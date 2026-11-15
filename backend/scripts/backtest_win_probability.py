"""Chronological backtest of simulator win probabilities (read-only).

Training: calibration, player profiles and venue effects use only matches before
``--cutoff``. Testing: limited-overs matches on/after the cutoff. For each test
match the real state after selected overs is rebuilt from Cricsheet deliveries
(score, wickets, batters at the crease, bowlers' overs, target, and the
match-conditions posterior from every ball so far) and the rest of the match is
re-simulated. Probabilities are for the side batting first.

Reports Brier score, log loss, expected calibration error and accuracy overall, by
phase, by required run rate and by wickets remaining, for several simulation
counts, plus the Monte Carlo noise (mean |difference| between two independent
seeds) at each count.

Run from backend/:
    .venv/bin/python scripts/backtest_win_probability.py --matches 40 --sims 100,500,2000,5000
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import bindparam, text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.ml import match_simulator as ms  # noqa: E402
from app.ml import sim_calibration as cal  # noqa: E402

CLS_SQL = cal.class_sql("COALESCE(w.bw, FALSE)", "COALESCE(w.ro, FALSE)", "COALESCE(x.wides, 0)", "COALESCE(x.noballs, 0)",
                        "COALESCE(x.byes, 0)", "COALESCE(x.legbyes, 0)", "d.batter_runs")


def test_matches(db, family, gender, cutoff, limit):
    overs = cal.DEFAULT_OVERS[family]
    return db.execute(text("""
        SELECT m.id, m.winner_id, m.result_type, m.venue_id, m.start_date FROM matches m
        WHERE m.match_format IN :formats AND m.gender = :gender AND m.start_date >= :cutoff
          AND m.result_type IN ('win', 'tie')
          AND (SELECT COUNT(*) FROM match_innings mi WHERE mi.match_id = m.id AND NOT mi.is_super_over) = 2
          AND NOT EXISTS (SELECT 1 FROM match_innings mi WHERE mi.match_id = m.id AND mi.target_overs IS NOT NULL AND mi.target_overs < :overs)
        ORDER BY md5(m.id) LIMIT :limit""").bindparams(bindparam("formats", expanding=True)),
        {"formats": list(cal.FAMILY_FORMATS[family]), "gender": gender, "cutoff": cutoff, "limit": limit, "overs": overs}).mappings().all()


def deliveries(db, match_id):
    return db.execute(text(f"""
        SELECT mi.innings_number AS inn, mi.batting_team_id AS team, d.over_number AS over, d.batter_id, d.non_striker_id,
               d.bowler_id, d.total_runs, d.is_legal_ball AS legal, {CLS_SQL} AS cls,
               COALESCE(w.nout, 0) AS outs
        FROM match_innings mi JOIN deliveries d ON d.innings_id = mi.id
        {cal._EXTRAS_JOIN.format(where='')} {cal._WICKETS_JOIN.format(where='')}
        WHERE mi.match_id = :m AND NOT mi.is_super_over ORDER BY mi.innings_number, d.over_number, d.delivery_sequence"""),
        {"m": match_id}).mappings().all()


def rebuild(rows):
    inns = {1: [], 2: []}
    team = {}
    for r in rows:
        inns[r["inn"]].append(r)
        team[r["inn"]] = r["team"]
    order = {1: [], 2: []}
    bowlers = {1: [], 2: []}
    for i in (1, 2):
        for r in inns[i]:
            for p in (r["batter_id"], r["non_striker_id"]):
                if p and p not in order[i]:
                    order[i].append(p)
            if r["bowler_id"] and r["bowler_id"] not in bowlers[i]:
                bowlers[i].append(r["bowler_id"])
    xi = {"A": list(order[1]), "B": list(order[2])}
    for p in bowlers[2]:
        if p not in xi["A"]:
            xi["A"].append(p)
    for p in bowlers[1]:
        if p not in xi["B"]:
            xi["B"].append(p)
    for k in xi:  # pad unknown non-participants so batting depth is eleven
        while len(xi[k]) < 11:
            xi[k].append(f"pad-{k}-{len(xi[k])}")
    return inns, team, xi


def states(model, rules, inns, xi, every):
    """Real match states at the start of every ``every``-th over, with conditions log-likelihoods."""
    out = []
    ll = [0.0] * ms.CONDITION_BINS
    target = sum(r["total_runs"] for r in inns[1]) + 1
    cap = rules.overs * 6
    for idx, i in enumerate((1, 2)):
        key = "A" if i == 1 else "B"
        score = wk = legal = 0
        overs_bowled = defaultdict(int)
        prev_nb = False
        last_bowler = None
        appeared = []
        recorded = set()
        for r in inns[i]:
            if legal % 6 == 0 and legal not in recorded and (legal // 6) % every == 0:
                recorded.add(legal)
                pair = (r["batter_id"], r["non_striker_id"])
                seen = list(appeared)
                for p in pair:
                    if p not in seen:
                        seen.append(p)
                order = seen + [p for p in xi[key] if p not in seen]
                out.append((idx, i, {"score": score, "wickets": wk, "legal_balls": legal, "striker": pair[0], "non_striker": pair[1],
                                     "next_index": len(seen), "overs_bowled": dict(overs_bowled), "last_bowler": last_bowler,
                                     "loglik": list(ll)}, order, target))
            for p in (r["batter_id"], r["non_striker_id"]):
                if p not in appeared:
                    appeared.append(p)
            ci = cal.CLASS_INDEX.get(r["cls"])
            if ci is not None and r["batter_id"] and r["bowler_id"]:
                over_index = min(legal // 6, rules.overs - 1)
                rrb = model.rrb_for(target, score, cap - legal) if i == 2 else -1
                for k in range(ms.CONDITION_BINS):
                    ck = model.cum_probs(r["batter_id"], r["bowler_id"], i, over_index, min(wk, 9), rrb,
                                         prev_nb and rules.free_hit, i >= 2, False, k)
                    pk = (ck[ci] - (ck[ci - 1] if ci else 0.0)) / ck[-1]
                    ll[k] += math.log(pk) if pk > 0 else -50.0
            prev_nb = r["cls"] == "NB"
            score += r["total_runs"]
            wk += int(r["outs"])
            if r["legal"]:
                legal += 1
                if legal % 6 == 0:
                    overs_bowled[r["bowler_id"]] += 1
                    last_bowler = r["bowler_id"]
    return out, target


def phase_label(family, idx, over):
    p = cal.phase_of(family, min(over, cal.DEFAULT_OVERS[family] - 1))
    return f"inn{idx + 1}-{p}"


def metrics(rows):
    if not rows:
        return {}
    n = len(rows)
    brier = sum((p - y) ** 2 for p, y in rows) / n
    eps = 1e-6
    ll = -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)) for p, y in rows) / n
    acc = sum(1 for p, y in rows if (p > 0.5 and y > 0.5) or (p < 0.5 and y < 0.5) or (p == 0.5)) / n
    bins = defaultdict(list)
    for p, y in rows:
        bins[min(9, int(p * 10))].append((p, y))
    ece = sum(len(b) / n * abs(sum(p for p, _ in b) / len(b) - sum(y for _, y in b) / len(b)) for b in bins.values())
    reliability = [{"bin": f"{k / 10:.1f}-{(k + 1) / 10:.1f}", "n": len(b), "mean_p": round(sum(p for p, _ in b) / len(b), 3),
                    "observed": round(sum(y for _, y in b) / len(b), 3)} for k, b in sorted(bins.items())]
    return {"n": n, "brier": round(brier, 4), "log_loss": round(ll, 4), "ece": round(ece, 4), "accuracy": round(acc, 4),
            "reliability": reliability}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="T20")
    ap.add_argument("--gender", default="male")
    ap.add_argument("--cutoff", default="2024-01-01")
    ap.add_argument("--matches", type=int, default=40)
    ap.add_argument("--sims", default="100,500,2000")
    ap.add_argument("--every", type=int, default=4, help="evaluate after every N overs")
    ap.add_argument("--out", default=None)
    ap.add_argument("--condition-scale", type=float, default=None, help="override the conditions scale (0 = ablation: no shared conditions)")
    args = ap.parse_args()
    cutoff = date.fromisoformat(args.cutoff)
    sims_list = [int(x) for x in args.sims.split(",")]
    rules = ms.rules_for({"T20": "T20", "ODI": "ODI"}[args.family])
    db = SessionLocal()
    t0 = time.time()
    try:
        calibration = cal.load_format_calibration(db, args.family, until=cutoff)
        print(f"calibration before {cutoff}: {calibration['genders'][args.gender]['deliveries']:,} deliveries "
              f"({time.time() - t0:.0f}s); conditions {calibration['genders'][args.gender].get('conditions', {}).get('scale')}", flush=True)
        matches = test_matches(db, args.family, args.gender, cutoff, args.matches)
        records = []  # (sims, seed, idx, over, rrr, wickets_left, p, y)
        prematch = []
        for mnum, m in enumerate(matches):
            rows = deliveries(db, m["id"])
            inns, team, xi = rebuild(rows)
            ids = [p for k in xi for p in xi[k] if not p.startswith("pad-")]
            profiles = cal.load_player_profiles(db, args.family, args.gender, ids, until=cutoff)
            meta = cal.load_player_meta(db, ids)
            venue = cal.load_venue_profile(db, args.family, args.gender, m["venue_id"], until=cutoff)
            positions = {p: i + 1 for k in xi for i, p in enumerate(xi[k])}
            model = ms.SimModel(calibration, args.family, args.gender, profiles, meta, venue=venue, positions=positions,
                                condition_scale=args.condition_scale)
            teams = {"A": ms.TeamSetup("A", "first", xi["A"]), "B": ms.TeamSetup("B", "second", xi["B"])}
            y = 0.5 if m["result_type"] == "tie" else (1.0 if m["winner_id"] == team[1] else 0.0)
            st, target = states(model, rules, inns, xi, args.every)
            first = ms.InningsResult(1, "A", "B")
            chase = ms.InningsResult(2, "B", "A", target=target)
            for idx, i, snap, order, _ in st:
                inn_obj = first if idx == 0 else chase
                bat_key = "A" if idx == 0 else "B"
                saved = teams[bat_key].order
                teams[bat_key].order = order
                post = ms.condition_posterior(snap["loglik"])
                cum_post = ms._cum(post)
                over = snap["legal_balls"] // 6
                rrr = None
                if idx == 1:
                    balls_left = rules.overs * 6 - snap["legal_balls"]
                    rrr = (target - snap["score"]) * 6 / balls_left if balls_left else None
                for sims in sims_list:
                    for seed in ((1, 2) if sims <= 2000 else (1,)):
                        exact = ms._terminal(rules, idx, inn_obj, snap)
                        if exact is not None:
                            p = exact
                        else:
                            a = 0.0
                            for j in range(sims):
                                rng = random.Random(f"bt:{seed}:{j}")
                                zk = min(ms.CONDITION_BINS - 1, ms.bisect_right(cum_post, rng.random() * cum_post[-1]))
                                share, _ = ms.outcome_from_state(model, rules, teams, idx, first, inn_obj, snap, rng, zk)
                                a += share
                            p = (a + 0.5) / (sims + 1)
                        records.append({"sims": sims, "seed": seed, "idx": idx, "over": over, "rrr": rrr,
                                        "wickets_left": 10 - snap["wickets"], "p": p, "y": y, "match": m["id"]})
                teams[bat_key].order = saved
            pm = [r for r in records if r["match"] == m["id"] and r["idx"] == 0 and r["over"] == 0 and r["seed"] == 1]
            prematch.extend(pm)
            print(f"[{mnum + 1}/{len(matches)}] {m['start_date']} states={len(st)} y={y} pre-match p={[round(r['p'], 3) for r in pm]} "
                  f"({time.time() - t0:.0f}s)", flush=True)
        report = {"condition_scale": model.condition_scale, "cutoff": str(cutoff), "family": args.family, "gender": args.gender, "matches": len(matches), "by_sims": {}}
        for sims in sims_list:
            rows = [r for r in records if r["sims"] == sims and r["seed"] == 1]
            pairs = [(r["p"], r["y"]) for r in rows]
            entry = {"overall": metrics(pairs), "pre_match": metrics([(r["p"], r["y"]) for r in rows if r["idx"] == 0 and r["over"] == 0])}
            by_phase = defaultdict(list)
            by_rrr = defaultdict(list)
            by_wk = defaultdict(list)
            for r in rows:
                by_phase[phase_label(args.family, r["idx"], r["over"])].append((r["p"], r["y"]))
                if r["idx"] == 1 and r["rrr"] is not None:
                    band = "<6" if r["rrr"] < 6 else "6-8" if r["rrr"] < 8 else "8-10" if r["rrr"] < 10 else "10-12" if r["rrr"] < 12 else "12+"
                    by_rrr[band].append((r["p"], r["y"]))
                    by_wk["8-10" if r["wickets_left"] >= 8 else "5-7" if r["wickets_left"] >= 5 else "0-4"].append((r["p"], r["y"]))
            entry["by_phase"] = {k: {x: v for x, v in metrics(v).items() if x != "reliability"} for k, v in sorted(by_phase.items())}
            entry["chase_by_required_rate"] = {k: {x: v for x, v in metrics(v).items() if x != "reliability"} for k, v in by_rrr.items()}
            entry["chase_by_wickets_left"] = {k: {x: v for x, v in metrics(v).items() if x != "reliability"} for k, v in by_wk.items()}
            two = defaultdict(dict)
            for r in records:
                if r["sims"] == sims:
                    two[(r["match"], r["idx"], r["over"])][r["seed"]] = r["p"]
            diffs = [abs(v[1] - v[2]) for v in two.values() if 1 in v and 2 in v]
            if diffs:
                entry["seed_noise_mean_abs_diff"] = round(sum(diffs) / len(diffs), 4)
                entry["seed_noise_max_abs_diff"] = round(max(diffs), 4)
            report["by_sims"][str(sims)] = entry
        report["elapsed_seconds"] = round(time.time() - t0)
        text_out = json.dumps(report, indent=1)
        print(text_out)
        if args.out:
            Path(args.out).write_text(text_out)
    finally:
        db.close()


if __name__ == "__main__":
    main()
