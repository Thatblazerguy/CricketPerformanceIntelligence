"""Data calibration for the ball-by-ball match simulator.

Everything the engine samples from is derived here from CPI delivery history in
PostgreSQL (``matches`` / ``match_innings`` / ``deliveries`` / ``wickets`` /
``delivery_extras`` / ``player_attributes``):

* **Format baselines** – outcome counts by gender, innings, over bucket and
  wickets already lost (and, for limited-overs chases, required-rate band),
  league-wide references by phase and bowling type, batting-position priors,
  extras/run-out run distributions and dismissal mixes.  These scan millions of
  rows, so they are computed once per format family and cached to
  ``artifacts/simulator/calibration_<family>.json`` (rebuild with
  ``scripts/train_match_simulator.py``).
* **Player profiles** – recency-weighted per-phase / per-bowling-type outcome
  counts for the selected players, queried once per request (and cached in
  process until the sync worker imports new matches).
* **Venue profile** – outcome counts at the chosen venue (historical data only)
  and the venue's toss-decision history.

No probabilities are produced here; the engine turns counts into smoothed
ratios (see ``match_simulator.build_model``).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

CALIBRATION_VERSION = "cpi-sim-calibration-v4"
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "simulator"

# Outcome classes of a single delivery. R0..R6: runs off the bat on a legal
# ball without extras; W: wicket credited to the bowler; RO: run out;
# WD/NB: wide / no-ball; B/LB: byes / leg-byes on a legal ball.
CLASSES = ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "W", "RO", "WD", "NB", "B", "LB")
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}
BAT_CLASSES = ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "W")

FAMILY_FORMATS = {"T20": ("T20", "T20I"), "ODI": ("ODI", "ODM"), "Test": ("Test", "MDM")}
FORMAT_TO_FAMILY = {"T20": "T20", "T20I": "T20", "ODI": "ODI", "ODM": "ODI", "Test": "Test", "MDM": "Test"}
# Modern-era windows keep scoring rates representative of today's game.
FAMILY_SINCE = {"T20": date(2016, 1, 1), "ODI": date(2012, 1, 1), "Test": date(2010, 1, 1)}
RRR_BANDS = {"T20": (6, 8, 10, 12, 15), "ODI": (4.5, 5.5, 6.5, 8, 10)}
DEFAULT_OVERS = {"T20": 20, "ODI": 50, "Test": None}
# Recency half-life (years) for player profiles.
HALF_LIFE_YEARS = 4.0


def phase_sql(family: str, col: str = "d.over_number") -> str:
    if family == "T20":
        return f"CASE WHEN {col} < 6 THEN 'powerplay' WHEN {col} < 15 THEN 'middle' ELSE 'death' END"
    if family == "ODI":
        return f"CASE WHEN {col} < 10 THEN 'powerplay' WHEN {col} < 40 THEN 'middle' ELSE 'death' END"
    return f"CASE WHEN {col} < 20 THEN 'new_ball' WHEN {col} < 80 THEN 'middle' ELSE 'old_ball' END"


def phase_of(family: str, over_index: int) -> str:
    if family == "T20":
        return "powerplay" if over_index < 6 else "middle" if over_index < 15 else "death"
    if family == "ODI":
        return "powerplay" if over_index < 10 else "middle" if over_index < 40 else "death"
    return "new_ball" if over_index < 20 else "middle" if over_index < 80 else "old_ball"


PHASES = {"T20": ("powerplay", "middle", "death"), "ODI": ("powerplay", "middle", "death"),
          "Test": ("new_ball", "middle", "old_ball")}


def over_bucket(family: str, over_index: int) -> int:
    if family == "T20":
        return min(over_index, 19)
    if family == "ODI":
        return min(over_index // 5, 9)
    return min(over_index // 10, 12)


def over_bucket_sql(family: str) -> str:
    if family == "T20":
        return "LEAST(d.over_number, 19)"
    if family == "ODI":
        return "LEAST(d.over_number / 5, 9)"
    return "LEAST(d.over_number / 10, 12)"


def position_band(position: int) -> str:
    """1-based batting position to a calibration band."""
    return "open" if position <= 2 else "top" if position <= 4 else "middle" if position <= 7 else "tail"


def class_sql(bw="bw", ro="ro", wides="wides", noballs="noballs", byes="byes", legbyes="legbyes", runs="batter_runs") -> str:
    return (f"CASE WHEN {bw} THEN 'W' WHEN {ro} THEN 'RO' WHEN {wides} > 0 THEN 'WD' WHEN {noballs} > 0 THEN 'NB' "
            f"WHEN {byes} > 0 THEN 'B' WHEN {legbyes} > 0 THEN 'LB' ELSE 'R' || LEAST({runs}, 6) END")


_CLASS_SQL = class_sql()
# Same classification straight off the joined delivery/extras/wickets rows.
_JOINED_CLASS_SQL = class_sql("COALESCE(w.bw, FALSE)", "COALESCE(w.ro, FALSE)", "COALESCE(x.wides, 0)", "COALESCE(x.noballs, 0)",
                              "COALESCE(x.byes, 0)", "COALESCE(x.legbyes, 0)", "d.batter_runs")

_EXTRAS_JOIN = """
LEFT JOIN (SELECT delivery_id,
    SUM(runs) FILTER (WHERE extra_type = 'wides') AS wides,
    SUM(runs) FILTER (WHERE extra_type = 'noballs') AS noballs,
    SUM(runs) FILTER (WHERE extra_type = 'byes') AS byes,
    SUM(runs) FILTER (WHERE extra_type = 'legbyes') AS legbyes
  FROM delivery_extras {where} GROUP BY delivery_id) x ON x.delivery_id = d.id"""
_WICKETS_JOIN = """
LEFT JOIN (SELECT delivery_id, BOOL_OR(is_bowler_wicket) AS bw, BOOL_OR(dismissal_type = 'run out') AS ro,
    SUM(CASE WHEN is_batter_dismissed AND dismissal_type NOT IN ('retired hurt', 'retired not out') THEN 1 ELSE 0 END) AS nout,
    MAX(player_out_id) AS out_id
  FROM wickets {where} GROUP BY delivery_id) w ON w.delivery_id = d.id"""
_BOWL_TYPE_JOIN = """
LEFT JOIN (SELECT player_id, MIN(attribute_value) AS btype FROM player_attributes
  WHERE attribute_type IN ('bowling_type', 'bowling_category') GROUP BY player_id) bt ON bt.player_id = d.bowler_id"""


def _btype_sql() -> str:
    return "CASE WHEN LOWER(bt.btype) LIKE 'pace%' THEN 'pace' WHEN LOWER(bt.btype) LIKE 'spin%' THEN 'spin' ELSE 'unknown' END"


def _vec() -> List[float]:
    return [0.0] * len(CLASSES)


# ---------------------------------------------------------------------------
# Format baselines (heavy, cached on disk)
# ---------------------------------------------------------------------------

# Bowler workload bands: priors for bowlers with little individual data come from
# bowlers of similar career volume, so a part-timer is shrunk toward how part-timers
# actually bowl rather than toward the league-average (frontline-dominated) bowler.
BOWLER_BANDS = ((0, "part_time"), (300, "occasional"), (1200, "regular"), (3000, "frontline"))


def bowler_band(balls: float) -> str:
    label = BOWLER_BANDS[0][1]
    for lo, name in BOWLER_BANDS:
        if balls >= lo:
            label = name
    return label


def _bowler_volume_bands(db, family, formats, since, until) -> Dict[str, dict]:
    from sqlalchemy import bindparam
    band_sql = " ".join(f"WHEN v.n >= {lo} THEN '{name}'" for lo, name in reversed(BOWLER_BANDS))
    sql = f"""
