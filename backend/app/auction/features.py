"""Point-in-time player features for auction valuation (leakage-free by construction).

Every query is bounded by ``start_date < as_of``; nothing on or after the
auction date can enter a feature. Data come from the persisted per-innings
scouting tables (``scouting_bat_innings`` / ``scouting_bowl_innings``), so the
cricket rules (balls faced, bowler wickets, phases, pace/spin splits) are the
same ones used by Players, Scouting and Matchups.

Scope: men's T20 cricket — franchise/domestic T20 (``T20``) and T20
internationals (``T20I``). Competitions are *not* treated as equivalent:

* IPL figures are kept separately and are the primary evidence.
* Other competitions are converted to an IPL-equivalent scale with
  competition factors estimated from players who batted/bowled in both that
  competition and the IPL inside the same window ("bridge players"); factors
  are shrunk towards 1 by bridge sample size, and competitions with too few
  bridge players get an uncertainty discount instead of a factor.
* Recent matches weigh more (exponential decay, one-year half-life).
* Rates are shrunk towards the population mean with pseudo-counts, so a
  handful of balls never produces an extreme rate; raw sample sizes are
  always returned alongside.

Missing data stays ``None`` — a player with no bowling has no bowling rate,
not an economy of zero.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.models import AuctionFeatureSnapshot

FEATURE_VERSION = "v2.1"
WINDOW_YEARS = 3
HALF_LIFE_DAYS = 365.0
IPL_NAME = "Indian Premier League"

# Pseudo-counts (in balls) for shrinkage towards the population rate.
K_BAT_BALLS = 120
K_BOWL_BALLS = 120
K_DISMISSALS = 4

_BAT_SQL = text("""
SELECT b.player_id,
       CASE WHEN t.name = :ipl THEN 'IPL' WHEN b.match_format = 'T20I' THEN 'T20I'
            ELSE COALESCE(b.tournament_id, 'other') END AS comp,
       COUNT(*) AS inns, COUNT(DISTINCT b.match_id) AS matches,
       SUM(b.runs) AS runs, SUM(b.balls) AS balls, SUM(b.fours) AS fours, SUM(b.sixes) AS sixes,
       SUM(b.dots) AS dots, SUM(CASE WHEN b.dismissed THEN 1 ELSE 0 END) AS outs,
       SUM(b.pp_runs) pp_runs, SUM(b.pp_balls) pp_balls, SUM(b.mid_runs) mid_runs, SUM(b.mid_balls) mid_balls,
       SUM(b.death_runs) death_runs, SUM(b.death_balls) death_balls,
       SUM(b.pace_runs) pace_runs, SUM(b.pace_balls) pace_balls, SUM(b.spin_runs) spin_runs, SUM(b.spin_balls) spin_balls,
       SUM(CASE WHEN b.batting_position <= 3 THEN 1 ELSE 0 END) AS top_inns,
       SUM(CASE WHEN b.batting_position BETWEEN 4 AND 5 THEN 1 ELSE 0 END) AS mid_inns,
       SUM(CASE WHEN b.batting_position BETWEEN 6 AND 8 THEN 1 ELSE 0 END) AS low_inns,
       SUM(CASE WHEN b.is_chase THEN b.runs ELSE 0 END) AS chase_runs,
       SUM(CASE WHEN b.is_chase THEN b.balls ELSE 0 END) AS chase_balls,
       SUM(power(0.5, (:as_of - b.start_date) / :hl)) AS w_inns,
       SUM(b.runs * power(0.5, (:as_of - b.start_date) / :hl)) AS w_runs,
       SUM(b.balls * power(0.5, (:as_of - b.start_date) / :hl)) AS w_balls,
       SUM(CASE WHEN b.dismissed THEN power(0.5, (:as_of - b.start_date) / :hl) ELSE 0 END) AS w_outs,
       SUM((b.fours + b.sixes) * power(0.5, (:as_of - b.start_date) / :hl)) AS w_bnd,
       SUM(b.dots * power(0.5, (:as_of - b.start_date) / :hl)) AS w_dots,
       MAX(b.start_date) AS last_date, MIN(b.start_date) AS first_date
