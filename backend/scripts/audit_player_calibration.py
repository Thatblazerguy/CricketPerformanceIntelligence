"""Audit how each selected player's history shows up in simulated matches (read-only).

For a match setup (two XIs), simulate N detailed matches and compare per player:
batting average, strike rate, dot %, boundary %, phase strike rates; bowling
economy, balls per wicket, dot %, boundary %, phase economy. Historical figures
are the recency-weighted CPI rates the engine is calibrated on (same format
family, gender and window). Simulated figures also reflect the opposition, the
batting position and match situations, so they should track history closely in
rank (high correlation) without matching exactly.

Run from backend/:
    .venv/bin/python scripts/audit_player_calibration.py payload.json [--sims 1000]
where payload.json is a /simulator/match/validate request body.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.ml import match_simulator as ms  # noqa: E402
from app.ml.sim_calibration import CLASS_INDEX as I, PHASES, phase_of  # noqa: E402
from app.services import match_simulation as svc  # noqa: E402

RUNS = [0, 1, 2, 3, 4, 5, 6, 0, 0, 1, 1, 1, 1]


def historical(profile: dict, family: str) -> dict:
    """Rates from the (recency-weighted) outcome counts the engine uses."""
    bat = defaultdict(float)
    bat_phase = defaultdict(lambda: [0.0, 0.0])
    for key, v in (profile.get("bat") or {}).items():
        phase = key.split("|")[0]
        faced = sum(v) - v[I["WD"]]
        runs = sum(v[i] * RUNS[i] for i in range(7)) + v[I["NB"]] * 0  # runs off the bat on legal balls
        bat["balls"] += faced
        bat["runs"] += runs
        bat["outs"] += v[I["W"]] + v[I["RO"]] * 0.5  # about half of run-outs involve the striker
        bat["dots"] += v[I["R0"]]
        bat["bnd"] += v[I["R4"]] + v[I["R6"]]
        bat_phase[phase][0] += runs
        bat_phase[phase][1] += faced
    bowl = defaultdict(float)
    bowl_phase = defaultdict(lambda: [0.0, 0.0])
    for key, v in (profile.get("bowl") or {}).items():
        phase = key.split("|")[0]
        legal = sum(v) - v[I["WD"]] - v[I["NB"]]
        conceded = sum(v[i] * RUNS[i] for i in range(7)) + v[I["WD"]] + v[I["NB"]]
        bowl["legal"] += legal
        bowl["runs"] += conceded
        bowl["wkts"] += v[I["W"]]
        bowl["dots"] += v[I["R0"]]
        bowl["bnd"] += v[I["R4"]] + v[I["R6"]]
        bowl_phase[phase][0] += conceded
        bowl_phase[phase][1] += legal
    return {"bat": bat, "bat_phase": bat_phase, "bowl": bowl, "bowl_phase": bowl_phase}


def rates(b, bp, w, wp, phases):
    out = {
        "bat_avg": b["runs"] / b["outs"] if b["outs"] else None,
        "bat_sr": 100 * b["runs"] / b["balls"] if b["balls"] else None,
        "bat_dot": 100 * b["dots"] / b["balls"] if b["balls"] else None,
        "bat_bnd": 100 * b["bnd"] / b["balls"] if b["balls"] else None,
        "econ": 6 * w["runs"] / w["legal"] if w["legal"] else None,
        "balls_per_wkt": w["legal"] / w["wkts"] if w["wkts"] else None,
        "bowl_dot": 100 * w["dots"] / w["legal"] if w["legal"] else None,
        "bowl_bnd": 100 * w["bnd"] / w["legal"] if w["legal"] else None,
    }
    for p in phases:
        r, n = bp.get(p, (0, 0))
        out[f"sr_{p}"] = 100 * r / n if n >= 1 else None
        r, n = wp.get(p, (0, 0))
        out[f"econ_{p}"] = 6 * r / n if n >= 1 else None
    return out


def simulate(ctx, sims, seed):
    model, rules, teams = ctx["model"], ctx["rules"], ctx["teams"]
    bat = defaultdict(lambda: defaultdict(float))
    bat_phase = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    bowl = defaultdict(lambda: defaultdict(float))
    bowl_phase = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for j in range(sims):
        r = ms.simulate_match(model, rules, teams, random.Random(f"{seed}:{j}"), detailed=True)
        for inn in r["innings"]:
            if inn.super_over:
                continue
            for d in inn.deliveries:
                p = phase_of(rules.family, d["over_index"])
                cls = d["outcome"]
                b, w = d["batter_id"], d["bowler_id"]
                if cls != "WD":
                    bat[b]["balls"] += 1
                    bat[b]["runs"] += d["batter_runs"]
                    bat[b]["dots"] += cls == "R0"
                    bat[b]["bnd"] += cls in ("R4", "R6")
                    bat_phase[b][p][0] += d["batter_runs"]
                    bat_phase[b][p][1] += 1
                if d["wicket"] and d["wicket"]["player_out"] == b:
                    bat[b]["outs"] += 1
                if d["wicket"] and d["wicket"]["player_out"] != b:
                    bat[d["wicket"]["player_out"]]["outs"] += 1
                conceded = d["batter_runs"] + d["extras"].get("wides", 0) + d["extras"].get("noballs", 0)
                bowl[w]["runs"] += conceded
                bowl_phase[w][p][0] += conceded
                if d["legal"]:
                    bowl[w]["legal"] += 1
                    bowl[w]["dots"] += cls == "R0"
                    bowl[w]["bnd"] += cls in ("R4", "R6")
                    bowl_phase[w][p][1] += 1
                if d["wicket"] and d["wicket"]["bowler_credited"]:
                    bowl[w]["wkts"] += 1
    return bat, bat_phase, bowl, bowl_phase


def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    sx = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs))
    sy = math.sqrt(sum((y - my) ** 2 for _, y in pairs))
    return sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy) if sx and sy else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("payload")
    ap.add_argument("--sims", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--json", help="write the full comparison to this file")
    args = ap.parse_args()
    payload = json.loads(Path(args.payload).read_text())
    db = SessionLocal()
    try:
        ctx = svc.build_context(db, payload)
    finally:
        db.close()
    family = ctx["rules"].family
    phases = PHASES[family]
    bat, bat_phase, bowl, bowl_phase = simulate(ctx, args.sims, args.seed)
    rows = []
    for key, team in ctx["teams"].items():
        options = set(ms.bowling_options(ctx["model"], team, ctx["rules"]))
        for pos, pid in enumerate(team.order, 1):
            prof = ctx["model"].profiles.get(pid) or {}
            h = historical(prof, family)
            hist = rates(h["bat"], h["bat_phase"], h["bowl"], h["bowl_phase"], phases)
            sim = rates(bat[pid], bat_phase[pid], bowl[pid], bowl_phase[pid], phases)
            rows.append({"team": team.name, "pos": pos, "player": ctx["meta"].get(pid, {}).get("name", pid), "id": pid,
                         "hist_bat_balls": prof.get("bat_balls", 0), "hist_bowl_balls": prof.get("bowl_balls", 0),
                         "bowling_option": pid in options, "sim_bat_balls": bat[pid]["balls"], "sim_bowl_balls": bowl[pid]["legal"],
                         "hist": hist, "sim": sim})
    metrics = list(rows[0]["hist"].keys())
    summary = {}
    for m in metrics:
        hs, ss = [], []
        for r in rows:
            enough = (r["sim_bat_balls"] >= 300 and r["hist_bat_balls"] >= 300) if m.startswith(("bat", "sr_")) else \
                     (r["sim_bowl_balls"] >= 300 and r["hist_bowl_balls"] >= 300)
            if enough and r["hist"][m] is not None and r["sim"][m] is not None:
                hs.append(r["hist"][m])
                ss.append(r["sim"][m])
        if hs:
            summary[m] = {"players": len(hs), "correlation": round(corr(hs, ss), 3) if corr(hs, ss) is not None else None,
                          "mean_hist": round(sum(hs) / len(hs), 2), "mean_sim": round(sum(ss) / len(ss), 2)}
    fmt = lambda v: "   -  " if v is None else f"{v:6.1f}"
    print(f"{args.sims} simulated matches, {family}; historical = recency-weighted CPI rates since {ctx['model'].calibration_meta['since'][:4]}")
    print(f"{'player':22} {'bat SR h/s':>14} {'avg h/s':>14} {'dot% h/s':>14} {'econ h/s':>14} {'b/wkt h/s':>14} {'sim overs':>9}")
    for r in rows:
        h, s = r["hist"], r["sim"]
        print(f"{r['player'][:22]:22} {fmt(h['bat_sr'])}/{fmt(s['bat_sr'])} {fmt(h['bat_avg'])}/{fmt(s['bat_avg'])} {fmt(h['bat_dot'])}/{fmt(s['bat_dot'])} "
              f"{fmt(h['econ'])}/{fmt(s['econ'])} {fmt(h['balls_per_wkt'])}/{fmt(s['balls_per_wkt'])} {r['sim_bowl_balls'] / 6 / args.sims:9.2f}")
    print("\nAcross players with >=300 balls in both history and simulation:")
    for m, v in summary.items():
        print(f"  {m:16} n={v['players']:2}  r={v['correlation']}  mean hist {v['mean_hist']}  sim {v['mean_sim']}")
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows, "summary": summary}, indent=1, default=float))


if __name__ == "__main__":
    main()
