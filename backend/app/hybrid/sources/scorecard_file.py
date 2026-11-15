"""Verified scorecard import adapter.

Imports historical scorecards supplied as a JSON bundle (format documented in
docs/SCORECARD_IMPORT_FORMAT.md). This is how data from a provider CPI has a
licence or written permission for gets in: CPI never scrapes a site to build one.

Every bundle must name its source and the licence/permission it is used under;
bundles without that are rejected. Each innings is checked for internal
consistency before it can count towards career statistics. Missing fields stay
NULL; nothing is inferred (balls bowled are only derived from overs when the
bundle states balls-per-over, because 8-ball overs were used historically).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.hybrid import formats
from app.hybrid.identity import MatchKey
from app.hybrid.people import resolve_player
from app.hybrid.registry import find_or_create_canonical, log_event, refresh_coverage
from app.hybrid.sources.base import SourceAdapter, SourceInfo
from app.models.models import (
    CanonicalMatchRecord, MatchAppearance, MatchSourceRef, ScorecardBatting, ScorecardBowling, ScorecardInnings,
)

NOT_OUT_KINDS = {"not out", "retired hurt", "retired not out", "absent hurt", "absent"}


class ScorecardBundleError(ValueError):
    pass


def overs_to_balls(overs: Optional[str], balls_per_over: Optional[int]) -> Optional[int]:
    if overs in (None, "") or not balls_per_over:
        return None
    whole, _, part = str(overs).partition(".")
    try:
        w, p = int(whole), int(part or 0)
    except ValueError:
        return None
    if p >= balls_per_over:
        return None
    return w * balls_per_over + p


def is_out_from(entry: Dict) -> Optional[bool]:
    if entry.get("dnb"):
        return None
    if entry.get("out") is not None:
        return bool(entry["out"])
    kind = (entry.get("dismissal") or "").strip().lower()
    if not kind:
        return None
    return kind not in NOT_OUT_KINDS


def validate_innings(inn: Dict) -> List[str]:
    """Internal-consistency checks. Returns issue strings (empty = consistent)."""
    issues: List[str] = []
    total = inn.get("total")
    bat = [b for b in inn.get("batting", []) if not b.get("dnb")]
    extras = (inn.get("extras") or {})
    ext_total = extras.get("total")
    if ext_total is None and all(extras.get(k) is not None for k in ("byes", "leg_byes", "wides", "no_balls")):
        ext_total = sum(extras.get(k) or 0 for k in ("byes", "leg_byes", "wides", "no_balls", "penalty"))
    if total is not None and ext_total is not None and bat and all(b.get("runs") is not None for b in bat):
        s = sum(b["runs"] for b in bat) + ext_total
        if s != total:
            issues.append(f"batting runs + extras = {s}, innings total = {total}")
    wk = inn.get("wickets")
    outs = [is_out_from(b) for b in bat]
    if wk is not None and outs and all(o is not None for o in outs) and sum(outs) != wk:
        issues.append(f"{sum(outs)} batters out, innings wickets = {wk}")
    bowl = inn.get("bowling", [])
    if wk is not None and bowl and all(b.get("wickets") is not None for b in bowl):
        if sum(b["wickets"] for b in bowl) > wk:
            issues.append("bowler wickets exceed innings wickets")
    if total is not None and bowl and all(b.get("runs") is not None for b in bowl):
        byes = extras.get("byes"), extras.get("leg_byes")
        if None not in byes:
            conceded = sum(b["runs"] for b in bowl) + byes[0] + byes[1] + (extras.get("penalty") or 0)
            if conceded != total:
                issues.append(f"bowler runs + byes + leg byes = {conceded}, innings total = {total}")
    return issues


def _status(issues: List[str], inn: Dict) -> str:
    if issues:
        return "inconsistent"
    bat = [b for b in inn.get("batting", []) if not b.get("dnb")]
    if inn.get("total") is None or not bat or any(b.get("runs") is None for b in bat):
        return "insufficient_fields"
    return "validated"


@dataclass
class ImportReport:
    source_key: str
    matches_in_bundle: int = 0
    created: int = 0
    linked_to_existing: int = 0
    ambiguous: List[Dict] = field(default_factory=list)
    rejected: List[Dict] = field(default_factory=list)
    innings_inconsistent: int = 0
    players_resolved: int = 0
    players_unresolved: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        d = self.__dict__.copy()
        d["players_unresolved"] = sorted(set(self.players_unresolved))[:200]
        return d


class ScorecardFileAdapter(SourceAdapter):
    info = SourceInfo(
        key="scorecard_file", name="Verified scorecard import", data_level="scorecard", access="user_supplied",
        licence="Per bundle: each bundle must state its source and the licence or permission it is used under.",
        coverage="Whatever licensed scorecards are supplied. Ships with none.",
        integrated=True,
        notes=["Use for licensed archives (e.g. a CricketArchive or ESPNcricinfo data licence, BCCI permission).",
               "Bundles without source attribution and licence are rejected."],
    )

    def refresh_inventory(self, db: Session) -> Dict[str, int]:
        return {"not_applicable": 1}

    def import_bundle(self, db: Session, bundle: Dict) -> ImportReport:
        src = bundle.get("source") or {}
        key = (src.get("key") or "").strip()
        if not key or not src.get("name") or not src.get("licence"):
            raise ScorecardBundleError("Bundle must include source.key, source.name and source.licence")
        if key == "cricsheet":
            raise ScorecardBundleError("source.key 'cricsheet' is reserved for the ball-by-ball layer")
        report = ImportReport(source_key=key, matches_in_bundle=len(bundle.get("matches", [])))
        touched: List[str] = []
        for raw in bundle.get("matches", []):
            try:
                with db.begin_nested():
                    cid = self._import_match(db, src, raw, report)
                if cid:
                    touched.append(cid)
            except (ScorecardBundleError, KeyError, ValueError, TypeError) as exc:
                report.rejected.append({"source_match_id": raw.get("source_match_id"), "error": str(exc)[:300]})
        if touched:
            from app.hybrid.career import detect_conflicts
            for cid in touched:
                detect_conflicts(db, cid)
            refresh_coverage(db, touched)
        log_event(db, key, "import_scorecards", "ok" if not report.rejected else "partial",
                  json.dumps({"ambiguous": report.ambiguous[:20], "rejected": report.rejected[:20]})[:4000],
                  created=report.created, linked=report.linked_to_existing, rejected=len(report.rejected),
                  ambiguous=len(report.ambiguous), inconsistent_innings=report.innings_inconsistent)
        return report

    def import_file(self, db: Session, path: Path) -> ImportReport:
        return self.import_bundle(db, json.loads(Path(path).read_text(encoding="utf-8")))

    # ------------------------------------------------------------------ internals

    def _import_match(self, db: Session, src: Dict, raw: Dict, report: ImportReport) -> Optional[str]:
        sid = str(raw["source_match_id"])
        fc = formats.normalise(raw.get("format_class"))
        if not fc:
            raise ScorecardBundleError(f"unknown format_class {raw.get('format_class')!r}")
        teams = raw["teams"]
        if len(teams) != 2:
            raise ScorecardBundleError("teams must list exactly two teams")
        gender = raw.get("gender", "male")
        result = raw.get("result") or {}
        toss = raw.get("toss") or {}
        innings = raw.get("innings", [])
        key = MatchKey(date.fromisoformat(raw["start_date"]), gender, fc, teams, raw.get("venue"),
                       raw.get("competition"), result.get("winner"), result.get("type"),
                       {int(i["number"]): int(i["total"]) for i in innings if i.get("total") is not None})

        ref = db.scalar(select(MatchSourceRef).where(MatchSourceRef.source_key == src["key"],
                                                     MatchSourceRef.source_match_id == sid))
        if ref is not None:
            rec = db.get(CanonicalMatchRecord, ref.canonical_match_id)
            db.execute(delete(ScorecardInnings).where(ScorecardInnings.source_ref_id == ref.id))  # re-import
            method, decision = "matched", None
        else:
            rec, decision = find_or_create_canonical(db, key, defaults={
                "match_format": raw.get("match_format") or fc, "season": raw.get("season"),
                "end_date": date.fromisoformat(raw["end_date"]) if raw.get("end_date") else None,
                "country": raw.get("country"), "toss_winner_name": toss.get("winner"),
                "toss_decision": toss.get("decision"), "coverage_status": "UNKNOWN"})
            if rec is None:
                report.ambiguous.append({"source_match_id": sid, "candidates": decision.candidates})
                return None
            method = "matched" if decision.status == "matched" else "primary"
            if decision.status == "matched":
                report.linked_to_existing += 1
            else:
                report.created += 1
            ref = MatchSourceRef(canonical_match_id=rec.id, source_key=src["key"], source_match_id=sid,
                                 data_level="scorecard", match_method=method,
                                 match_confidence=decision.confidence if decision.status == "matched" else 1.0,
                                 match_evidence=decision.evidence, source_url=raw.get("url") or src.get("url"),
                                 attribution=f"{src['name']} ({src['licence']})"[:512])
            db.add(ref)
            db.flush()
        # Fill metadata only where the canonical record has none: never overwrite ball-by-ball facts.
        for attr, val in (("toss_winner_name", toss.get("winner")), ("toss_decision", toss.get("decision")),
                          ("winner_name", result.get("winner")), ("result_type", result.get("type")),
                          ("venue_name", raw.get("venue")), ("competition_name", raw.get("competition")),
                          ("season", raw.get("season")), ("country", raw.get("country"))):
            if val is not None and getattr(rec, attr) in (None, ""):
                setattr(rec, attr, val)

        bpo = raw.get("balls_per_over")
        seen_players = set(db.scalars(select(MatchAppearance.player_id).where(MatchAppearance.canonical_match_id == rec.id)))
        for inn in innings:
            issues = validate_innings(inn)
            status = _status(issues, inn)
            if status == "inconsistent":
                report.innings_inconsistent += 1
            ex = inn.get("extras") or {}
            si = ScorecardInnings(canonical_match_id=rec.id, source_ref_id=ref.id, innings_number=int(inn["number"]),
                                  batting_team_name=inn["team"], total_runs=inn.get("total"), wickets=inn.get("wickets"),
                                  overs=None if inn.get("overs") is None else str(inn["overs"]), balls_per_over=bpo,
                                  extras_total=ex.get("total"), byes=ex.get("byes"), leg_byes=ex.get("leg_byes"),
                                  wides=ex.get("wides"), no_balls=ex.get("no_balls"), penalty_runs=ex.get("penalty"),
                                  declared=inn.get("declared"), forfeited=inn.get("forfeited"),
                                  validation_status=status, validation_issues=issues)
            db.add(si)
            db.flush()
            bowling_team = teams[1] if inn["team"] == teams[0] else teams[0]
            for pos, b in enumerate(inn.get("batting", []), 1):
                pid, ident = self._resolve(db, b, inn["team"], report)
                db.add(ScorecardBatting(
                    scorecard_innings_id=si.id, canonical_match_id=rec.id, player_id=pid, identity_status=ident,
                    source_player_name=b["name"], source_player_id=b.get("id"), batting_position=b.get("position", pos),
                    did_not_bat=bool(b.get("dnb")), runs=b.get("runs"), balls_faced=b.get("balls"),
                    minutes=b.get("minutes"), fours=b.get("fours"), sixes=b.get("sixes"), is_out=is_out_from(b),
                    dismissal_type=b.get("dismissal"), dismissal_text=b.get("how_out")))
                self._appear(db, rec.id, pid, inn["team"], src["key"], seen_players)
            for b in inn.get("bowling", []):
                pid, ident = self._resolve(db, b, bowling_team, report)
                db.add(ScorecardBowling(
                    scorecard_innings_id=si.id, canonical_match_id=rec.id, player_id=pid, identity_status=ident,
                    source_player_name=b["name"], source_player_id=b.get("id"),
                    overs=None if b.get("overs") is None else str(b["overs"]),
                    legal_balls=b.get("balls") if b.get("balls") is not None else overs_to_balls(b.get("overs"), bpo),
                    maidens=b.get("maidens"), runs_conceded=b.get("runs"), wickets=b.get("wickets"),
                    wides=b.get("wides"), no_balls=b.get("no_balls"), economy_reported=b.get("economy")))
                self._appear(db, rec.id, pid, bowling_team, src["key"], seen_players)
        db.flush()
        return rec.id

    @staticmethod
    def _resolve(db: Session, entry: Dict, team: str, report: ImportReport):
        pid, status = resolve_player(db, source_player_id=entry.get("id"), name=entry["name"], team_name=team)
        if pid:
            report.players_resolved += 1
        else:
            report.players_unresolved.append(entry["name"])
        return pid, status

    @staticmethod
    def _appear(db: Session, cid: str, pid: Optional[str], team: str, source_key: str, seen: set) -> None:
        if pid and pid not in seen:
            db.add(MatchAppearance(canonical_match_id=cid, player_id=pid, team_name=team, source_key=source_key))
            seen.add(pid)