FROM scouting_bat_innings b LEFT JOIN tournaments t ON t.id = b.tournament_id
WHERE b.gender = 'male' AND b.match_format IN ('T20', 'T20I')
  AND b.start_date < :as_of AND b.start_date >= :since
  AND (:all_players OR b.player_id = ANY(:ids))
GROUP BY 1, 2
""")

_BOWL_SQL = text("""
SELECT b.player_id,
       CASE WHEN t.name = :ipl THEN 'IPL' WHEN b.match_format = 'T20I' THEN 'T20I'
            ELSE COALESCE(b.tournament_id, 'other') END AS comp,
       COUNT(*) AS inns, SUM(b.legal_balls) AS balls, SUM(b.runs) AS runs, SUM(b.wickets) AS wkts,
       SUM(b.dots) AS dots, SUM(b.fours + b.sixes) AS bnd,
       SUM(b.pp_balls) pp_balls, SUM(b.pp_runs) pp_runs, SUM(b.pp_wkts) pp_wkts,
       SUM(b.mid_balls) mid_balls, SUM(b.mid_runs) mid_runs, SUM(b.mid_wkts) mid_wkts,
       SUM(b.death_balls) death_balls, SUM(b.death_runs) death_runs, SUM(b.death_wkts) death_wkts,
       SUM(b.legal_balls * power(0.5, (:as_of - b.start_date) / :hl)) AS w_balls,
       SUM(b.runs * power(0.5, (:as_of - b.start_date) / :hl)) AS w_runs,
       SUM(b.wickets * power(0.5, (:as_of - b.start_date) / :hl)) AS w_wkts,
       SUM(b.dots * power(0.5, (:as_of - b.start_date) / :hl)) AS w_dots,
       SUM(power(0.5, (:as_of - b.start_date) / :hl)) AS w_inns,
       MAX(b.start_date) AS last_date
FROM scouting_bowl_innings b LEFT JOIN tournaments t ON t.id = b.tournament_id
WHERE b.gender = 'male' AND b.match_format IN ('T20', 'T20I')
  AND b.start_date < :as_of AND b.start_date >= :since
  AND (:all_players OR b.player_id = ANY(:ids))
GROUP BY 1, 2
""")

_CAREER_SQL = text("""
SELECT player_id,
       COUNT(DISTINCT match_id) FILTER (WHERE is_ipl) AS ipl_matches_career,
       COUNT(DISTINCT match_id) AS t20_matches_career,
       MIN(start_date) AS first_t20, MAX(start_date) FILTER (WHERE is_ipl) AS last_ipl
FROM (
  SELECT b.player_id, b.match_id, b.start_date, t.name = :ipl AS is_ipl
  FROM scouting_bat_innings b LEFT JOIN tournaments t ON t.id = b.tournament_id
  WHERE b.gender='male' AND b.match_format IN ('T20','T20I') AND b.start_date < :as_of AND b.player_id = ANY(:ids)
  UNION ALL
  SELECT b.player_id, b.match_id, b.start_date, t.name = :ipl
  FROM scouting_bowl_innings b LEFT JOIN tournaments t ON t.id = b.tournament_id
  WHERE b.gender='male' AND b.match_format IN ('T20','T20I') AND b.start_date < :as_of AND b.player_id = ANY(:ids)
) x GROUP BY player_id
""")

_KEEPING_SQL = text("""
SELECT w.fielder_id AS player_id, COUNT(*) FILTER (WHERE lower(w.dismissal_type) = 'stumped') AS stumpings,
       COUNT(DISTINCT mi.match_id) AS matches_with_dismissal
FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
WHERE w.fielder_id = ANY(:ids) AND m.gender = 'male' AND m.match_format IN ('T20','T20I')
  AND m.start_date < :as_of AND m.start_date >= :since