WITH scope AS (
  SELECT d.id, d.bowler_id, d.batter_runs, m.gender, {phase_sql(family)} AS phase FROM deliveries d
  JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
  WHERE m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND NOT mi.is_super_over
), vol AS (SELECT bowler_id, gender, COUNT(*) AS n FROM scope GROUP BY 1, 2)
SELECT s.gender, s.phase, CASE {band_sql} END AS band,
  {class_sql("COALESCE(w.bw, FALSE)", "COALESCE(w.ro, FALSE)", "COALESCE(x.wides, 0)", "COALESCE(x.noballs, 0)", "COALESCE(x.byes, 0)", "COALESCE(x.legbyes, 0)", "s.batter_runs")} AS cls,
  COUNT(*) AS n, COUNT(DISTINCT s.bowler_id) AS bowlers
FROM scope s JOIN vol v ON v.bowler_id = s.bowler_id AND v.gender = s.gender
{_EXTRAS_JOIN.format(where='').replace('d.id', 's.id')} {_WICKETS_JOIN.format(where='').replace('d.id', 's.id')}
GROUP BY 1, 2, 3, 4"""
    out: Dict[str, dict] = defaultdict(lambda: defaultdict(_vec))
    meta: Dict[str, dict] = defaultdict(dict)
    rows = db.execute(text(sql).bindparams(bindparam("formats", expanding=True)),
                      {"formats": list(formats), "since": since, "until": until}).mappings()
    for r in rows:
        if r["cls"] in CLASS_INDEX:
            out[r["gender"]][f"{r['band']}|{r['phase']}"][CLASS_INDEX[r["cls"]]] += float(r["n"])
            meta[r["gender"]][r["band"]] = max(meta[r["gender"]].get(r["band"], 0), int(r["bowlers"]))
    # keys are "band|phase" so the engine can compare each band with the same phase's league rates
    return {g: {key: {"counts": counts, "bowlers": meta[g].get(key.split("|")[0], 0)} for key, counts in bands.items()} for g, bands in out.items()}


# Shared match conditions. Runs in the two innings of a match are correlated (pitch,
# weather, ground on the day). This measures that correlation over the first
# ``CONDITION_OVERS`` of each innings (before chases end) and how outcome classes
# shift with the *other* innings' scoring rate. The engine turns this into a latent
# match-level factor (see ``match_simulator.fit_condition_scale``).
CONDITION_OVERS = {"T20": 10, "ODI": 25, "Test": 30}


def _match_conditions(db, family, formats, since, until) -> Dict[str, dict]:
    import math
    from sqlalchemy import bindparam
    k = CONDITION_OVERS[family]
    sql = f"""
