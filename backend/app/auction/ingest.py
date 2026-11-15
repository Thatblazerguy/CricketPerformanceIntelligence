"""Auction data foundation: season rules, source import, reconciliation, purse state.

Pipeline (idempotent; safe to re-run after adding sources):

1. ``load_seasons``      data/auction/seasons.json → ``auction_seasons``.
2. ``import_sources``    normalized rows from ``app.auction.sources`` →
                         ``auction_history_records`` (raw observations, one per
                         source row, with provenance). Existing bundled CSV
                         imports are left untouched.
3. ``refresh_identity``  re-resolve unresolved/ambiguous source rows with the
                         stronger resolver in ``app.auction.identity``.
4. ``reconcile_lots``    one ``auction_lots`` row per player/season/acquisition,
                         merging sources: verification is ``corroborated`` when
                         two or more sources agree on the price, ``conflict``
                         when they disagree, ``single_source`` otherwise.
5. ``build_franchise_seasons`` purse before auction: sourced where a source
                         states it; derived as season purse − retention
                         salaries only where the retention list is complete.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.auction import sources as src
from app.auction.identity import IdentityResolver, PROJECT_ROOT
from app.models.models import (
    AuctionBacktestPrediction, AuctionFranchiseSeason, AuctionHistoryImport, AuctionHistoryRecord, AuctionLot, AuctionSeason,
)

# Lower number = preferred when sources disagree on a descriptive field.
SOURCE_PRIORITY = {
    "official-list/ipl-2022-auction": 0, "official-list/ipl-2023-auction": 0,
    "wikipedia/ipl-personnel-changes": 1,
    "outside-edge/ipl_auction": 2, "rixabhh/IPL-Auction-Analysis": 3,
}
PIPELINE_SOURCES = ("wikipedia/ipl-personnel-changes", "official-list/ipl-2022-auction",
                    "official-list/ipl-2023-auction")
# Seasons whose pre-auction retained list is complete in our sources, so
# purse = season purse − retention salaries is a valid derivation.
COMPLETE_RETENTION_SEASONS = {2022, 2024, 2025, 2026}
INDIA = {"india", "indian"}


def _norm_name(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def load_seasons(db: Session) -> int:
    payload = json.loads((PROJECT_ROOT / "data/auction/seasons.json").read_text())
    ladder = payload["default_bid_increments"]["ladder"]
    count = 0
    for row in payload["seasons"]:
        season = db.get(AuctionSeason, row["season"]) or AuctionSeason(season=row["season"])
        season.auction_date = date.fromisoformat(row["auction_date"]) if row.get("auction_date") else None
        season.auction_type = row["auction_type"]
        season.location = row.get("location")
        season.purse_lakh = row.get("purse_lakh")
        for key in ("min_squad", "max_squad", "max_overseas_squad", "max_overseas_xi",
                    "min_base_price_lakh", "max_retentions"):
            setattr(season, key, row.get(key))
        season.rtm_enabled = bool(row.get("rtm_enabled"))
        season.bid_increments = ladder
        season.rule_sources = {**row.get("provenance", {}),
                               "bid_increments": payload["default_bid_increments"]["provenance"],
                               "pool_size_reported": row.get("pool_size_reported"),
                               "players_presented_reported": row.get("players_presented_reported")}
        season.notes = row.get("notes")
        db.merge(season)
        count += 1
    db.commit()
    return count


def _record_key(row: Dict) -> str:
    raw = "|".join(str(row.get(k) or "") for k in (
        "source_name", "season", "player_name", "franchise", "status", "final_price_lakh", "set_code"))
    return hashlib.sha256(raw.encode()).hexdigest()


def import_sources(db: Session, resolver: Optional[IdentityResolver] = None) -> Dict:
    resolver = resolver or IdentityResolver(db)
    seasons = {s.season: s for s in db.scalars(select(AuctionSeason)).all()}
    normalized = src.load_all_normalized(PROJECT_ROOT)
    existing = set(db.scalars(select(AuctionHistoryRecord.source_record_key)).all())
    report = defaultdict(lambda: {"accepted": 0, "duplicate": 0, "identity": defaultdict(int)})
    for row in normalized["lots"]:
        key = _record_key(row)
        rep = report[row["source_name"]]
        if key in existing:
            rep["duplicate"] += 1
            continue
        existing.add(key)
        season = seasons.get(row["season"])
        player_id, status = resolver.resolve(row["player_name"], season.auction_date if season else None,
                                             prior_ipl=_prior_ipl(row.get("ipl_matches_before"), row.get("previous_franchise")))
        rep["identity"][status] += 1
        rep["accepted"] += 1
        dob = row.get("date_of_birth")
        db.add(AuctionHistoryRecord(
            player_id=player_id, source_player_name=row["player_name"], identity_match_status=status,
            auction_year=row["season"], franchise_name=row.get("franchise"), role=row.get("role"),
            nationality=("Indian" if (row.get("country") or "").casefold() in INDIA
                         else "Overseas" if row.get("country") else None),
            base_price_lakh=row.get("base_price_lakh"), final_price_lakh=row.get("final_price_lakh"),
            status=row["status"], acquisition_type=row["acquisition_type"],
            source_name=row["source_name"], source_url=row.get("source_url"), source_record_key=key,
            set_code=row.get("set_code"), lot_number=row.get("lot_number"),
            capped_status=row.get("capped_status"), is_rtm=row.get("is_rtm"),
            previous_franchise=row.get("previous_franchise"), country=row.get("country"),
            bowling_style=(row.get("bowling_style") or None) and str(row["bowling_style"])[:64],
            ipl_matches_before=int(row["ipl_matches_before"]) if row.get("ipl_matches_before") is not None else None,
            age_at_auction=row.get("age_at_auction"),
            date_of_birth=date.fromisoformat(dob) if dob else None,
            source_revision=row.get("source_revision"), source_tier=row.get("source_tier"),
        ))
    for name, rep in report.items():
        db.add(AuctionHistoryImport(
            filename=f"{name} (normalized)", source_name=name,
            source_url=next((r.get("source_url") for r in normalized["lots"] if r["source_name"] == name), None),
            accepted_rows=rep["accepted"], duplicate_rows=rep["duplicate"], rejected_rows=0,
            report_json={"identity_summary": dict(rep["identity"])}))
    db.commit()
    return {k: {"accepted": v["accepted"], "duplicate": v["duplicate"], "identity": dict(v["identity"])}
            for k, v in report.items()}, normalized["purse"]


def refresh_identity(db: Session, resolver: Optional[IdentityResolver] = None) -> Dict[str, int]:
    resolver = resolver or IdentityResolver(db)
    seasons = {s.season: s.auction_date for s in db.scalars(select(AuctionSeason)).all()}
    changed = defaultdict(int)
    # Only rows created by this pipeline are re-resolved. Rows imported by the
    # original auction module are never modified; their improved identity is
    # applied in memory during reconciliation and stored only on auction_lots.
    for rec in db.scalars(select(AuctionHistoryRecord).where(
            AuctionHistoryRecord.source_name.in_(PIPELINE_SOURCES))).all():
        pid, status = resolver.resolve(rec.source_player_name, seasons.get(int(rec.auction_year)),
                                       prior_ipl=_prior_ipl(rec.ipl_matches_before, rec.previous_franchise))
        if (pid, status) != (rec.player_id, rec.identity_match_status):
            rec.player_id, rec.identity_match_status = pid, status
            changed[status] += 1
    db.commit()
    return dict(changed)


def _similar_names(a: str, b: str) -> bool:
    ta, tb = _norm_name(a).split(), _norm_name(b).split()
    if not ta or not tb:
        return False
    ca, cb = "".join(ta), "".join(tb)
    if ca in cb or cb in ca:
        return True
    shared = set(ta) & set(tb)
    return len(shared) >= 2 or (ta[-1] == tb[-1] and ta[0][0] == tb[0][0]) or \
        (len(shared) == 1 and max(len(t) for t in shared) >= 6)


def _strongly_similar(a: str, b: str) -> bool:
    ta, tb = _norm_name(a).split(), _norm_name(b).split()
    ca, cb = "".join(ta), "".join(tb)
    shared = set(ta) & set(tb)
    return bool(ta and tb) and (ca in cb or cb in ca or any(len(t) >= 6 for t in shared))


def _prior_ipl(matches, previous_franchise) -> Optional[bool]:
    if matches is not None:
        return float(matches) > 0
    return True if previous_franchise else None


def _franchise(value) -> Optional[str]:
    return src.franchise_code(value) or (str(value).upper() if value and str(value).upper() in src.FRANCHISE_NAMES else None)


def _overseas(rec) -> Optional[bool]:
    if rec.country:
        return rec.country.strip().casefold() not in INDIA
    nat = (rec.nationality or "").strip().casefold()
    if nat in INDIA:
        return False
    if nat in ("overseas",):
        return True
    return None


def _capped(value) -> Optional[bool]:
    v = (value or "").strip().casefold()
    if v.startswith("uncapped"):
        return False
    if v.startswith("capped") or v.startswith("associate"):
        return True
    return None


def reconcile_lots(db: Session, resolver: Optional[IdentityResolver] = None) -> Dict:
    records = db.scalars(select(AuctionHistoryRecord)).all()
    resolver = resolver or IdentityResolver(db)
    season_dates = {s.season: s.auction_date for s in db.scalars(select(AuctionSeason)).all()}
    # Effective identity per source row. Legacy rows are re-resolved in memory
    # only — the stored records are left exactly as imported.
    ident = {}
    for rec in records:
        if rec.source_name in PIPELINE_SOURCES:
            ident[rec.id] = [rec.player_id, rec.identity_match_status]
        else:
            ident[rec.id] = list(resolver.resolve(rec.source_player_name, season_dates.get(int(rec.auction_year)),
                                                  prior_ipl=_prior_ipl(rec.ipl_matches_before, rec.previous_franchise)))
    pid_of = lambda r: ident[r.id][0]
    status_of = lambda r: ident[r.id][1]
    # Collision guard: one source listing two differently named people under the
    # same CPI id in one season means the resolution is unsafe for all of them.
    seen = defaultdict(set)
    for rec in records:
        if pid_of(rec):
            seen[(int(rec.auction_year), pid_of(rec), rec.source_name)].add(_norm_name(rec.source_player_name))
    collided = {(y, pid) for (y, pid, _s), names in seen.items() if len(names) > 1}
    for rec in records:
        if pid_of(rec) and (int(rec.auction_year), pid_of(rec)) in collided:
            ident[rec.id] = [None, "AMBIGUOUS"]
    groups: Dict[tuple, List[AuctionHistoryRecord]] = defaultdict(list)
    for rec in records:
        acq = "retained" if rec.status == "RETAINED" else "auction"
        key = pid_of(rec) or "name:" + _norm_name(rec.source_player_name)
        groups[(int(rec.auction_year), key, acq)].append(rec)

    # Spelling variants can split one transaction across sources. Two groups in
    # the same season/acquisition/franchise/price bucket are merged when their
    # names are similar AND no single source lists both (a source listing both
    # would mean two genuinely different players).
    merged = 0
    buckets = defaultdict(list)
    for gkey, recs in groups.items():
        r0 = next((r for r in recs if r.final_price_lakh), None)
        fr = next((_franchise(r.franchise_name) for r in recs if _franchise(r.franchise_name)), None)
        if r0 is not None and fr:
            buckets[(gkey[0], gkey[2], fr, round(float(r0.final_price_lakh)))].append(gkey)
    for keys in buckets.values():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: (k[1].startswith("name:"), k[1]))  # resolved groups absorb others
        alive = list(keys)
        for i, a in enumerate(keys):
            if a not in groups:
                continue
            for b in keys[i + 1:]:
                if b not in groups or b == a:
                    continue
                if {r.source_name for r in groups[a]} & {r.source_name for r in groups[b]}:
                    # A source can double-list one transaction under two spellings.
                    # Accept only for distinctive names at a non-minimum price.
                    if not (_strongly_similar(groups[a][0].source_player_name, groups[b][0].source_player_name)
                            and float(groups[a][0].final_price_lakh or 0) >= 50):
                        continue
                if _similar_names(groups[a][0].source_player_name, groups[b][0].source_player_name):
                    if not a[1].startswith("name:") and not b[1].startswith("name:"):
                        for r in groups[b]:
                            ident[r.id][1] = "AMBIGUOUS"  # sources disagree on identity
                    groups[a].extend(groups.pop(b))
                    merged += 1

    # Keep lot ids stable across rebuilds (backtest predictions reference them).
    existing_ids = {(l.season, l.player_key, l.acquisition_type): l.id for l in db.scalars(select(AuctionLot)).all()}
    db.execute(delete(AuctionBacktestPrediction).where(AuctionBacktestPrediction.lot_id.notin_(
        [existing_ids[k] for k in existing_ids if k in {(g[0], g[1][:64], g[2]) for g in groups}] or [""])))
    db.execute(text("ALTER TABLE auction_backtest_predictions DROP CONSTRAINT IF EXISTS auction_backtest_predictions_lot_id_fkey"))
    db.execute(delete(AuctionLot))
    stats = defaultdict(int)
    for (season, key, acq), recs in groups.items():
        recs.sort(key=lambda r: SOURCE_PRIORITY.get(r.source_name, 9))
        sold_like = [r for r in recs if r.status in ("SOLD", "RETAINED")]
        status = "RETAINED" if acq == "retained" else ("SOLD" if sold_like else "UNSOLD")
        prices = sorted({round(float(r.final_price_lakh), 2) for r in sold_like if r.final_price_lakh is not None})
        distinct_sources = {r.source_name for r in recs}
        conflict = None
        if len(prices) > 1 and (prices[-1] - prices[0]) > max(1.0, 0.01 * prices[-1]):
            verification = "conflict"
            conflict = "Sources disagree on price: " + ", ".join(
                f"{r.source_name}={r.final_price_lakh}" for r in sold_like if r.final_price_lakh is not None)
        elif len(distinct_sources) >= 2 and (prices or status == "UNSOLD"):
            verification = "corroborated"
        else:
            verification = "single_source"
        # SOLD vs UNSOLD disagreement is also a conflict.
        if status == "SOLD" and any(r.status == "UNSOLD" for r in recs):
            verification, conflict = "conflict", "Sources disagree on sold/unsold outcome"
        first = lambda attr: next((getattr(r, attr) for r in recs if getattr(r, attr) not in (None, "")), None)
        franchise = next((_franchise(r.franchise_name) for r in sold_like if _franchise(r.franchise_name)), None)
        chosen_price = next((float(r.final_price_lakh) for r in sold_like if r.final_price_lakh is not None), None)
        if verification == "conflict" and len(prices) == 2:
            # Rounding can only remove precision, never create it: when one source
            # reports a whole-crore figure and another a finer one, keep the finer.
            round_vals = [p for p in prices if p % 100 == 0]
            fine_vals = [p for p in prices if p % 100 != 0]
            if len(round_vals) == 1 and len(fine_vals) == 1 and abs(fine_vals[0] - round_vals[0]) < 100:
                chosen_price = fine_vals[0]
                conflict += f" — resolved to {fine_vals[0]:g} (other value is a whole-crore rounding)"
        role = next((src.normalize_role(r.role) for r in recs if src.normalize_role(r.role)), None) \
            or next((src.role_from_set(r.set_code) for r in recs if src.role_from_set(r.set_code)), None)
        kind = next((src.bowling_kind(r.bowling_style, r.set_code) for r in recs
                     if src.bowling_kind(r.bowling_style, r.set_code)), None)
        overseas = next((_overseas(r) for r in recs if _overseas(r) is not None), None)
        db.add(AuctionLot(
            id=existing_ids.get((season, key[:64], acq)),
            season=season, player_key=key[:64], player_id=None if key.startswith("name:") else key,
            player_name=recs[0].source_player_name,
            identity_status=status_of(recs[0]) if key.startswith("name:") else
            ("MATCHED" if any(status_of(r) == "MATCHED" for r in recs) else "DISAMBIGUATED"),
            status=status, acquisition_type=acq, franchise=franchise,
            previous_franchise=_franchise(first("previous_franchise")),
            base_price_lakh=first("base_price_lakh"),
            final_price_lakh=chosen_price if status != "UNSOLD" else None,
            set_code=first("set_code"), lot_number=first("lot_number"), role=role, bowling_kind=kind,
            overseas=overseas, capped=_capped(first("capped_status")),
            is_rtm=any(bool(r.is_rtm) for r in recs) if any(r.is_rtm is not None for r in recs) else None,
            age_at_auction=first("age_at_auction"), ipl_matches_before=first("ipl_matches_before"),
            verification=verification, source_count=len(distinct_sources),
            sources=[{"source": r.source_name, "record_id": r.id, "status": r.status,
                      "price_lakh": float(r.final_price_lakh) if r.final_price_lakh is not None else None,
                      "url": r.source_url, "revision": r.source_revision} for r in recs],
            conflict_note=conflict,
        ))
        stats[verification] += 1
    db.flush()
    db.execute(text("""ALTER TABLE auction_backtest_predictions ADD CONSTRAINT auction_backtest_predictions_lot_id_fkey
                       FOREIGN KEY (lot_id) REFERENCES auction_lots(id) ON DELETE CASCADE"""))
    db.commit()
    return {"lots": sum(stats.values()), "verification": dict(stats), "name_groups_merged": merged}


def build_franchise_seasons(db: Session, purse_rows: List[Dict]) -> Dict:
    seasons = {s.season: s for s in db.scalars(select(AuctionSeason)).all()}
    sourced = {(r["season"], r["franchise"]): r for r in purse_rows}
    db.execute(delete(AuctionFranchiseSeason))
    lots = db.scalars(select(AuctionLot).where(AuctionLot.status == "RETAINED")).all()
    retained = defaultdict(list)
    for lot in lots:
        if lot.franchise:
            retained[(lot.season, lot.franchise)].append(lot)
    out = defaultdict(int)
    teams_by_season = defaultdict(set)
    for (season, fr) in retained:
        teams_by_season[season].add(fr)
    for season, fr in sourced:
        teams_by_season[season].add(fr)
    checks = []
    for season, teams in teams_by_season.items():
        cfg = seasons.get(season)
        for fr in sorted(teams):
            rows = retained.get((season, fr), [])
            spend = sum(float(r.final_price_lakh or 0) for r in rows)
            known_salary = all(r.final_price_lakh is not None for r in rows)
            src_row = sourced.get((season, fr))
            if src_row and src_row.get("purse_remaining_lakh") is not None:
                purse, basis = float(src_row["purse_remaining_lakh"]), "sourced"
                if cfg and cfg.purse_lakh and known_salary:
                    checks.append({"season": season, "franchise": fr,
                                   "sourced_purse_lakh": purse, "purse_minus_retained_lakh": float(cfg.purse_lakh) - spend})
            elif cfg and cfg.purse_lakh and season in COMPLETE_RETENTION_SEASONS and known_salary:
                purse, basis = float(cfg.purse_lakh) - spend, "derived_from_retentions"
            else:
                purse, basis = None, "unknown"
            overseas = sum(1 for r in rows if r.overseas)
            max_squad = cfg.max_squad if cfg else None
            max_os = cfg.max_overseas_squad if cfg else None
            db.add(AuctionFranchiseSeason(
                season=season, franchise=fr, purse_before_auction_lakh=purse, purse_basis=basis,
                retained_count=len(rows), retained_overseas=overseas, retained_spend_lakh=spend if known_salary else None,
                slots_left=(src_row or {}).get("slots_left") or (max_squad - len(rows) if max_squad and season in COMPLETE_RETENTION_SEASONS else None),
                overseas_slots_left=(src_row or {}).get("overseas_slots_left") or (max_os - overseas if max_os and season in COMPLETE_RETENTION_SEASONS else None),
                source={"purse": src_row.get("source_url") if src_row else None,
                        "retention_sources": sorted({s["source"] for r in rows for s in r.sources})}))
            out[basis] += 1
    db.commit()
    return {"rows": dict(out), "consistency_checks": checks}


def run_full_ingest(db: Session) -> Dict:
    seasons = load_seasons(db)
    resolver = IdentityResolver(db)
    imported, purse_rows = import_sources(db, resolver)
    identity = refresh_identity(db, resolver)
    lots = reconcile_lots(db, resolver)
    franchises = build_franchise_seasons(db, purse_rows)
    return {"seasons": seasons, "imported": imported, "identity_refreshed": identity,
            "lots": lots, "franchise_seasons": franchises}