GROUP BY w.fielder_id
""")


def _ratio(num, den, scale=1.0):
    return (float(num) * scale / float(den)) if den else None


def _shrink(num, den, prior_rate, k):
    """Posterior-mean style shrinkage of num/den towards prior_rate with k pseudo-units."""
    if den is None or prior_rate is None:
        return None
    return (float(num or 0) + prior_rate * k) / (float(den or 0) + k)


class CompetitionFactors:
    """IPL-equivalence factors from bridge players (estimated before ``as_of``)."""

    def __init__(self, bat_rows: List[dict], bowl_rows: List[dict]):
        by_player_bat = defaultdict(dict)
        for r in bat_rows:
            by_player_bat[r["player_id"]][r["comp"]] = r
        by_player_bowl = defaultdict(dict)
        for r in bowl_rows:
            by_player_bowl[r["player_id"]][r["comp"]] = r
        self.bat_sr, self.bowl_econ, self.bridges = {}, {}, {}
        ratios_sr, ratios_ec = defaultdict(list), defaultdict(list)
        for comps in by_player_bat.values():
            ipl = comps.get("IPL")
            if not ipl or (ipl["balls"] or 0) < 60:
                continue
            ipl_sr = _ratio(ipl["runs"], ipl["balls"], 100)
            for comp, r in comps.items():
                if comp != "IPL" and (r["balls"] or 0) >= 60 and ipl_sr:
                    ratios_sr[comp].append(math.log(ipl_sr / max(_ratio(r["runs"], r["balls"], 100), 1e-6)))
        for comps in by_player_bowl.values():
            ipl = comps.get("IPL")
            if not ipl or (ipl["balls"] or 0) < 60:
                continue
            ipl_ec = _ratio(ipl["runs"], ipl["balls"], 6)
            for comp, r in comps.items():
                if comp != "IPL" and (r["balls"] or 0) >= 60 and ipl_ec:
                    ratios_ec[comp].append(math.log(ipl_ec / max(_ratio(r["runs"], r["balls"], 6), 1e-6)))
        for comp, vals in ratios_sr.items():
            n = len(vals)
            med = sorted(vals)[n // 2]
            # Shrink the log-ratio towards 0 (no adjustment) by bridge count.
            self.bat_sr[comp] = math.exp(med * n / (n + 8))
            self.bridges[comp] = max(self.bridges.get(comp, 0), n)
        for comp, vals in ratios_ec.items():
            n = len(vals)
            med = sorted(vals)[n // 2]
            self.bowl_econ[comp] = math.exp(med * n / (n + 8))
            self.bridges[comp] = max(self.bridges.get(comp, 0), n)

    def reliability(self, comp: str) -> float:
        """Weight multiplier for non-IPL evidence: grows with bridge players, capped below IPL."""
        if comp == "IPL":
            return 1.0
        n = self.bridges.get(comp, 0)
        return 0.75 * n / (n + 10)


def _fetch(db: Session, sql, as_of: date, ids: Optional[List[str]], since: date) -> List[dict]:
    params = {"ipl": IPL_NAME, "as_of": as_of, "since": since, "hl": HALF_LIFE_DAYS,
              "all_players": ids is None, "ids": ids or []}
    return [dict(r) for r in db.execute(sql, params).mappings()]


def compute_features(db: Session, player_ids: Iterable[str], as_of: date) -> Dict[str, dict]:
    ids = sorted({p for p in player_ids if p})
    if not ids:
        return {}
    since = as_of - timedelta(days=int(365.25 * WINDOW_YEARS))
    # Competition factors need the full bridge population in the same window.
    all_bat = _fetch(db, _BAT_SQL, as_of, None, since)
    all_bowl = _fetch(db, _BOWL_SQL, as_of, None, since)
    factors = CompetitionFactors(all_bat, all_bowl)
    wanted = set(ids)
    bat_by = defaultdict(list)
    for r in all_bat:
        if r["player_id"] in wanted:
            bat_by[r["player_id"]].append(r)
    bowl_by = defaultdict(list)
    for r in all_bowl:
        if r["player_id"] in wanted:
            bowl_by[r["player_id"]].append(r)

    # Population priors (IPL scale) for shrinkage.
    ipl_bat = [r for r in all_bat if r["comp"] == "IPL"]
    ipl_bowl = [r for r in all_bowl if r["comp"] == "IPL"]
    prior_sr = _ratio(sum(r["runs"] or 0 for r in ipl_bat), sum(r["balls"] or 0 for r in ipl_bat), 100) or 130.0
    prior_avg = _ratio(sum(r["runs"] or 0 for r in ipl_bat), sum(r["outs"] or 0 for r in ipl_bat)) or 25.0
    prior_bnd = _ratio(sum((r["fours"] or 0) + (r["sixes"] or 0) for r in ipl_bat), sum(r["balls"] or 0 for r in ipl_bat)) or 0.15
    prior_econ = _ratio(sum(r["runs"] or 0 for r in ipl_bowl), sum(r["balls"] or 0 for r in ipl_bowl), 6) or 8.0
    prior_bsr = _ratio(sum(r["balls"] or 0 for r in ipl_bowl), sum(r["wkts"] or 0 for r in ipl_bowl)) or 20.0
    prior_dot = _ratio(sum(r["dots"] or 0 for r in ipl_bowl), sum(r["balls"] or 0 for r in ipl_bowl)) or 0.38
    phase_prior = {}
    for ph in ("pp", "mid", "death"):
        phase_prior[f"bat_{ph}"] = _ratio(sum(r[f"{ph}_runs"] or 0 for r in ipl_bat), sum(r[f"{ph}_balls"] or 0 for r in ipl_bat), 100)
        phase_prior[f"bowl_{ph}"] = _ratio(sum(r[f"{ph}_runs"] or 0 for r in ipl_bowl), sum(r[f"{ph}_balls"] or 0 for r in ipl_bowl), 6)

    career = {r["player_id"]: r for r in db.execute(_CAREER_SQL, {"ipl": IPL_NAME, "as_of": as_of, "ids": ids}).mappings()}
    keeping = {r["player_id"]: r for r in db.execute(_KEEPING_SQL, {"as_of": as_of, "since": since, "ids": ids}).mappings()}

    out = {}
    for pid in ids:
        f: Dict[str, Optional[float]] = {"as_of": as_of.isoformat(), "feature_version": FEATURE_VERSION}
        brs = bat_by.get(pid, [])
        # --- batting --------------------------------------------------------
        ipl = next((r for r in brs if r["comp"] == "IPL"), None)
        f["ipl_bat_inns"] = int(ipl["inns"]) if ipl else 0
        f["ipl_bat_balls"] = int(ipl["balls"] or 0) if ipl else 0
        f["ipl_bat_sr"] = _ratio(ipl["runs"], ipl["balls"], 100) if ipl else None
        f["ipl_bat_avg"] = _ratio(ipl["runs"], ipl["outs"]) if ipl else None
        # Equivalent (IPL-scale) recency-weighted totals across competitions.
        eq_runs = eq_balls = eq_outs = eq_bnd = eq_dots = w_inns = 0.0
        raw = defaultdict(float)
        comps_used = set()
        for r in brs:
            rel = factors.reliability(r["comp"])
            if rel <= 0:
                continue
            factor = factors.bat_sr.get(r["comp"], 1.0) if r["comp"] != "IPL" else 1.0
            comps_used.add(r["comp"])
            eq_runs += float(r["w_runs"] or 0) * factor * rel
            eq_balls += float(r["w_balls"] or 0) * rel
            eq_outs += float(r["w_outs"] or 0) * rel
            eq_bnd += float(r["w_bnd"] or 0) * rel
            eq_dots += float(r["w_dots"] or 0) * rel
            w_inns += float(r["w_inns"] or 0) * rel
            for key in ("runs", "balls", "outs", "inns", "fours", "sixes", "pp_runs", "pp_balls", "mid_runs",
                        "mid_balls", "death_runs", "death_balls", "pace_runs", "pace_balls", "spin_runs",
                        "spin_balls", "top_inns", "mid_inns", "low_inns", "chase_runs", "chase_balls"):
                raw[key] += float(r[key] or 0)
        f["t20_bat_inns"] = int(raw["inns"])
        f["t20_bat_balls"] = int(raw["balls"])
        f["bat_evidence_balls"] = round(eq_balls, 1)
        if raw["balls"] > 0:
            f["bat_sr_eq"] = round(_shrink(eq_runs * 100, eq_balls, prior_sr, K_BAT_BALLS), 2)
            f["bat_avg_eq"] = round(_shrink(eq_runs, eq_outs, prior_avg, K_DISMISSALS), 2)
            f["bat_boundary_pct"] = round(100 * _shrink(eq_bnd, eq_balls, prior_bnd, K_BAT_BALLS), 2)
            f["bat_dot_pct"] = round(100 * _ratio(eq_dots, eq_balls), 2) if eq_balls else None
            f["bat_runs_per_inns"] = round(eq_runs / w_inns, 2) if w_inns else None
            for ph in ("pp", "mid", "death"):
                f[f"bat_{ph}_sr"] = round(_shrink(raw[f"{ph}_runs"] * 100, raw[f"{ph}_balls"], phase_prior[f"bat_{ph}"], 60), 2) \
                    if raw[f"{ph}_balls"] >= 1 and phase_prior[f"bat_{ph}"] else None
                f[f"bat_{ph}_balls"] = int(raw[f"{ph}_balls"])
            f["bat_vs_pace_sr"] = round(_shrink(raw["pace_runs"] * 100, raw["pace_balls"], prior_sr, 60), 2) if raw["pace_balls"] else None
            f["bat_vs_spin_sr"] = round(_shrink(raw["spin_runs"] * 100, raw["spin_balls"], prior_sr, 60), 2) if raw["spin_balls"] else None
            f["bat_chase_sr"] = round(_shrink(raw["chase_runs"] * 100, raw["chase_balls"], prior_sr, 60), 2) if raw["chase_balls"] else None
            n = max(raw["top_inns"] + raw["mid_inns"] + raw["low_inns"], 1)
            f["pos_top_share"] = round(raw["top_inns"] / n, 3)
            f["pos_middle_share"] = round(raw["mid_inns"] / n, 3)
            f["pos_lower_share"] = round(raw["low_inns"] / n, 3)
            f["death_balls_share"] = round(raw["death_balls"] / raw["balls"], 3)
        # --- bowling --------------------------------------------------------
        bws = bowl_by.get(pid, [])
        ipl_b = next((r for r in bws if r["comp"] == "IPL"), None)
        f["ipl_bowl_balls"] = int(ipl_b["balls"] or 0) if ipl_b else 0
        f["ipl_bowl_econ"] = _ratio(ipl_b["runs"], ipl_b["balls"], 6) if ipl_b else None
        eqb_runs = eqb_balls = eqb_wkts = eqb_dots = wb_inns = 0.0
        rawb = defaultdict(float)
        for r in bws:
            rel = factors.reliability(r["comp"])
            if rel <= 0:
                continue
            factor = factors.bowl_econ.get(r["comp"], 1.0) if r["comp"] != "IPL" else 1.0
            comps_used.add(r["comp"])
            eqb_runs += float(r["w_runs"] or 0) * factor * rel
            eqb_balls += float(r["w_balls"] or 0) * rel
            eqb_wkts += float(r["w_wkts"] or 0) * rel
            eqb_dots += float(r["w_dots"] or 0) * rel
            wb_inns += float(r["w_inns"] or 0) * rel
            for key in ("balls", "runs", "wkts", "inns", "dots", "bnd", "pp_balls", "pp_runs", "pp_wkts",
                        "mid_balls", "mid_runs", "mid_wkts", "death_balls", "death_runs", "death_wkts"):
                rawb[key] += float(r[key] or 0)
        f["t20_bowl_inns"] = int(rawb["inns"])
        f["t20_bowl_balls"] = int(rawb["balls"])
        f["bowl_evidence_balls"] = round(eqb_balls, 1)
        if rawb["balls"] > 0:
            f["bowl_econ_eq"] = round(_shrink(eqb_runs * 6, eqb_balls, prior_econ, K_BOWL_BALLS), 3)
            f["bowl_sr_eq"] = round(_shrink(eqb_balls, eqb_wkts, prior_bsr, K_DISMISSALS), 2)
            f["bowl_dot_pct"] = round(100 * _shrink(eqb_dots, eqb_balls, prior_dot, K_BOWL_BALLS), 2)
            f["bowl_boundary_pct"] = round(100 * _ratio(rawb["bnd"], rawb["balls"]), 2)
            f["bowl_wkts_per_inns"] = round(eqb_wkts / wb_inns, 3) if wb_inns else None
            f["bowl_balls_per_inns"] = round(rawb["balls"] / rawb["inns"], 2) if rawb["inns"] else None
            for ph in ("pp", "mid", "death"):
                f[f"bowl_{ph}_econ"] = round(_shrink(rawb[f"{ph}_runs"] * 6, rawb[f"{ph}_balls"], phase_prior[f"bowl_{ph}"], 60), 3) \
                    if rawb[f"{ph}_balls"] >= 1 and phase_prior[f"bowl_{ph}"] else None
                f[f"bowl_{ph}_balls"] = int(rawb[f"{ph}_balls"])
                f[f"bowl_{ph}_wkts"] = int(rawb[f"{ph}_wkts"])
            f["bowl_death_share"] = round(rawb["death_balls"] / rawb["balls"], 3)
            f["bowl_pp_share"] = round(rawb["pp_balls"] / rawb["balls"], 3)
        # --- career / recency / keeping ------------------------------------
        c = career.get(pid)
        f["ipl_matches_career"] = int(c["ipl_matches_career"] or 0) if c else 0
        f["t20_matches_career"] = int(c["t20_matches_career"] or 0) if c else 0
        f["t20_career_years"] = round((as_of - c["first_t20"]).days / 365.25, 2) if c and c["first_t20"] else None
        f["days_since_ipl"] = (as_of - c["last_ipl"]).days if c and c["last_ipl"] else None
        last = max([r["last_date"] for r in brs + bws if r.get("last_date")], default=None)
        f["days_since_t20"] = (as_of - last).days if last else None
        k = keeping.get(pid)
        f["stumpings_window"] = int(k["stumpings"] or 0) if k else 0
        f["competitions_used"] = len(comps_used)
        f["ipl_share_of_evidence"] = round((float(ipl["balls"] or 0) if ipl else 0) / max(raw["balls"], 1), 3) if raw["balls"] else None
        out[pid] = f
    return out


def get_features(db: Session, player_ids: Iterable[str], as_of: date) -> Dict[str, dict]:
    """Cached wrapper: reuse persisted snapshots for (player, as_of, version)."""
    ids = sorted({p for p in player_ids if p})
    if not ids:
        return {}
    cached = {s.player_id: s.features for s in db.scalars(select(AuctionFeatureSnapshot).where(
        AuctionFeatureSnapshot.as_of == as_of, AuctionFeatureSnapshot.feature_version == FEATURE_VERSION,
        AuctionFeatureSnapshot.player_id.in_(ids))).all()}
    missing = [p for p in ids if p not in cached]
    if missing:
        fresh = compute_features(db, missing, as_of)
        for pid in missing:
            feats = fresh.get(pid) or {"as_of": as_of.isoformat(), "feature_version": FEATURE_VERSION}
            cached[pid] = feats
            db.add(AuctionFeatureSnapshot(player_id=pid, as_of=as_of, feature_version=FEATURE_VERSION, features=feats))
        db.commit()
    return cached