SELECT m.gender, m.id AS match_id, mi.innings_number AS inn,
  {class_sql("COALESCE(w.bw, FALSE)", "COALESCE(w.ro, FALSE)", "COALESCE(x.wides, 0)", "COALESCE(x.noballs, 0)", "COALESCE(x.byes, 0)", "COALESCE(x.legbyes, 0)", "d.batter_runs")} AS cls,
  COUNT(*) AS n, SUM(d.total_runs) AS runs, SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS legal
FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
{_EXTRAS_JOIN.format(where='')} {_WICKETS_JOIN.format(where='')}
WHERE m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND NOT mi.is_super_over
  AND mi.innings_number <= 2 AND d.over_number < {k}
  AND NOT EXISTS (SELECT 1 FROM match_innings t WHERE t.match_id = m.id AND t.target_overs IS NOT NULL AND t.target_overs < {k * 2})
GROUP BY 1, 2, 3, 4"""
    per: Dict[tuple, dict] = {}
    for r in db.execute(text(sql).bindparams(bindparam("formats", expanding=True)),
                        {"formats": list(formats), "since": since, "until": until}).mappings():
        key = (r["gender"], r["match_id"], int(r["inn"]))
        e = per.setdefault(key, {"vec": _vec(), "runs": 0, "legal": 0})
        if r["cls"] in CLASS_INDEX:
            e["vec"][CLASS_INDEX[r["cls"]]] += float(r["n"])
        e["runs"] += int(r["runs"] or 0)
        e["legal"] += int(r["legal"] or 0)
    result: Dict[str, dict] = {}
    for gender in {g for g, _, _ in per}:
        pairs = []
        for (g, mid, inn), e in per.items():
            if g != gender or inn != 1:
                continue
            other = per.get((g, mid, 2))
            # Only innings that lasted the full window, so rates are comparable.
            if other and e["legal"] >= k * 6 and other["legal"] >= k * 6:
                pairs.append((e, other))
        if len(pairs) < 200:
            continue
        x1 = [math.log(max(1, a["runs"]) / a["legal"]) for a, _ in pairs]
        x2 = [math.log(max(1, b["runs"]) / b["legal"]) for _, b in pairs]
        n = len(pairs)
        m1, m2 = sum(x1) / n, sum(x2) / n
        v1 = sum((x - m1) ** 2 for x in x1) / n
        v2 = sum((x - m2) ** 2 for x in x2) / n
        rho = sum((a - m1) * (b - m2) for a, b in zip(x1, x2)) / n / math.sqrt(v1 * v2)
        # Class shifts vs the *other* innings' standardised log run rate (quintiles; no self-selection).
        rows = [((x1[i] - m1) / math.sqrt(v1), pairs[i][1]["vec"]) for i in range(n)]
        rows += [((x2[i] - m2) / math.sqrt(v2), pairs[i][0]["vec"]) for i in range(n)]
        rows.sort(key=lambda t: t[0])
        q = 5
        groups = [rows[i * len(rows) // q:(i + 1) * len(rows) // q] for i in range(q)]
        zs, dists = [], []
        for grp in groups:
            vec = _vec()
            for _, v in grp:
                for i, c in enumerate(v):
                    vec[i] += c
            tot = sum(vec) or 1.0
            zs.append(sum(z for z, _ in grp) / len(grp))
            dists.append([c / tot for c in vec])
        zbar = sum(zs) / q
        vz = sum((z - zbar) ** 2 for z in zs)
        beta = []
        for ci in range(len(CLASSES)):
            ys = [math.log(d[ci]) if d[ci] > 0 else None for d in dists]
            if any(y is None for y in ys):
                beta.append(0.0)
                continue
            ybar = sum(ys) / q
            beta.append(sum((z - zbar) * (y - ybar) for z, y in zip(zs, ys)) / vz)
        result[gender] = {"rho": round(rho, 4), "pairs": n, "beta": [round(b, 4) for b in beta], "overs": k,
                          "sd_log_rr": [round(math.sqrt(v1), 4), round(math.sqrt(v2), 4)]}
    return result


def build_format_calibration(db, family: str, until: Optional[date] = None) -> dict:
    """Scan the family's modern-era deliveries once and aggregate outcome counts."""
    started = time.time()
    until = until or date(2100, 1, 1)
    formats = FAMILY_FORMATS[family]
    since = FAMILY_SINCE[family]
    default_overs = DEFAULT_OVERS[family] or 0
    bands = RRR_BANDS.get(family)
    rrb_sql = "-1"
    if bands:
        rrb_sql = ("CASE WHEN inn = 2 AND target_runs IS NOT NULL THEN width_bucket(((target_runs - sc_before) * 6.0 / "
                   f"GREATEST(1, COALESCE(tovers, {default_overs}) * 6 - lb_before))::numeric, ARRAY[{','.join(str(b) for b in bands)}]::numeric[]) ELSE -1 END")
    max_inn = 4 if family == "Test" else 2
    sql = f"""
WITH base AS (
  SELECT m.gender, mi.innings_number AS inn, mi.target_runs, mi.target_overs AS tovers, d.innings_id,
    d.over_number, d.delivery_sequence, d.batter_id, d.batter_runs, d.total_runs, d.is_legal_ball,
    {over_bucket_sql(family)} AS ob, {phase_sql(family)} AS phase, {_btype_sql()} AS btype,
    COALESCE(x.wides, 0) AS wides, COALESCE(x.noballs, 0) AS noballs, COALESCE(x.byes, 0) AS byes, COALESCE(x.legbyes, 0) AS legbyes,
    COALESCE(w.bw, FALSE) AS bw, COALESCE(w.ro, FALSE) AS ro, COALESCE(w.nout, 0) AS nout,
    (w.out_id = d.batter_id) AS striker_out, EXTRACT(YEAR FROM m.start_date)::int AS yr
  FROM deliveries d
  JOIN match_innings mi ON mi.id = d.innings_id
  JOIN matches m ON m.id = mi.match_id
  {_EXTRAS_JOIN.format(where='')}
  {_WICKETS_JOIN.format(where='')}
  {_BOWL_TYPE_JOIN}
  WHERE m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND NOT mi.is_super_over AND mi.innings_number <= {max_inn}
), win AS (
  SELECT *,
    COALESCE(SUM(nout) OVER p, 0) - nout AS wk_before,
    COALESCE(SUM(total_runs) OVER p, 0) - total_runs AS sc_before,
    COALESCE(SUM(CASE WHEN is_legal_ball THEN 1 ELSE 0 END) OVER p, 0) - CASE WHEN is_legal_ball THEN 1 ELSE 0 END AS lb_before,
    MIN(over_number * 1000 + delivery_sequence) OVER (PARTITION BY innings_id, batter_id) AS first_faced
  FROM base WINDOW p AS (PARTITION BY innings_id ORDER BY over_number, delivery_sequence ROWS UNBOUNDED PRECEDING)
), ranked AS (
  SELECT gender, inn, ob, phase, btype, yr, {_CLASS_SQL} AS cls, striker_out,
    LEAST(wk_before, 9) AS wk, {rrb_sql} AS rrb,
    CASE WHEN bat_pos <= 2 THEN 'open' WHEN bat_pos <= 4 THEN 'top' WHEN bat_pos <= 7 THEN 'middle' ELSE 'tail' END AS posband,
    CASE WHEN wides > 0 THEN wides WHEN noballs > 0 THEN batter_runs WHEN byes > 0 THEN byes
         WHEN legbyes > 0 THEN legbyes WHEN ro THEN batter_runs ELSE 0 END AS detail_runs
  FROM (SELECT *, DENSE_RANK() OVER (PARTITION BY innings_id ORDER BY first_faced) AS bat_pos FROM win) wr
)
SELECT gender, GROUPING(inn, btype, posband, detail_runs, yr) AS gid,
  inn, ob, wk, rrb, phase, btype, posband, yr, cls, detail_runs, striker_out, COUNT(*) AS n
FROM ranked
GROUP BY GROUPING SETS (
  (gender, inn, ob, wk, rrb, phase, cls),
  (gender, phase, btype, cls),
  (gender, phase, posband, cls),
  (gender, cls, detail_runs, striker_out),
  (gender, yr, phase, btype, cls)
)
"""
    from sqlalchemy import bindparam
    stmt = text(sql).bindparams(bindparam("formats", expanding=True))
    rows = db.execute(stmt, {"formats": list(formats), "since": since, "until": until}).mappings().all()

    out: Dict[str, dict] = {}

    def g(gender):
        return out.setdefault(gender, {
            "base": defaultdict(_vec), "pressure": defaultdict(_vec), "ref": defaultdict(_vec), "ref_year": defaultdict(_vec),
            "position": defaultdict(_vec), "details": defaultdict(lambda: defaultdict(float)),
            "runout_striker": [0.0, 0.0], "innings_totals": {},
        })

    for r in rows:
        cls = r["cls"]
        if cls not in CLASS_INDEX:
            continue
        ci, n, gd, gid = CLASS_INDEX[cls], float(r["n"]), g(r["gender"]), int(r["gid"])
        if gid == 0b01111:
            gd["base"][f"{r['inn']}|{r['ob']}|{r['wk']}"][ci] += n
            if r["rrb"] is not None and r["rrb"] >= 0:
                gd["pressure"][f"{r['phase']}|{r['rrb']}"][ci] += n
                gd["pressure"][f"{r['phase']}|all"][ci] += n
        elif gid == 0b10111:
            gd["ref"][f"{r['phase']}|{r['btype']}"][ci] += n
            gd["ref"][f"{r['phase']}|*"][ci] += n
        elif gid == 0b11011:
            gd["position"][f"{r['phase']}|{r['posband']}"][ci] += n
        elif gid == 0b10110:
            gd["ref_year"][f"{r['yr']}|{r['phase']}|{r['btype']}"][ci] += n
            gd["ref_year"][f"{r['yr']}|{r['phase']}|*"][ci] += n
        elif gid == 0b11101:
            gd["details"][cls][str(int(r["detail_runs"]))] += n
            if cls == "RO" and r["striker_out"] is not None:
                gd["runout_striker"][0 if r["striker_out"] else 1] += n

    # Dismissal mix by bowling type (bowler-credited wickets) and innings totals.
    mix_sql = f"""
SELECT m.gender, {_btype_sql()} AS btype, w.dismissal_type, COUNT(*) AS n
FROM wickets w JOIN deliveries d ON d.id = w.delivery_id JOIN match_innings mi ON mi.id = d.innings_id
JOIN matches m ON m.id = mi.match_id {_BOWL_TYPE_JOIN}
WHERE m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND w.is_bowler_wicket
GROUP BY 1, 2, 3"""
    mix_stmt = text(mix_sql).bindparams(bindparam("formats", expanding=True))
    mixes: Dict[str, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in db.execute(mix_stmt, {"formats": list(formats), "since": since, "until": until}).mappings():
        mixes[r["gender"]][r["btype"]][r["dismissal_type"]] += float(r["n"])
        mixes[r["gender"]]["*"][r["dismissal_type"]] += float(r["n"])

    totals_sql = f"""
SELECT m.gender, mi.innings_number AS inn, COUNT(*) AS innings, AVG(t.runs) AS avg_runs, AVG(t.wkts) AS avg_wkts
FROM (SELECT d.innings_id, SUM(d.total_runs) AS runs, SUM(COALESCE(w.nout, 0)) AS wkts
      FROM deliveries d JOIN match_innings mi0 ON mi0.id = d.innings_id JOIN matches m0 ON m0.id = mi0.match_id
      {_WICKETS_JOIN.format(where='')}
      WHERE m0.match_format IN :formats AND m0.start_date >= :since AND m0.start_date < :until GROUP BY d.innings_id) t
JOIN match_innings mi ON mi.id = t.innings_id JOIN matches m ON m.id = mi.match_id
WHERE NOT mi.is_super_over AND mi.innings_number <= 2 AND COALESCE(m.result_type, '') <> 'no result'
GROUP BY 1, 2"""
    totals_stmt = text(totals_sql).bindparams(bindparam("formats", expanding=True))
    for r in db.execute(totals_stmt, {"formats": list(formats), "since": since, "until": until}).mappings():
        g(r["gender"])["innings_totals"][str(r["inn"])] = {
            "innings": int(r["innings"]), "avg_runs": round(float(r["avg_runs"] or 0), 1), "avg_wickets": round(float(r["avg_wkts"] or 0), 2)}

    toss_sql = """SELECT m.gender, m.toss_decision, COUNT(*) AS n FROM matches m
WHERE m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND m.toss_decision IS NOT NULL GROUP BY 1, 2"""
    toss_stmt = text(toss_sql).bindparams(bindparam("formats", expanding=True))
    toss: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in db.execute(toss_stmt, {"formats": list(formats), "since": since, "until": until}).mappings():
        toss[r["gender"]][r["toss_decision"]] = float(r["n"])

    bowler_bands = _bowler_volume_bands(db, family, formats, since, until)
    conditions = _match_conditions(db, family, formats, since, until)

    def plain(d):
        if isinstance(d, dict):
            return {k: plain(v) for k, v in d.items()}
        return d

    genders = {}
    for gender, gd in out.items():
        genders[gender] = {
            "base": dict(gd["base"]), "pressure": dict(gd["pressure"]), "ref": dict(gd["ref"]), "ref_year": dict(gd["ref_year"]),
            "position": dict(gd["position"]), "details": plain(gd["details"]),
            "runout_striker": gd["runout_striker"], "dismissal_mix": plain(mixes.get(gender, {})),
            "innings_totals": gd["innings_totals"], "toss": toss.get(gender, {}),
            "bowler_bands": bowler_bands.get(gender, {}), "conditions": conditions.get(gender),
            "deliveries": int(sum(sum(v) for k, v in gd["ref"].items() if k.endswith("|*"))),
        }
    calibration = {"version": CALIBRATION_VERSION, "genders": genders}
    from app.ml.match_simulator import fit_condition_scale  # lazy: the engine imports this module
    for gender, block in genders.items():
        if block.get("conditions"):
            fit = fit_condition_scale(calibration, family, gender)
            if fit:
                block["conditions"]["scale"] = fit["scale"]
                block["conditions"]["fit_curve"] = fit["fit_curve"]
    return {
        "version": CALIBRATION_VERSION, "family": family, "formats": list(formats), "since": str(since),
        "until": str(until) if until.year < 2100 else None,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "build_seconds": round(time.time() - started, 1),
        "classes": list(CLASSES), "genders": genders,
    }


_CAL_CACHE: Dict[str, dict] = {}
_CAL_LOCK = threading.Lock()


def calibration_path(family: str, until: Optional[date] = None) -> Path:
    if until:
        return ARTIFACT_DIR / "backtest" / f"calibration_{family.lower()}_until_{until.isoformat()}.json"
    return ARTIFACT_DIR / f"calibration_{family.lower()}.json"


def load_format_calibration(db, family: str, *, build_if_missing: bool = True, until: Optional[date] = None) -> Optional[dict]:
    """Return the cached family calibration, building and persisting it on first use.

    ``until`` builds a separate calibration from matches strictly before that date
    (chronological backtests); the default uses all history.
    """
    key = f"{family}@{until}" if until else family
    with _CAL_LOCK:
        if key in _CAL_CACHE:
            return _CAL_CACHE[key]
        path = calibration_path(family, until)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if data.get("version") == CALIBRATION_VERSION:
                    _CAL_CACHE[key] = data
                    return data
            except (OSError, json.JSONDecodeError):
                logger.warning("Ignoring unreadable simulator calibration %s", path)
        if not build_if_missing:
            return None
        logger.info("Building %s simulator calibration from CPI deliveries (first use)", family)
        data = build_format_calibration(db, family, until=until)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        tmp.replace(path)
        _CAL_CACHE[key] = data
        return data


def calibration_available(family: str) -> bool:
    if family in _CAL_CACHE:
        return True
    path = calibration_path(family)
    if not path.exists():
        return False
    try:  # an outdated version will be rebuilt on first use
        with path.open() as fh:
            return f'"version":"{CALIBRATION_VERSION}"' in fh.read(200)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Player and venue profiles (light, per request)
# ---------------------------------------------------------------------------

_PROFILE_CACHE: Dict[tuple, dict] = {}
_PROFILE_LOCK = threading.Lock()


def clear_profile_cache() -> None:
    with _PROFILE_LOCK:
        _PROFILE_CACHE.clear()


def _recency_sql() -> str:
    return f"POWER(0.5, GREATEST(0, (CAST(:asof AS date) - m.start_date)) / (365.25 * {HALF_LIFE_YEARS}))"


def load_player_profiles(db, family: str, gender: str, player_ids: Iterable[str], until: Optional[date] = None) -> Dict[str, dict]:
    """Recency-weighted batting/bowling outcome counts for each player (cached per player).

    ``until`` restricts history to matches before that date (chronological backtests)."""
    ids = sorted({p for p in player_ids if p})
    result: Dict[str, dict] = {}
    missing = []
    with _PROFILE_LOCK:
        for pid in ids:
            hit = _PROFILE_CACHE.get((family, gender, pid, until))
            if hit is not None:
                result[pid] = hit
            else:
                missing.append(pid)
    if not missing:
        return result
    from sqlalchemy import bindparam
    formats = list(FAMILY_FORMATS[family])
    since = FAMILY_SINCE[family]
    params = {"formats": formats, "since": since, "ids": missing, "gender": gender,
              "until": until or date(2100, 1, 1), "asof": until or date.today()}
    fresh = {pid: {"bat": defaultdict(_vec), "bowl": defaultdict(_vec), "bat_balls": 0, "bowl_balls": 0,
                   "bowl_phase_balls": defaultdict(float), "dismissals": defaultdict(float), "matches": 0,
                   "bat_innings": 0, "bat_runs": 0, "bat_outs": 0, "bowl_runs": 0, "bowl_wkts": 0} for pid in missing}
    common = f"""FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
  {_EXTRAS_JOIN.format(where='')} {_WICKETS_JOIN.format(where='')}"""
    bat_sql = f"""
SELECT d.batter_id AS pid, {phase_sql(family)} AS phase, {_btype_sql()} AS btype, EXTRACT(YEAR FROM m.start_date)::int AS yr,
  {_JOINED_CLASS_SQL} AS cls,
  SUM({_recency_sql()}) AS wn, COUNT(*) AS n, COUNT(DISTINCT mi.id) AS inns
{common} {_BOWL_TYPE_JOIN}
WHERE d.batter_id IN :ids AND m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND m.gender = :gender AND NOT mi.is_super_over
GROUP BY 1, 2, 3, 4, 5"""
    bowl_sql = f"""
SELECT d.bowler_id AS pid, {phase_sql(family)} AS phase, EXTRACT(YEAR FROM m.start_date)::int AS yr,
  {_JOINED_CLASS_SQL} AS cls,
  SUM({_recency_sql()}) AS wn, COUNT(*) AS n, SUM(d.bowling_runs) AS runs
{common}
WHERE d.bowler_id IN :ids AND m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND m.gender = :gender AND NOT mi.is_super_over
GROUP BY 1, 2, 3, 4"""
    mix_sql = """
SELECT d.bowler_id AS pid, w.dismissal_type, COUNT(*) AS n
FROM wickets w JOIN deliveries d ON d.id = w.delivery_id JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
WHERE d.bowler_id IN :ids AND w.is_bowler_wicket AND m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND m.gender = :gender
GROUP BY 1, 2"""
    out_sql = """
SELECT w.player_out_id AS pid, COUNT(*) AS n FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
WHERE w.player_out_id IN :ids AND w.is_batter_dismissed AND w.dismissal_type NOT IN ('retired hurt', 'retired not out')
  AND m.match_format IN :formats AND m.start_date >= :since AND m.start_date < :until AND m.gender = :gender GROUP BY 1"""
    exp = lambda s: text(s).bindparams(bindparam("ids", expanding=True), bindparam("formats", expanding=True))
    for r in db.execute(exp(bat_sql), params).mappings():
        p = fresh[r["pid"]]
        if r["cls"] not in CLASS_INDEX:
            continue
        ci = CLASS_INDEX[r["cls"]]
        p["bat"][f"{r['phase']}|{r['btype']}|{r['yr']}"][ci] += float(r["wn"])
        if r["cls"] in BAT_CLASSES:
            p["bat_balls"] += int(r["n"])
            p["bat_runs"] += int(r["n"]) * int(r["cls"][1]) if r["cls"] != "W" else 0
        p["bat_innings"] = max(p["bat_innings"], int(r["inns"]))
    for r in db.execute(exp(bowl_sql), params).mappings():
        p = fresh[r["pid"]]
        if r["cls"] not in CLASS_INDEX:
            continue
        p["bowl"][f"{r['phase']}|{r['yr']}"][CLASS_INDEX[r["cls"]]] += float(r["wn"])
        p["bowl_balls"] += int(r["n"])
        p["bowl_phase_balls"][r["phase"]] += float(r["n"])
        p["bowl_runs"] += int(r["runs"] or 0)
        if r["cls"] == "W":
            p["bowl_wkts"] += int(r["n"])
    for r in db.execute(exp(mix_sql), params).mappings():
        fresh[r["pid"]]["dismissals"][r["dismissal_type"]] += float(r["n"])
    for r in db.execute(exp(out_sql), params).mappings():
        fresh[r["pid"]]["bat_outs"] += int(r["n"])
    with _PROFILE_LOCK:
        for pid, p in fresh.items():
            frozen = {
                "bat": dict(p["bat"]), "bowl": dict(p["bowl"]), "bat_balls": p["bat_balls"], "bowl_balls": p["bowl_balls"],
                "bowl_phase_balls": dict(p["bowl_phase_balls"]), "dismissals": dict(p["dismissals"]),
                "bat_runs": p["bat_runs"], "bat_outs": p["bat_outs"], "bowl_runs": p["bowl_runs"], "bowl_wkts": p["bowl_wkts"],
            }
            _PROFILE_CACHE[(family, gender, pid, until)] = frozen
            result[pid] = frozen
    return result


def load_player_meta(db, player_ids: Iterable[str]) -> Dict[str, dict]:
    """Names and style attributes (bowling type/style, batting hand) for the players."""
    ids = sorted({p for p in player_ids if p})
    if not ids:
        return {}
    from sqlalchemy import bindparam
    rows = db.execute(text("SELECT id, canonical_name FROM players WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": ids}).all()
    meta = {pid: {"id": pid, "name": name} for pid, name in rows}
    attrs = db.execute(text("""SELECT player_id, attribute_type, attribute_value FROM player_attributes
        WHERE player_id IN :ids AND attribute_type IN ('bowling_type', 'bowling_category', 'bowling_style', 'batting_style', 'batting_hand', 'primary_role')""")
        .bindparams(bindparam("ids", expanding=True)), {"ids": ids}).all()
    for pid, kind, value in attrs:
        m = meta.setdefault(pid, {"id": pid, "name": pid})
        if kind in ("bowling_type", "bowling_category"):
            v = (value or "").lower()
            m.setdefault("bowling_type", "pace" if v.startswith("pace") else "spin" if v.startswith("spin") else None)
        elif kind in ("batting_style", "batting_hand"):
            m.setdefault("batting_hand", "left" if "left" in (value or "").lower() else "right" if "right" in (value or "").lower() else None)
        else:
            m.setdefault(kind, value)
    return meta


def infer_gender(db, player_ids: Iterable[str]) -> str:
    """Majority gender of the players' matches (Cricsheet records gender per match)."""
    ids = sorted({p for p in player_ids if p})
    if not ids:
        return "male"
    from sqlalchemy import bindparam
    rows = db.execute(text("""SELECT m.gender, COUNT(DISTINCT m.id) FROM player_match_appearances a JOIN matches m ON m.id = a.match_id
        WHERE a.player_id IN :ids GROUP BY 1""").bindparams(bindparam("ids", expanding=True)), {"ids": ids}).all() if _has_table(db, "player_match_appearances") else []
    if not rows:
        rows = db.execute(text("""SELECT m.gender, COUNT(*) FROM (SELECT DISTINCT innings_id FROM deliveries WHERE batter_id IN :ids OR bowler_id IN :ids LIMIT 5000) d
            JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id GROUP BY 1""").bindparams(bindparam("ids", expanding=True)), {"ids": ids}).all()
    return max(rows, key=lambda r: r[1])[0] if rows else "male"


def _has_table(db, name: str) -> bool:
    return bool(db.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{name}"}).scalar())


def load_venue_profile(db, family: str, gender: str, venue_id: Optional[str], until: Optional[date] = None) -> Optional[dict]:
    """Outcome counts and toss decisions at a venue (historical data only)."""
    if not venue_id:
        return None
    from sqlalchemy import bindparam
    key = ("venue", family, gender, venue_id, until)
    with _PROFILE_LOCK:
        if key in _PROFILE_CACHE:
            return _PROFILE_CACHE[key]
    formats = list(FAMILY_FORMATS[family])
    params = {"formats": formats, "since": FAMILY_SINCE[family], "venue": venue_id, "gender": gender, "until": until or date(2100, 1, 1)}
    sql = f"""
SELECT {_JOINED_CLASS_SQL} AS cls,
  {_btype_sql()} AS btype, COUNT(*) AS n
FROM matches m JOIN match_innings mi ON mi.match_id = m.id JOIN deliveries d ON d.innings_id = mi.id
  {_EXTRAS_JOIN.format(where='')} {_WICKETS_JOIN.format(where='')} {_BOWL_TYPE_JOIN}
WHERE m.venue_id = :venue AND m.match_format IN :formats AND m.gender = :gender AND m.start_date >= :since AND m.start_date < :until AND NOT mi.is_super_over
GROUP BY 1, 2"""
    counts = defaultdict(_vec)
    for r in db.execute(text(sql).bindparams(bindparam("formats", expanding=True)), params).mappings():
        if r["cls"] in CLASS_INDEX:
            counts[r["btype"]][CLASS_INDEX[r["cls"]]] += float(r["n"])
            counts["*"][CLASS_INDEX[r["cls"]]] += float(r["n"])
    meta = db.execute(text("""SELECT COUNT(*) AS matches,
          COUNT(*) FILTER (WHERE toss_decision = 'bat') AS bat, COUNT(*) FILTER (WHERE toss_decision = 'field') AS field,
          COUNT(*) FILTER (WHERE winner_id IS NOT NULL AND toss_winner_id IS NOT NULL AND winner_id = toss_winner_id) AS toss_won_match
        FROM matches m WHERE m.venue_id = :venue AND m.match_format IN :formats AND m.gender = :gender AND m.start_date < :until""")
        .bindparams(bindparam("formats", expanding=True)), params).mappings().first()
    name = db.execute(text("SELECT canonical_name, city, country FROM venues WHERE id = :v"), {"v": venue_id}).mappings().first()
    profile = {"venue_id": venue_id, "name": name["canonical_name"] if name else None,
               "city": name["city"] if name else None, "country": name["country"] if name else None,
               "counts": dict(counts), "matches": int(meta["matches"] or 0) if meta else 0,
               "toss": {"bat": int(meta["bat"] or 0), "field": int(meta["field"] or 0)} if meta else {},
               "deliveries": int(sum(counts["*"])) if "*" in counts else 0}
    with _PROFILE_LOCK:
        _PROFILE_CACHE[key] = profile
    return profile


def venues_for_family(db, family: str) -> List[dict]:
    from sqlalchemy import bindparam
    rows = db.execute(text("""SELECT v.id, v.canonical_name, v.city, v.country, COUNT(*) AS matches
        FROM matches m JOIN venues v ON v.id = m.venue_id WHERE m.match_format IN :formats
        GROUP BY 1, 2, 3, 4 HAVING COUNT(*) >= 1 ORDER BY COUNT(*) DESC, v.canonical_name""")
        .bindparams(bindparam("formats", expanding=True)), {"formats": list(FAMILY_FORMATS[family])}).mappings().all()
    return [dict(r) for r in rows]
