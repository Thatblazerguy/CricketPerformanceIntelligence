"""Backtest the match simulator against real CPI matches (read-only).

For a sample of recent matches it rebuilds both XIs (batting order from first
appearance, bowlers from the opposing innings), simulates each match with the
real team batting first, and compares simulated first-innings totals, wickets
and win probabilities with what actually happened.

Run from backend/:
    .venv/bin/python scripts/backtest_match_simulator.py --family T20 --matches 120 --sims 60 --exponents 1.0,0.8,0.6

Note: player profiles include the sampled matches themselves, so this measures
calibration bias (systematic over/under-scoring), not out-of-sample skill.
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import bindparam, text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.ml import match_simulator as ms  # noqa: E402
from app.ml import sim_calibration as cal  # noqa: E402


def sample_matches(db, family, gender, since, limit):
    rows = db.execute(text("""
        SELECT m.id, m.winner_id, m.team1_id, m.team2_id, m.venue_id FROM matches m
        WHERE m.match_format IN :formats AND m.gender = :gender AND m.start_date >= :since
          AND m.result_type = 'win'
          AND (SELECT COUNT(*) FROM match_innings mi WHERE mi.match_id = m.id AND NOT mi.is_super_over) = 2
          AND NOT EXISTS (SELECT 1 FROM match_innings mi WHERE mi.match_id = m.id AND mi.target_overs IS NOT NULL AND mi.target_overs < :overs)
        ORDER BY md5(m.id) LIMIT :limit""").bindparams(bindparam("formats", expanding=True)),
        {"formats": list(cal.FAMILY_FORMATS[family]), "gender": gender, "since": since, "limit": limit,
         "overs": cal.DEFAULT_OVERS[family]}).mappings().all()
    return rows


def match_teams(db, match_id):
    rows = db.execute(text("""
        SELECT mi.innings_number, mi.batting_team_id, d.batter_id, d.non_striker_id, d.bowler_id, d.total_runs,
               (SELECT COUNT(*) FROM wickets w WHERE w.delivery_id = d.id AND w.is_batter_dismissed
                  AND w.dismissal_type NOT IN ('retired hurt', 'retired not out')) AS outs
        FROM match_innings mi JOIN deliveries d ON d.innings_id = mi.id
        WHERE mi.match_id = :m AND NOT mi.is_super_over ORDER BY mi.innings_number, d.over_number, d.delivery_sequence"""),
        {"m": match_id}).all()
    order = {1: [], 2: []}
    bowlers = {1: [], 2: []}
    team = {}
    totals = {1: [0, 0], 2: [0, 0]}
    for inn, bat_team, b, ns, bw, runs, outs in rows:
        team[inn] = bat_team
        for p in (b, ns):
            if p and p not in order[inn]:
                order[inn].append(p)
        if bw and bw not in bowlers[inn]:
            bowlers[inn].append(bw)
        totals[inn][0] += runs
        totals[inn][1] += outs
    first = order[1] + [p for p in bowlers[2] if p not in order[1]]
    second = order[2] + [p for p in bowlers[1] if p not in order[2]]
    return team, first, second, totals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="T20")
    ap.add_argument("--gender", default="male")
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--matches", type=int, default=100)
    ap.add_argument("--sims", type=int, default=60)
    ap.add_argument("--exponents", default="1.0,0.8,0.6")
    ap.add_argument("--no-pressure", action="store_true", help="disable the chase-pressure tilt (diagnostic)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        calibration = cal.load_format_calibration(db, args.family)
        rules = ms.rules_for({"T20": "T20", "ODI": "ODI", "Test": "Test"}[args.family])
        matches = sample_matches(db, args.family, args.gender, args.since, args.matches)
        cases = []
        for m in matches:
            team, first, second, totals = match_teams(db, m["id"])
            if len(first) < 6 or len(second) < 6:
                continue
            cases.append((m, team, first, second, totals))
        ids = {p for c in cases for p in c[2] + c[3]}
        profiles = cal.load_player_profiles(db, args.family, args.gender, ids)
        meta = cal.load_player_meta(db, ids)
        venues = {c[0]["venue_id"]: cal.load_venue_profile(db, args.family, args.gender, c[0]["venue_id"]) for c in cases}
        print(f"{len(cases)} matches; actual mean first innings {statistics.mean(c[4][1][0] for c in cases):.1f}, "
              f"second {statistics.mean(c[4][2][0] for c in cases):.1f}")
        for exponent in [float(x) for x in args.exponents.split(",")]:
            sim1, act1, simw, actw, brier, sim2 = [], [], [], [], [], []
            for m, team, first, second, totals in cases:
                positions = {p: i + 1 for i, p in enumerate(first)}
                positions.update({p: i + 1 for i, p in enumerate(second)})
                model = ms.SimModel(calibration, args.family, args.gender, profiles, meta, venue=venues.get(m["venue_id"]),
                                    positions=positions, player_exponent=exponent)
                if args.no_pressure:
                    model.pressure = {}
                teams = {"A": ms.TeamSetup("A", "first", first), "B": ms.TeamSetup("B", "second", second)}
                out = ms.run_batch(model, rules, teams, 11, 0, args.sims, "A", "bat")
                s1 = statistics.mean(o["innings"][0][1] for o in out)
                sim1.append(s1)
                sim2.append(statistics.mean(o["innings"][1][1] for o in out))
                act1.append(totals[1][0])
                simw.append(statistics.mean(o["innings"][0][2] for o in out))
                actw.append(totals[1][1])
                p_first = sum(1 for o in out if o["winner"] == "A") / len(out)
                first_won = 1.0 if m["winner_id"] == team[1] else 0.0
                brier.append((p_first - first_won) ** 2)
            n = len(sim1)
            bias = statistics.mean(s - a for s, a in zip(sim1, act1))
            mae = statistics.mean(abs(s - a) for s, a in zip(sim1, act1))
            ms1, ma1 = statistics.mean(sim1), statistics.mean(act1)
            cov = sum((s - ms1) * (a - ma1) for s, a in zip(sim1, act1)) / n
            corr = cov / math.sqrt(statistics.pvariance(sim1) * statistics.pvariance(act1)) if statistics.pvariance(sim1) > 0 else 0
            print(f"exponent {exponent:.2f}: first-innings sim {ms1:.1f} vs actual {ma1:.1f} (bias {bias:+.1f}, MAE {mae:.1f}, r {corr:.2f}); "
                  f"wickets sim {statistics.mean(simw):.2f} vs {statistics.mean(actw):.2f}; second innings sim {statistics.mean(sim2):.1f}; "
                  f"winner Brier {statistics.mean(brier):.3f} (coin flip 0.250)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
