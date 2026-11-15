"""Matchup intelligence: team-vs-team and batter-vs-bowler head-to-head analysis.

Team matchups reuse the Team/Venue Analytics engine (``competition_common``):
matches come from ``load_matches`` (stored matches + persisted
``team_innings_summary`` totals), so results, completeness, chase facts,
close-match rules and home/away classification are identical to Team
Analytics and Venue Analytics.

Player matchups read the raw ``deliveries`` between one batter and one bowler
(indexed on ``(batter_id, bowler_id)``; at most a few hundred rows) once, and
derive every breakdown from that single row set, so every split adds up to the
headline. Context baselines (the batter against all pace/spin, the batter and
bowler at a venue) come from the persisted scouting innings tables, which use
the same delivery rules.

Delivery rules (identical to ``scouting_aggregates`` / ``cricket_rules``):

* Super-over innings are excluded everywhere.
* Ball faced = ``is_ball_faced_by_batter`` (wides excluded, no-balls included).
* Batter dot = ball faced with zero batter runs.
* Bowler-credited dismissal = ``wickets.is_bowler_wicket`` with the batter out;
  run outs etc. while facing the bowler are reported separately, never credited.
* Runs conceded = ``bowling_runs`` (byes, leg-byes and penalties excluded);
  economy uses legal balls (``is_legal_ball``).

Nothing is imputed: undefined ratios are ``None`` and every block carries its
sample size. Insights are historical observations with their sample and
statistical basis; none of them is a prediction.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.competition_common import (
    LIMITED, MIN_SAMPLE, PHASES, PHASE_NAMES, Scope, avg, binomial_p, cached, div, fmt_p, format_baseline,
    home_ground_map, load_matches, margin_text, pct, proportion, rate, team_result, two_proportion_p, venue_side,
)
from app.analytics.team_analytics import chase_defence, innings_block, order_split, phase_block, record

LIMITED_SAMPLE = 5          # below this an observation is not reported at all
SIDES = ("home", "away", "neutral")
FAMILY = {"T20": "T20", "T20I": "T20", "ODI": "ODI", "ODM": "ODI"}  # phase-compatible format families


def _sample(n: int) -> str:
    return "none" if not n else "low" if n < MIN_SAMPLE else "limited" if n < 30 else "ok"


def _sig(p: Optional[float]) -> bool:
    return p is not None and p < 0.05


def _sig_text(p: Optional[float]) -> str:
    if p is None:
        return "significance not testable"
    return f"statistically significant ({fmt_p(p)})" if p < 0.05 else f"not statistically significant ({fmt_p(p)}) — could be chance"


def _insight(kind: str, text_: str, basis: str, n: int, tone: str = "neutral", p: Optional[float] = None,
             unit: str = "matches") -> dict:
    limited = n < MIN_SAMPLE
    return {"kind": kind, "tone": tone, "text": text_ + (" (limited historical data)" if limited else ""),
            "basis": basis, "n": n, "unit": unit, "sample": _sample(n), "p": p,
            "significant": _sig(p) if p is not None else None, "type": "historical"}


def _date_clause(params: dict, date_from: Optional[str], date_to: Optional[str], alias: str = "m") -> List[str]:
    out = []
    if date_from:
        out.append(f"{alias}.start_date >= :date_from"); params["date_from"] = date.fromisoformat(date_from)
    if date_to:
        out.append(f"{alias}.start_date <= :date_to"); params["date_to"] = date.fromisoformat(date_to)
    return out


def _score(i: Optional[dict]) -> Optional[str]:
    if not i:
        return None
    return f"{i['runs']}/{i['wickets']}" if i["wickets"] < 10 else str(i["runs"])


def _overs(balls: Optional[int]) -> Optional[str]:
    return f"{balls // 6}.{balls % 6}" if balls is not None else None


# ============================================================== player of match

def player_of_match(db: Session, match_ids: List[str]) -> Dict[str, List[dict]]:
    """Player-of-the-match names from the stored Cricsheet source, resolved to player ids where possible."""
    if not match_ids:
        return {}
    rows = db.execute(text("""
        SELECT m.id, rm.raw_json -> 'info' -> 'player_of_match' AS pom
        FROM matches m JOIN raw_matches rm ON rm.provider_id = m.provider_id AND rm.source_match_id = m.source_match_id
        WHERE m.id = ANY(:ids)"""), {"ids": match_ids}).all()
    # Resolve names against the players who batted or bowled in that match (names are unique within a match).
    people = db.execute(text("""
        SELECT x.match_id, p.id, p.canonical_name FROM (
            SELECT match_id, player_id FROM scouting_bat_innings WHERE match_id = ANY(:ids)
            UNION SELECT match_id, player_id FROM scouting_bowl_innings WHERE match_id = ANY(:ids)) x
        JOIN players p ON p.id = x.player_id"""), {"ids": match_ids}).all()
    by_match = defaultdict(dict)
    for mid, pid, name in people:
        by_match[mid][name] = pid
    out = {}
    for mid, pom in rows:
        names = [n for n in (pom or []) if isinstance(n, str)]
        out[mid] = [{"name": n, "player_id": by_match[mid].get(n)} for n in names]
    return out


# ================================================================ team matchups

def _innings_row(i: Optional[dict], names: dict) -> Optional[dict]:
    if not i:
        return None
    return {"team_id": i["batting_team_id"], "team": names.get(i["batting_team_id"]), "runs": i["runs"],
            "wickets": i["wickets"], "score": _score(i), "overs": _overs(i["legal_balls"]),
            "innings_number": i["innings_number"]}


def _encounter(m: dict, names: dict) -> dict:
    winner = names.get(m["winner_id"]) if m["outcome"] == "decided" else None
    mt = margin_text(m)
    if m["outcome"] == "decided":
        result = f"{winner} won" + (f" {mt}" if mt else "")
    else:
        result = (mt or m["outcome"]).capitalize()
    return {"match_id": m["id"], "date": str(m["start_date"]), "season": m["season"], "competition": m["competition"],
            "venue": m["venue"], "venue_id": m["venue_id"], "city": m["city"], "winner_id": m["winner_id"], "winner": winner,
            "outcome": m["outcome"], "result": result, "margin": mt,
            "toss_winner": names.get(m["toss_winner_id"]), "toss_decision": m["toss_decision"],
            "first_innings": _innings_row(m["first_innings"], names), "second_innings": _innings_row(m["second_innings"], names),
            "close": m["close"], "reduced": m["reduced"], "super_over": m["has_super_over"]}


def _margins(ms: List[dict], team_id: str) -> dict:
    wins = [m for m in ms if m["outcome"] == "decided" and m["winner_id"] == team_id]
    runs = [m["result_margin_runs"] for m in wins if m["result_margin_runs"]]
    wkts = [m["result_margin_wickets"] for m in wins if m["result_margin_wickets"]]
    balls = [m["chase"]["balls_remaining"] for m in wins if m["result_margin_wickets"] and m["chase"] and m["chase"]["balls_remaining"] is not None]
    return {"wins": len(wins), "by_runs": len(runs), "average_runs_margin": avg(runs), "by_wickets": len(wkts),
            "average_wickets_margin": avg(wkts), "average_balls_remaining": avg(balls)}


def _toss(ms: List[dict], a: str, b: str) -> dict:
    known = [m for m in ms if m["outcome"] == "decided" and m["toss_winner_id"]]
    k = sum(1 for m in known if m["winner_id"] == m["toss_winner_id"])
    by_decision = {}
    for dec in ("bat", "field"):
        sub = [m for m in known if m["toss_decision"] == dec]
        by_decision[dec] = {"chosen": sum(1 for m in ms if m["toss_decision"] == dec and m["toss_winner_id"]),
                            "toss_winner_won": proportion(sum(1 for m in sub if m["winner_id"] == m["toss_winner_id"]), len(sub))}
    teams = {}
    for tid in (a, b):
        won_toss = [m for m in ms if m["toss_winner_id"] == tid]
        lost_toss = [m for m in ms if m["toss_winner_id"] and m["toss_winner_id"] != tid]
        teams[tid] = {"won_toss": record(won_toss, tid), "lost_toss": record(lost_toss, tid),
                      "tosses_won": len(won_toss)}
    return {"decided_with_toss": len(known), "toss_winner_won": proportion(k, len(known)), "p_value": binomial_p(k, len(known)),
            "by_decision": by_decision, "teams": teams}


def _order(ms: List[dict], limited: bool) -> dict:
    decided = [m for m in ms if m["outcome"] == "decided" and m["first_batting_id"]]
    bf = sum(1 for m in decided if m["winner_id"] == m["first_batting_id"])
    complete = [m for m in ms if m["complete"]]
    out = {"decided": len(decided), "batting_first_won": proportion(bf, len(decided)),
           "chasing_won": proportion(len(decided) - bf, len(decided)), "p_value": binomial_p(bf, len(decided)),
           "average_first_innings": avg([m["first_innings"]["runs"] for m in complete if m["first_innings"]]),
           "average_second_innings": avg([m["second_innings"]["runs"] for m in complete if m["second_innings"]]),
           "complete_matches": len(complete)}
    if limited:
        chases = [m["chase"] for m in complete if m["chase"] and m["chase"]["won"] is not None]
        won = sum(1 for c in chases if c["won"])
        out["chase_success"] = proportion(won, len(chases))
        out["defend_success"] = proportion(len(chases) - won, len(chases))
    return out


def _records(ms: List[dict], names: dict, limited: bool) -> dict:
    inns = [(m, i) for m in ms for i in m["innings"]]

    def irow(m, i):
        return {"match_id": m["id"], "date": str(m["start_date"]), "team_id": i["batting_team_id"], "team": names.get(i["batting_team_id"]),
                "opponent": names.get(i["bowling_team_id"]), "runs": i["runs"], "wickets": i["wickets"], "score": _score(i),
                "overs": _overs(i["legal_balls"]), "innings_number": i["innings_number"], "venue": m["venue"],
                "reduced": m["reduced"], "won": m["outcome"] == "decided" and m["winner_id"] == i["batting_team_id"]}
    highest = sorted(inns, key=lambda x: -x[1]["runs"])[:5]
    lowest = sorted([x for x in inns if x[1]["finished"]], key=lambda x: x[1]["runs"])[:5]
    out = {"highest_totals": [irow(*x) for x in highest], "lowest_totals": [irow(*x) for x in lowest],
           "lowest_note": "Lowest totals use completed innings only (bowled out or full quota faced, no reduced or abandoned matches)."}
    decided = [m for m in ms if m["outcome"] == "decided"]
    by_runs = sorted([m for m in decided if m["result_margin_runs"]], key=lambda m: -m["result_margin_runs"])[:3]
    by_wkts = sorted([m for m in decided if m["result_margin_wickets"]],
                     key=lambda m: (-m["result_margin_wickets"], -((m["chase"] or {}).get("balls_remaining") or 0)))[:3]
    out["dominant_victories"] = [{**_encounter(m, names), "kind": "runs"} for m in by_runs] + \
                                [{**_encounter(m, names), "kind": "wickets",
                                  "balls_remaining": (m["chase"] or {}).get("balls_remaining")} for m in by_wkts]

    def closeness(m):
        if m["outcome"] == "tie":
            return (0, 0)
        if m["result_margin_runs"]:
            return (1, m["result_margin_runs"])
        br = (m["chase"] or {}).get("balls_remaining")
        return (2, br if br is not None else 999, m["result_margin_wickets"] or 99)
    close = sorted([m for m in ms if m["close"]], key=closeness)[:5]
    out["closest_finishes"] = [_encounter(m, names) for m in close]
    if limited:
        chases = [m for m in ms if m["complete"] and m["chase"] and m["chase"]["won"]]
        best = max(chases, key=lambda m: m["chase"]["target"], default=None)
        out["highest_successful_chase"] = ({**_encounter(best, names), "target": best["chase"]["target"],
                                            "team": names.get(best["chase"]["chasing_id"])} if best else None)
    return out


def _seasons(ms: List[dict], a: str, b: str, key: str) -> List[dict]:
    by = defaultdict(list)
    for m in ms:
        by[m[key] or "Unknown"].append(m)
    rows = []
    for k, sub in by.items():
        ra = record(sub, a)
        complete = [m for m in sub if m["complete"] and m["first_innings"]]
        rows.append({key: k, "matches": len(sub), "a_won": ra["won"], "b_won": ra["lost"], "tied": ra["tied"],
                     "drawn": ra["drawn"], "no_result": ra["no_result"], "a_win_percentage": ra["win_percentage"],
                     "average_first_innings": avg([m["first_innings"]["runs"] for m in complete]),
                     "last_played": str(sub[-1]["start_date"]), "last_match_id": sub[-1]["id"]})
    return sorted(rows, key=lambda r: r[key], reverse=(key == "season"))


def _venue_table(ms: List[dict], a: str) -> List[dict]:
    by = defaultdict(list)
    for m in ms:
        if m["venue_id"]:
            by[m["venue_id"]].append(m)
    rows = []
    for vid, sub in by.items():
        ra = record(sub, a)
        complete = [m for m in sub if m["complete"] and m["first_innings"]]
        rows.append({"venue_id": vid, "venue": sub[0]["venue"], "city": sub[0]["city"], "matches": len(sub),
                     "a_won": ra["won"], "b_won": ra["lost"], "other": ra["matches"] - ra["won"] - ra["lost"],
                     "average_first_innings": avg([m["first_innings"]["runs"] for m in complete]),
                     "last_played": str(sub[-1]["start_date"])})
    return sorted(rows, key=lambda r: (-r["matches"], r["venue"] or ""))


def _collapses(db: Session, ms: List[dict], names: dict, limited: bool) -> dict:
    """Batting collapses (4+ wickets for ≤30 runs) and recoveries (3+ down in the powerplay, still won)."""
    if not ms:
        return {"teams": {}, "definitions": {}}
    rows = db.execute(text("""
        WITH seq AS (
            SELECT mi.match_id, mi.id AS innings_id, mi.batting_team_id, d.phase, d.id AS delivery_id,
                   SUM(d.total_runs) OVER w AS cum_runs,
                   COUNT(*) FILTER (WHERE d.is_legal_ball) OVER w AS cum_balls
            FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id AND mi.is_super_over = FALSE
            WHERE mi.match_id = ANY(:ids)
            WINDOW w AS (PARTITION BY d.innings_id ORDER BY d.over_number, d.delivery_sequence)
        )
        SELECT s.match_id, s.innings_id, s.batting_team_id, s.phase, s.cum_runs, s.cum_balls
        FROM seq s JOIN wickets wk ON wk.delivery_id = s.delivery_id AND wk.is_batter_dismissed
        ORDER BY s.innings_id, s.cum_balls, s.cum_runs"""), {"ids": [m["id"] for m in ms]}).all()
    falls = defaultdict(list)
    for r in rows:
        falls[r.innings_id].append(r)
    by_match = {m["id"]: m for m in ms}
    teams = defaultdict(lambda: {"innings": 0, "collapses": 0, "recoveries": 0, "examples": [], "recovery_examples": []})
    for m in ms:
        for i in m["innings"]:
            teams[i["batting_team_id"]]["innings"] += 1
    for inn_id, fl in falls.items():
        mid, tid = fl[0].match_id, fl[0].batting_team_id
        m = by_match[mid]
        t = teams[tid]
        worst = None
        for j in range(len(fl) - 3):
            start = fl[j - 1].cum_runs if j > 0 else 0
            lost = fl[j + 3].cum_runs - start
            if lost <= 30 and (worst is None or lost < worst[0]):
                worst = (lost, f"{start}/{j}", f"{fl[j + 3].cum_runs}/{j + 4}")
        if worst:
            t["collapses"] += 1
            t["examples"].append({"match_id": mid, "date": str(m["start_date"]), "from": worst[1], "to": worst[2],
                                  "runs": worst[0], "won": m["outcome"] == "decided" and m["winner_id"] == tid})
        if limited:
            pp_wkts = sum(1 for f in fl if f.phase == "powerplay")
            if pp_wkts >= 3 and m["outcome"] == "decided" and m["winner_id"] == tid:
                t["recoveries"] += 1
                t["recovery_examples"].append({"match_id": mid, "date": str(m["start_date"]), "powerplay_wickets": pp_wkts})
    out = {}
    for tid, t in teams.items():
        t["examples"] = sorted(t["examples"], key=lambda e: e["date"], reverse=True)[:5]
        t["recovery_examples"] = sorted(t["recovery_examples"], key=lambda e: e["date"], reverse=True)[:5]
        t["collapse_rate"] = pct(t["collapses"], t["innings"])
        out[tid] = t
    return {"teams": out, "definitions": {
        "collapse": "Four or more wickets lost for 30 runs or fewer at any point of an innings (counted once per innings).",
        "recovery": "Three or more wickets lost in the powerplay and the match still won." if limited else None}}


def _side_batting(ms: List[dict], tid: str, base_phases: Optional[dict], limited: bool) -> dict:
    bat = [i for m in ms for i in m["innings"] if i["batting_team_id"] == tid]
    bowl = [i for m in ms for i in m["innings"] if i["bowling_team_id"] == tid]
    first = [i for i in bat if i["innings_number"] == 1]
    second = [i for i in bat if i["innings_number"] == 2]
    out = {"batting": innings_block(bat), "bowling": innings_block(bowl),
           "batting_first_innings": innings_block(first), "batting_second_innings": innings_block(second),
           "wickets_taken": sum(i["wickets"] for i in bowl), "wickets_lost": sum(i["wickets"] for i in bat)}
    if limited:
        out["batting_phases"] = phase_block(bat, base_phases)
        out["bowling_phases"] = phase_block(bowl, base_phases)
    return out


def _team_insights(d: dict, a_name: str, b_name: str, a: str, b: str, limited: bool) -> List[dict]:
    out: List[dict] = []
    ra = d["overview"]["a"]
    n = ra["decided"]
    # 1. Recent encounters.
    recent = [m for m in d["_matches"] if m["outcome"] == "decided"][-10:]
    if len(recent) >= LIMITED_SAMPLE:
        k = sum(1 for m in recent if m["winner_id"] == a)
        leader, lk = (a_name, k) if k >= len(recent) - k else (b_name, len(recent) - k)
        if lk * 2 != len(recent):
            out.append(_insight("recent", f"{leader} won {lk} of the last {len(recent)} decided encounters.",
                                f"Last {len(recent)} decided matches between the sides under the current filters "
                                f"({recent[0]['start_date']} to {recent[-1]['start_date']}). Ties and no-results excluded.",
                                len(recent), "pos" if leader == a_name else "neg"))
    # 2. Overall record vs a 50/50 split.
    if n >= LIMITED_SAMPLE:
        p = binomial_p(ra["won"], n)
        lead = a_name if ra["won"] > ra["lost"] else b_name if ra["lost"] > ra["won"] else None
        if lead:
            lw, ll = (ra["won"], ra["lost"]) if lead == a_name else (ra["lost"], ra["won"])
            out.append(_insight("record", f"{lead} lead the head-to-head {lw}–{ll} ({pct(lw, n)}% of decided matches).",
                                f"Exact two-sided binomial test against an even 50/50 rivalry: {_sig_text(p)}.", n,
                                "pos" if lead == a_name else "neg", p))
    # 3. Batting order.
    o = d["toss_innings"]["order"]
    if o["decided"] >= LIMITED_SAMPLE:
        bf = o["batting_first_won"]
        better = "the side batting first" if (bf["value"] or 0) > 50 else "the chasing side" if (bf["value"] or 0) < 50 else None
        if better:
            share = bf["value"] if (bf["value"] or 0) > 50 else o["chasing_won"]["value"]
            out.append(_insight("order", f"In this fixture {better} has won {share}% of decided matches.",
                                f"{bf['k']} of {bf['n']} decided matches won batting first; binomial test vs 50%: {_sig_text(o['p_value'])}.",
                                o["decided"], "neutral", o["p_value"]))
    for tid, name in ((a, a_name), (b, b_name)):
        os_ = d["toss_innings"]["order_by_team"][tid]
        f, c = os_["batting_first"], os_["chasing"]
        if f["decided"] >= LIMITED_SAMPLE and c["decided"] >= LIMITED_SAMPLE:
            p = two_proportion_p(f["won"], f["decided"], c["won"], c["decided"])
            gap = abs((f["win_percentage"] or 0) - (c["win_percentage"] or 0))
            if gap >= 15:
                better = "batting second" if (c["win_percentage"] or 0) > (f["win_percentage"] or 0) else "batting first"
                out.append(_insight("order_team", f"{name} have a better record {better} in this matchup: "
                                    f"{c['win_percentage']}% chasing (n={c['decided']}) vs {f['win_percentage']}% batting first (n={f['decided']}).",
                                    f"Two-proportion z-test on decided matches: {_sig_text(p)}.", f["decided"] + c["decided"],
                                    "pos" if tid == a else "neg", p))
    # 4. Toss.
    t = d["toss_innings"]["toss"]
    tw = t["toss_winner_won"]
    if tw["n"] >= LIMITED_SAMPLE and tw["value"] is not None and abs(tw["value"] - 50) >= 10:
        out.append(_insight("toss", f"The toss winner has won {tw['value']}% of decided encounters ({tw['k']} of {tw['n']}).",
                            f"Binomial test against 50%: {_sig_text(t['p_value'])}. Toss winners {'' if tw['value'] > 50 else 'have not '}converted the toss advantage historically.",
                            tw["n"], "neutral", t["p_value"]))
    # 5. Phase scoring gaps.
    if limited:
        sa, sb = d["batting_bowling"][a], d["batting_bowling"][b]
        for pa, pb in zip(sa.get("batting_phases") or [], sb.get("batting_phases") or []):
            if pa["run_rate"] is None or pb["run_rate"] is None or min(pa["balls"], pb["balls"]) < 120:
                continue
            diff = pa["run_rate"] - pb["run_rate"]
            if abs(diff) >= 0.5:
                lead, lv, tv = (a_name, pa, pb) if diff > 0 else (b_name, pb, pa)
                out.append(_insight("phase", f"{lead} consistently score faster in the {pa['phase']} overs in this matchup: "
                                    f"{lv['run_rate']} vs {tv['run_rate']} runs per over.",
                                    f"Aggregate {pa['phase']} run rate across {pa['innings']} and {pb['innings']} innings "
                                    f"({pa['balls']} and {pb['balls']} legal balls). Difference ≥0.5 RPO threshold; descriptive, not tested.",
                                    min(pa["innings"], pb["innings"]), "pos" if lead == a_name else "neg", unit="innings"))
    # 6. Collapses.
    col = d["collapses"]["teams"]
    for tid, name in ((a, a_name), (b, b_name)):
        c = col.get(tid)
        if c and c["innings"] >= LIMITED_SAMPLE and c["collapses"] >= 2 and (c["collapse_rate"] or 0) >= 20:
            out.append(_insight("collapse", f"{name} collapsed in {c['collapses']} of {c['innings']} innings against this opponent ({c['collapse_rate']}%).",
                                d["collapses"]["definitions"]["collapse"], c["innings"], "neg" if tid == a else "pos", unit="innings"))
    # 7. Venue.
    v = d.get("venue")
    if v and v.get("teams"):
        va, vb = v["teams"][a]["record"], v["teams"][b]["record"]
        if va["decided"] >= LIMITED_SAMPLE and vb["decided"] >= LIMITED_SAMPLE:
            p = two_proportion_p(va["won"], va["decided"], vb["won"], vb["decided"])
            gap = (va["win_percentage"] or 0) - (vb["win_percentage"] or 0)
            if abs(gap) >= 10:
                lead, lr, tr = (a_name, va, vb) if gap > 0 else (b_name, vb, va)
                out.append(_insight("venue", f"{lead} have the stronger record at {v['venue']['name']}: {lr['win_percentage']}% wins "
                                    f"(n={lr['decided']}) vs {tr['win_percentage']}% (n={tr['decided']}) against all opponents.",
                                    f"Every decided match each side played at this venue in the filtered scope; two-proportion z-test: {_sig_text(p)}.",
                                    min(va["decided"], vb["decided"]), "pos" if lead == a_name else "neg", p))
    if 0 < n < MIN_SAMPLE:
        out.append(_insight("sample", f"Only {n} decided meeting{'s' if n != 1 else ''} in this selection — treat every head-to-head pattern as weak evidence.",
                            "Head-to-head samples under 10 decided matches cannot separate skill from chance.", n))
    return out


def team_matchup(db: Session, a: str, b: str, scope: Scope, *, venue_id: Optional[str] = None,
                 side: Optional[str] = None, order: Optional[str] = None, recent: Optional[int] = None,
                 date_from: Optional[str] = None, date_to: Optional[str] = None) -> Optional[dict]:
    """Everything about the rivalry between teams ``a`` and ``b`` under one scope (without the paged list)."""
    def build():
        teams = {r.id: r.canonical_name for r in db.execute(text("SELECT id, canonical_name FROM teams WHERE id IN (:a, :b)"), {"a": a, "b": b})}
        if a not in teams or b not in teams:
            return None
        params = {"a": a, "b": b}
        conds = ["((m.team1_id = :a AND m.team2_id = :b) OR (m.team1_id = :b AND m.team2_id = :a))"]
        conds += _date_clause(params, date_from, date_to)
        if venue_id:
            conds.append("m.venue_id = :venue_id"); params["venue_id"] = venue_id
        all_ms = load_matches(db, scope, " AND ".join(conds), params)
        limited = scope.limited
        homes = home_ground_map(db, scope.format)
        ms = all_ms
        if side in SIDES:
            ms = [m for m in ms if venue_side(m, a, homes)[0] == side]
        if order == "a_bat_first":
            ms = [m for m in ms if m["first_batting_id"] == a]
        elif order == "a_chasing":
            ms = [m for m in ms if m["first_batting_id"] == b]
        if recent:
            ms = ms[-recent:]
        names = dict(teams)
        base = format_baseline(db, scope)
        ra, rb = record(ms, a), record(ms, b)
        sides = defaultdict(list)
        for m in ms:
            sides[venue_side(m, a, homes)[0]].append(m)
        d = {
            "teams": {"a": {"id": a, "name": teams[a]}, "b": {"id": b, "name": teams[b]}},
            "limited_overs": limited,
            "matches_considered": len(ms),
            "matches_before_view_filters": len(all_ms),
            "overview": {
                "matches": len(ms), "a": ra, "b": rb,
                "a_margins": _margins(ms, a), "b_margins": _margins(ms, b),
                "first_played": str(ms[0]["start_date"]) if ms else None,
                "last_played": str(ms[-1]["start_date"]) if ms else None,
                "reduced_matches": sum(1 for m in ms if m["reduced"]),
                "super_over_ties": sum(1 for m in ms if m["outcome"] == "tie" and m["has_super_over"]),
                "form": [team_result(m, a) for m in ms[-10:]][::-1],
                "form_match_ids": [m["id"] for m in ms[-10:]][::-1],
            },
            "records": _records(ms, names, limited),
            "toss_innings": {"toss": _toss(ms, a, b), "order": _order(ms, limited),
                             "order_by_team": {a: order_split(ms, a), b: order_split(ms, b)},
                             "chase_defence": {a: chase_defence(ms, a), b: chase_defence(ms, b)} if limited else None},
            "batting_bowling": {a: _side_batting(ms, a, base["phases"], limited), b: _side_batting(ms, b, base["phases"], limited)},
            "home_away": {s: record(sides[s], a) for s in ("home", "away", "neutral", "unclassified")},
            "seasons": _seasons(ms, a, b, "season"),
            "competitions": _seasons(ms, a, b, "competition"),
            "venues": _venue_table(ms, a),
            "collapses": _collapses(db, ms, names, limited),
            "baseline": {k: base[k] for k in ("average_first_innings", "average_second_innings", "run_rate",
                                                 "boundary_percentage", "batting_first_win_percentage", "toss_winner_win_percentage")},
            "_matches": ms,
            "_names": names,
        }
        if venue_id:
            d["venue"] = venue_context(db, venue_id, scope, [a, b], ms, names)
        d["insights"] = _team_insights(d, teams[a], teams[b], a, b, limited)
        d["notes"] = [
            "Super-over innings are excluded from all scoring metrics; a super-over tie remains a tie.",
            "Win % = wins ÷ (wins + losses); ties, draws and no-results are reported separately.",
            "Score averages and lowest totals use complete innings only (no abandoned or reduced-overs matches); results use every match.",
            "Home/away is evidence-based (verified national country or detected franchise home ground); other matches are 'unclassified'.",
        ]
        return d
    return cached(("team-matchup", a, b, venue_id, side, order, recent, date_from, date_to) + scope.key(), build)


def team_encounters(db: Session, d: dict, page: int, page_size: int) -> dict:
    ms = list(reversed(d["_matches"]))
    rows = ms[(page - 1) * page_size: page * page_size]
    pom = player_of_match(db, [m["id"] for m in rows])
    items = [{**_encounter(m, d["_names"]), "player_of_match": pom.get(m["id"], [])} for m in rows]
    return {"total": len(ms), "page": page, "page_size": page_size, "items": items,
            "player_of_match_available": any(i["player_of_match"] for i in items),
            "player_of_match_note": "Player of the Match is not stored for these matches (the source match file is not archived), so it is not shown."}


# --------------------------------------------------------------- venue context

def venue_context(db: Session, venue_id: str, scope: Scope, team_ids: List[str], h2h: List[dict], names: dict) -> Optional[dict]:
    v = db.execute(text("SELECT id, canonical_name, city, country FROM venues WHERE id = :v"), {"v": venue_id}).mappings().first()
    if not v:
        return None
    all_at = load_matches(db, scope, "m.venue_id = :venue_id", {"venue_id": venue_id})
    limited = scope.limited
    inns = [i for m in all_at for i in m["innings"]]
    h_inns = [i for m in h2h for i in m["innings"]]
    teams = {}
    for tid in team_ids:
        ms = [m for m in all_at if tid in (m["team1_id"], m["team2_id"])]
        bat = [i for m in ms for i in m["innings"] if i["batting_team_id"] == tid]
        teams[tid] = {"record": record(ms, tid), "batting": innings_block(bat),
                      "order": order_split(ms, tid) if limited else None, "seasons": _team_venue_seasons(ms, tid)}
    return {
        "venue": {"id": v["id"], "name": v["canonical_name"], "city": v["city"], "country": v["country"]},
        "venue_overall": {"matches": len(all_at), "order": _order(all_at, limited), "toss": _toss_simple(all_at),
                          "scoring": innings_block(inns)},
        "head_to_head": {"matches": len(h2h), "order": _order(h2h, limited), "toss": _toss_simple(h2h),
                         "scoring": innings_block(h_inns), "margins": {tid: _margins(h2h, tid) for tid in team_ids}},
        "teams": teams,
        "sample_note": (f"{len(h2h)} head-to-head match{'es' if len(h2h) != 1 else ''} at this venue; "
                        f"{len(all_at)} matches at the venue in total under these filters."),
    }


def _toss_simple(ms: List[dict]) -> dict:
    known = [m for m in ms if m["outcome"] == "decided" and m["toss_winner_id"]]
    k = sum(1 for m in known if m["winner_id"] == m["toss_winner_id"])
    return {"toss_winner_won": proportion(k, len(known)), "p_value": binomial_p(k, len(known)),
            "chose_field": sum(1 for m in ms if m["toss_decision"] == "field"),
            "chose_bat": sum(1 for m in ms if m["toss_decision"] == "bat")}


def _team_venue_seasons(ms: List[dict], tid: str) -> List[dict]:
    by = defaultdict(list)
    for m in ms:
        by[m["season"]].append(m)
    return [{"season": s, **{k: record(sub, tid)[k] for k in ("matches", "won", "lost", "win_percentage")}}
            for s, sub in sorted(by.items(), reverse=True)]


# ============================================================== player matchups

_PAIR_SQL = """
SELECT d.id, d.over_number, d.delivery_sequence, d.phase, d.batter_runs, d.bowling_runs, d.is_legal_ball,
       d.is_ball_faced_by_batter AS faced, d.is_boundary_four AS b4, d.is_boundary_six AS b6,
       mi.innings_number, mi.batting_team_id,
       m.id AS match_id, m.start_date, m.season, m.match_format, m.tournament_id, tr.name AS competition,
       m.venue_id, v.canonical_name AS venue, v.city, v.country AS venue_country,
       m.team1_id, m.team2_id, t1.canonical_name AS team1, t2.canonical_name AS team2,
       CASE WHEN t1.country_confidence = 'high' THEN t1.country END AS team1_country,
       CASE WHEN t2.country_confidence = 'high' THEN t2.country END AS team2_country,
       m.winner_id, lower(coalesce(m.result_type, '')) AS result_type,
       wk.dismissal_type, COALESCE(wk.is_bowler_wicket, FALSE) AS bowler_wicket, (wk.id IS NOT NULL) AS out
FROM deliveries d
JOIN match_innings mi ON mi.id = d.innings_id AND mi.is_super_over = FALSE
JOIN matches m ON m.id = mi.match_id
LEFT JOIN tournaments tr ON tr.id = m.tournament_id
LEFT JOIN venues v ON v.id = m.venue_id
LEFT JOIN teams t1 ON t1.id = m.team1_id
LEFT JOIN teams t2 ON t2.id = m.team2_id
LEFT JOIN LATERAL (
    SELECT w.id, w.dismissal_type, w.is_bowler_wicket FROM wickets w
    WHERE w.delivery_id = d.id AND w.player_out_id = :batter AND w.is_batter_dismissed
    LIMIT 1
) wk ON TRUE
WHERE d.batter_id = :batter AND d.bowler_id = :bowler {where}
ORDER BY m.start_date, m.id, mi.innings_number, d.over_number, d.delivery_sequence
"""


def _player_filters(f: dict, params: dict, alias: str = "m") -> List[str]:
    conds = []
    if f.get("format"):
        conds.append(f"{alias}.match_format = :fmt"); params["fmt"] = f["format"]
    elif f.get("formats"):
        conds.append(f"{alias}.match_format = ANY(:fmts)"); params["fmts"] = list(f["formats"])
    if f.get("competition"):
        conds.append(f"{alias}.tournament_id IN (SELECT id FROM tournaments WHERE name ILIKE :competition)")
        params["competition"] = f"%{f['competition']}%"
    if f.get("season"):
        conds.append(f"{alias}.season = :season"); params["season"] = f["season"]
    conds += _date_clause(params, f.get("date_from"), f.get("date_to"), alias)
    if f.get("venue_id"):
        conds.append(f"{alias}.venue_id = :venue_id"); params["venue_id"] = f["venue_id"]
    return conds


def _agg(rows: Iterable) -> dict:
    balls = runs = fours = sixes = dots = legal = conceded = wides = noballs = 0
    credited = striker_outs = 0
    runs_sq = 0
    for r in rows:
        if r.faced:
            balls += 1; runs += r.batter_runs; runs_sq += r.batter_runs * r.batter_runs
            fours += r.b4; sixes += r.b6
            dots += r.batter_runs == 0
            if not r.is_legal_ball:
                noballs += 1
        else:
            wides += 1
        legal += r.is_legal_ball
        conceded += r.bowling_runs
        if r.out:
            striker_outs += 1
            credited += r.bowler_wicket
    return {"balls": balls, "runs": runs, "fours": fours, "sixes": sixes, "dots": dots,
            "dismissals": credited, "all_dismissals": striker_outs, "other_dismissals": striker_outs - credited,
            "strike_rate": round(100 * runs / balls, 2) if balls else None,
            "average": div(runs, credited), "balls_per_dismissal": div(balls, credited, 1),
            "dot_percentage": pct(dots, balls), "boundary_percentage": pct(fours + sixes, balls),
            "boundary_run_percentage": pct(4 * fours + 6 * sixes, runs),
            "legal_balls": legal, "runs_conceded": conceded, "economy": rate(conceded, legal),
            "wides": wides, "no_balls": noballs, "_runs_sq": runs_sq}


def _group(rows, key) -> Dict:
    by = defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    return by


def _bat_baseline(db: Session, batter: str, f: dict, venue_id: Optional[str] = None) -> dict:
    """The batter against every bowler under the same filters (from ``scouting_bat_innings``)."""
    params = {"p": batter}
    conds = ["b.player_id = :p"] + _player_filters({**f, "venue_id": venue_id}, params, "b")
    if f.get("innings"):
        conds.append("b.innings_number = :inn"); params["inn"] = f["innings"]
    r = db.execute(text(f"""
        SELECT COUNT(*) AS innings, COALESCE(SUM(runs),0) AS runs, COALESCE(SUM(balls),0) AS balls,
               COALESCE(SUM(dismissed::int),0) AS outs, COALESCE(SUM(fours),0) AS fours, COALESCE(SUM(sixes),0) AS sixes,
               COALESCE(SUM(dots),0) AS dots, COALESCE(SUM(runs_sq),0) AS runs_sq,
               COALESCE(SUM(pace_runs),0) AS pace_runs, COALESCE(SUM(pace_balls),0) AS pace_balls, COALESCE(SUM(pace_dots),0) AS pace_dots,
               COALESCE(SUM(pace_bnd),0) AS pace_bnd, COALESCE(SUM(pace_outs),0) AS pace_outs,
               COALESCE(SUM(spin_runs),0) AS spin_runs, COALESCE(SUM(spin_balls),0) AS spin_balls, COALESCE(SUM(spin_dots),0) AS spin_dots,
               COALESCE(SUM(spin_bnd),0) AS spin_bnd, COALESCE(SUM(spin_outs),0) AS spin_outs,
               COALESCE(SUM(pp_runs),0) AS pp_runs, COALESCE(SUM(pp_balls),0) AS pp_balls, COALESCE(SUM(pp_outs),0) AS pp_outs,
               COALESCE(SUM(mid_runs),0) AS mid_runs, COALESCE(SUM(mid_balls),0) AS mid_balls, COALESCE(SUM(mid_outs),0) AS mid_outs,
               COALESCE(SUM(death_runs),0) AS death_runs, COALESCE(SUM(death_balls),0) AS death_balls, COALESCE(SUM(death_outs),0) AS death_outs
        FROM scouting_bat_innings b WHERE {' AND '.join(conds)}"""), params).mappings().first()
    r = dict(r)
    out = {"innings": r["innings"], "runs": r["runs"], "balls": r["balls"], "dismissals": r["outs"],
           "strike_rate": round(100 * r["runs"] / r["balls"], 2) if r["balls"] else None,
           "average": div(r["runs"], r["outs"]), "balls_per_dismissal": div(r["balls"], r["outs"], 1),
           "dot_percentage": pct(r["dots"], r["balls"]), "boundary_percentage": pct(r["fours"] + r["sixes"], r["balls"]),
           "fours": r["fours"], "sixes": r["sixes"]}
    for s in ("pace", "spin"):
        b = r[f"{s}_balls"]
        out[s] = {"balls": b, "runs": r[f"{s}_runs"], "dismissals": r[f"{s}_outs"],
                  "strike_rate": round(100 * r[f"{s}_runs"] / b, 2) if b else None,
                  "balls_per_dismissal": div(b, r[f"{s}_outs"], 1), "dot_percentage": pct(r[f"{s}_dots"], b),
                  "boundary_percentage": pct(r[f"{s}_bnd"], b)}
    out["phases"] = [{"phase": PHASE_NAMES[p], "balls": r[f"{p}_balls"], "runs": r[f"{p}_runs"], "dismissals": r[f"{p}_outs"],
                      "strike_rate": round(100 * r[f"{p}_runs"] / r[f"{p}_balls"], 2) if r[f"{p}_balls"] else None}
                     for p in PHASES]
    out["_runs_sq"] = r["runs_sq"]
    return out


def _bowl_baseline(db: Session, bowler: str, f: dict, venue_id: Optional[str] = None) -> dict:
    params = {"p": bowler}
    conds = ["b.player_id = :p"] + _player_filters({**f, "venue_id": venue_id}, params, "b")
    if f.get("innings"):
        conds.append("b.innings_number = :inn"); params["inn"] = f["innings"]
    r = dict(db.execute(text(f"""
        SELECT COUNT(*) AS innings, COALESCE(SUM(legal_balls),0) AS balls, COALESCE(SUM(runs),0) AS runs,
               COALESCE(SUM(wickets),0) AS wickets, COALESCE(SUM(dots),0) AS dots, COALESCE(SUM(fours+sixes),0) AS bnd,
               COALESCE(SUM(pp_balls),0) AS pp_balls, COALESCE(SUM(pp_runs),0) AS pp_runs, COALESCE(SUM(pp_wkts),0) AS pp_wkts,
               COALESCE(SUM(mid_balls),0) AS mid_balls, COALESCE(SUM(mid_runs),0) AS mid_runs, COALESCE(SUM(mid_wkts),0) AS mid_wkts,
               COALESCE(SUM(death_balls),0) AS death_balls, COALESCE(SUM(death_runs),0) AS death_runs, COALESCE(SUM(death_wkts),0) AS death_wkts
        FROM scouting_bowl_innings b WHERE {' AND '.join(conds)}"""), params).mappings().first())
    return {"innings": r["innings"], "balls": r["balls"], "runs": r["runs"], "wickets": r["wickets"],
            "economy": rate(r["runs"], r["balls"]), "average": div(r["runs"], r["wickets"]),
            "strike_rate": div(r["balls"], r["wickets"], 1), "dot_percentage": pct(r["dots"], r["balls"]),
            "boundary_percentage": pct(r["bnd"], r["balls"]),
            "phases": [{"phase": PHASE_NAMES[p], "balls": r[f"{p}_balls"], "runs": r[f"{p}_runs"], "wickets": r[f"{p}_wkts"],
                        "economy": rate(r[f"{p}_runs"], r[f"{p}_balls"])} for p in PHASES]}


def _bowler_type(db: Session, bowler: str) -> dict:
    rows = db.execute(text("""
        SELECT DISTINCT ON (attribute_type) attribute_type, attribute_value FROM player_attributes
        WHERE player_id = :p AND attribute_type IN ('bowling_type', 'bowling_style', 'bowling_arm')
        ORDER BY attribute_type, CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC, updated_at DESC"""),
        {"p": bowler}).all()
    a = {t: v for t, v in rows}
    btype = (a.get("bowling_type") or "").lower()
    return {"type": btype if btype in ("pace", "spin") else None, "style": a.get("bowling_style"), "arm": a.get("bowling_arm")}


def _poisson_upper(k: int, lam: float) -> float:
    """P(X ≥ k) for X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    term, cdf = math.exp(-lam), 0.0
    for i in range(k):
        cdf += term
        term *= lam / (i + 1)
    return max(0.0, 1.0 - cdf)


def _poisson_lower(k: int, lam: float) -> float:
    """P(X ≤ k)."""
    term, cdf = math.exp(-lam), 0.0
    for i in range(k + 1):
        cdf += term
        term *= lam / (i + 1)
    return min(1.0, cdf)


def _player_insights(d: dict) -> List[dict]:
    out = []
    o = d["overall"]
    bn, wn = d["batter"]["name"], d["bowler"]["name"]
    btype = d["bowler"]["type"]
    base = (d.get("context") or {}).get("batter_vs_type")
    if o["balls"] < 6:
        return out
    # 1. Dismissal frequency vs the batter's usual rate against this bowling type.
    if base and base.get("balls_per_dismissal") and o["balls"] >= 12:
        expected = o["balls"] / base["balls_per_dismissal"]
        k = o["all_dismissals"]
        if k > expected:
            p = round(min(1.0, 2 * _poisson_upper(k, expected)), 4)
            if k >= 3 and k >= 1.5 * expected:
                out.append(_insight("dismissal", f"{bn} has struggled against {wn}: dismissed {k} times in {o['balls']} balls "
                                    f"(every {div(o['balls'], k, 1)} balls) vs every {base['balls_per_dismissal']} balls against {btype} overall.",
                                    f"Poisson test of {k} dismissals against {expected:.1f} expected from the batter's own rate vs {btype} "
                                    f"under the same filters: {_sig_text(p)}.", o["balls"], "neg", p, unit="balls"))
        elif expected >= 2:
            p = round(min(1.0, 2 * _poisson_lower(k, expected)), 4)
            if k <= 0.5 * expected:
                out.append(_insight("dismissal", f"{wn} has rarely dismissed {bn}: {k} dismissal{'s' if k != 1 else ''} in {o['balls']} balls, "
                                    f"where {expected:.1f} would be expected from the batter's rate against {btype}.",
                                    f"Poisson test vs the batter's balls-per-dismissal against {btype} ({base['balls_per_dismissal']}): {_sig_text(p)}.",
                                    o["balls"], "pos", p, unit="balls"))
    # 2. Scoring rate vs baseline.
    if base and base.get("strike_rate") and o["balls"] >= 30:
        n = o["balls"]
        mean = o["runs"] / n
        var = max(1e-9, o["_runs_sq"] / n - mean * mean)
        z = (mean - base["strike_rate"] / 100) / math.sqrt(var / n)
        p = round(math.erfc(abs(z) / math.sqrt(2)), 4)
        diff = (o["strike_rate"] or 0) - base["strike_rate"]
        if abs(diff) >= 15:
            out.append(_insight("strike_rate", f"{bn} scores {'faster' if diff > 0 else 'slower'} against {wn} (SR {o['strike_rate']}) "
                                f"than against {btype} bowling overall (SR {base['strike_rate']}).",
                                f"z-test on runs per ball ({n} balls, per-ball s.d. {math.sqrt(var):.2f}) vs the batter's {btype} baseline: {_sig_text(p)}.",
                                n, "pos" if diff > 0 else "neg", p, unit="balls"))
    if base and base.get("dot_percentage") is not None and o["balls"] >= 30 and o["dot_percentage"] is not None:
        diff = o["dot_percentage"] - base["dot_percentage"]
        if abs(diff) >= 8:
            p = two_proportion_p(o["dots"], o["balls"], round(base["dot_percentage"] * base["balls"] / 100), base["balls"])
            out.append(_insight("dots", f"{wn} {'ties ' + bn + ' down' if diff > 0 else 'concedes fewer dots to ' + bn}: "
                                f"{o['dot_percentage']}% dot balls vs {base['dot_percentage']}% for {bn} against {btype} overall.",
                                f"Two-proportion z-test: {_sig_text(p)}.", o["balls"], "neg" if diff > 0 else "pos", p, unit="balls"))
    # 3. Dismissal method concentration.
    types = d["dismissals"]["by_type"]
    if d["dismissals"]["total"] >= 3:
        top, cnt = max(types.items(), key=lambda kv: kv[1])
        if cnt / d["dismissals"]["total"] >= 0.5:
            out.append(_insight("method", f"{cnt} of {d['dismissals']['total']} dismissals have been {top}.",
                                "Share of all dismissals of the batter on this bowler's deliveries (descriptive).",
                                d["dismissals"]["total"], "neutral", unit="dismissals"))
    # 4. Phase extremes.
    for fam in d["phases"]:
        ph = [p for p in fam["phases"] if p["balls"] >= 18 and p["strike_rate"] is not None]
        if len(ph) >= 2:
            hi, lo = max(ph, key=lambda p: p["strike_rate"]), min(ph, key=lambda p: p["strike_rate"])
            if hi["strike_rate"] - lo["strike_rate"] >= 30:
                out.append(_insight("phase", f"In {fam['family']} cricket {bn} scores at SR {hi['strike_rate']} against {wn} in the {hi['phase']} "
                                    f"but {lo['strike_rate']} in the {lo['phase']}.",
                                    f"Phase splits with ≥18 balls each ({hi['balls']} and {lo['balls']} balls). Descriptive.",
                                    min(hi["balls"], lo["balls"]), "neutral", unit="balls"))
    # 5. Recent form.
    rf = d["recent_form"]
    if rf["innings"] >= 3 and rf["balls"] >= 12 and o["strike_rate"] is not None and rf["strike_rate"] is not None:
        diff = rf["strike_rate"] - o["strike_rate"]
        if abs(diff) >= 20:
            out.append(_insight("form", f"Recent trend: in the last {rf['innings']} meetings {bn} has scored at SR {rf['strike_rate']}, "
                                f"{'above' if diff > 0 else 'below'} the matchup's overall {o['strike_rate']}.",
                                f"{rf['balls']} balls across the most recent {rf['innings']} innings; small window — indicative only, not a forecast.",
                                rf["balls"], "pos" if diff > 0 else "neg", unit="balls"))
    if o["balls"] < 30:
        out.append(_insight("sample", f"Only {o['balls']} balls between these players — every figure here is based on limited historical data.",
                            "Batter-vs-bowler records under ~30 balls are dominated by chance.", o["balls"], unit="balls"))
    return out


def player_matchup(db: Session, batter: str, bowler: str, f: dict) -> Optional[dict]:
    """Full batter-vs-bowler analysis. ``f``: format, competition, season, date_from, date_to,
    venue_id, innings, side (home|away|neutral for the batter), recent (last N matches)."""
    def build():
        players = {r.id: r.canonical_name for r in db.execute(text("SELECT id, canonical_name FROM players WHERE id IN (:a, :b)"), {"a": batter, "b": bowler})}
        if batter not in players or bowler not in players:
            return None
        params = {"batter": batter, "bowler": bowler}
        conds = _player_filters(f, params)
        if f.get("innings"):
            conds.append("mi.innings_number = :inn"); params["inn"] = f["innings"]
        rows = db.execute(text(_PAIR_SQL.format(where="".join(f" AND {c}" for c in conds))), params).all()
        # Home/away for the batter's side (evidence-based, per format).
        homes_by_fmt = {}

        def side_of(r) -> str:
            fmt = r.match_format
            if fmt not in homes_by_fmt:
                homes_by_fmt[fmt] = home_ground_map(db, fmt)
            return venue_side(r._mapping, r.batting_team_id, homes_by_fmt[fmt])[0]
        sides = {}
        for r in rows:
            if r.match_id not in sides:
                sides[r.match_id] = side_of(r)
        if f.get("side") in SIDES:
            rows = [r for r in rows if sides[r.match_id] == f["side"]]
        match_order = list(dict.fromkeys(r.match_id for r in rows))
        if f.get("recent"):
            keep = set(match_order[-int(f["recent"]):])
            rows = [r for r in rows if r.match_id in keep]
            match_order = [m for m in match_order if m in keep]
        overall = _agg(rows)
        btype = _bowler_type(db, bowler)

        # Scoring distribution (balls faced only).
        faced = [r for r in rows if r.faced]
        dist = Counter()
        for r in faced:
            if r.b6:
                dist["6"] += 1
            elif r.b4:
                dist["4"] += 1
            elif r.batter_runs == 0:
                dist["0"] += 1
            elif r.batter_runs in (1, 2, 3):
                dist[str(r.batter_runs)] += 1
            else:
                dist["other"] += 1  # e.g. all-run 4s, 5s
        scoring = [{"label": k, "balls": dist[k], "percentage": pct(dist[k], len(faced)),
                    "runs": sum(r.batter_runs for r in faced if (k == "6" and r.b6) or (k == "4" and r.b4) or
                                (k not in ("4", "6", "other") and not r.b4 and not r.b6 and str(r.batter_runs) == k) or
                                (k == "other" and not r.b4 and not r.b6 and r.batter_runs not in (0, 1, 2, 3)))}
                   for k in ("0", "1", "2", "3", "4", "6", "other")]

        # Dismissals.
        outs = [r for r in rows if r.out]
        by_type = Counter(r.dismissal_type for r in outs)
        dismissals = {"total": len(outs), "bowler_credited": sum(1 for r in outs if r.bowler_wicket),
                      "not_credited": sum(1 for r in outs if not r.bowler_wicket), "by_type": dict(by_type),
                      "events": [{"match_id": r.match_id, "date": str(r.start_date), "type": r.dismissal_type,
                                  "credited": r.bowler_wicket, "over": f"{r.over_number}.{r.delivery_sequence}",
                                  "phase": r.phase} for r in reversed(outs)][:20]}

        # Phases per phase-compatible family.
        phases = []
        for fam in ("T20", "ODI"):
            fr = [r for r in rows if FAMILY.get(r.match_format) == fam]
            if not fr:
                continue
            bp = _group(fr, lambda r: r.phase)
            bo = _group(fr, lambda r: r.over_number)
            overs = [{"over": o + 1, **{k: v for k, v in _agg(bo[o]).items() if k in ("balls", "runs", "dismissals", "strike_rate", "dots", "fours", "sixes")}}
                     for o in sorted(bo)]
            phases.append({"family": fam, "balls": sum(1 for r in fr if r.faced), "overs": overs,
                           "phases": [{"phase": p, **{k: v for k, v in _agg(bp.get(p, [])).items() if not k.startswith("_")}}
                                      for p in ("powerplay", "middle", "death")]})

        def split(key, label_key):
            g = _group(rows, key)
            res = []
            for k, rs in g.items():
                a = {kk: vv for kk, vv in _agg(rs).items() if not kk.startswith("_")}
                res.append({label_key: k, "matches": len({r.match_id for r in rs}), **a,
                            "last_date": str(max(r.start_date for r in rs)),
                            "last_match_id": max(rs, key=lambda r: r.start_date).match_id})
            return res
        seasons = sorted(split(lambda r: r.season, "season"), key=lambda x: x["season"])
        years = sorted(split(lambda r: r.start_date.year, "year"), key=lambda x: x["year"])
        comps = sorted(split(lambda r: r.competition or "Unknown", "competition"), key=lambda x: -x["balls"])
        formats = sorted(split(lambda r: r.match_format, "format"), key=lambda x: -x["balls"])
        innings = sorted(split(lambda r: r.innings_number, "innings"), key=lambda x: x["innings"])
        venues = sorted(split(lambda r: r.venue_id, "venue_id"), key=lambda x: -x["balls"])
        vnames = {r.venue_id: (r.venue, r.city) for r in rows}
        for v in venues:
            v["venue"], v["city"] = vnames.get(v["venue_id"], (None, None))
        side_rows = sorted(split(lambda r: sides[r.match_id], "side"), key=lambda x: SIDES.index(x["side"]) if x["side"] in SIDES else 9)

        # Match-by-match (one row per innings).
        per_inn = _group(rows, lambda r: (r.match_id, r.innings_number))
        by_match = []
        for (mid, inn), rs in per_inn.items():
            r0 = rs[0]
            a = {k: v for k, v in _agg(rs).items() if not k.startswith("_")}
            bat_team = r0.team1 if r0.batting_team_id == r0.team1_id else r0.team2
            bowl_team = r0.team2 if r0.batting_team_id == r0.team1_id else r0.team1
            out_r = next((x for x in rs if x.out), None)
            by_match.append({"match_id": mid, "date": str(r0.start_date), "season": r0.season, "format": r0.match_format,
                             "competition": r0.competition, "venue": r0.venue, "venue_id": r0.venue_id, "innings": inn,
                             "batter_team": bat_team, "bowler_team": bowl_team, "side": sides[mid],
                             "batter_team_won": (r0.winner_id == r0.batting_team_id) if r0.winner_id else None,
                             "dismissal": out_r.dismissal_type if out_r else None,
                             "dismissal_credited": bool(out_r and out_r.bowler_wicket), **a})
        by_match.sort(key=lambda x: (x["date"], x["innings"]), reverse=True)

        # Recent form: last 5 innings vs the pair's overall.
        last = by_match[:5]
        rb = sum(x["balls"] for x in last)
        rr = sum(x["runs"] for x in last)
        recent_form = {"innings": len(last), "balls": rb, "runs": rr, "strike_rate": round(100 * rr / rb, 2) if rb else None,
                       "dismissals": sum(x["dismissals"] for x in last), "rows": last}
        # Cumulative trend (chronological).
        cum, cb, cr, co = [], 0, 0, 0
        for x in reversed(by_match):
            cb += x["balls"]; cr += x["runs"]; co += x["dismissals"]
            cum.append({"date": x["date"], "match_id": x["match_id"], "balls": cb, "runs": cr, "dismissals": co,
                        "strike_rate": round(100 * cr / cb, 2) if cb else None, "innings_strike_rate": x["strike_rate"]})

        # Context baselines (same format/competition/season/date/venue/innings filters).
        base_f = {k: f.get(k) for k in ("format", "competition", "season", "date_from", "date_to", "innings")}
        # Without a format filter, compare like with like: only the formats in which the pair actually met.
        base_f["formats"] = sorted({r.match_format for r in rows}) or ["__none__"]
        bat_all = _bat_baseline(db, batter, base_f)
        context = {"batter_overall": {k: v for k, v in bat_all.items() if not k.startswith("_")},
                   "bowler_overall": _bowl_baseline(db, bowler, base_f),
                   "batter_vs_type": bat_all.get(btype["type"]) if btype["type"] else None,
                   "baseline_formats": base_f["formats"] if not f.get("format") else [f["format"]],
                   "note": "Baselines use the same formats (those in which the pair met, unless one is chosen), competition, season, date-range and innings filters; "
                           "home/away and recent-encounter filters apply to the head-to-head only."}
        if f.get("venue_id"):
            vrow = db.execute(text("SELECT id, canonical_name, city, country FROM venues WHERE id = :v"), {"v": f["venue_id"]}).mappings().first()
            bv = _bat_baseline(db, batter, base_f, f["venue_id"])
            context["venue"] = {"venue": dict(vrow) if vrow else None,
                                "batter": {k: v for k, v in bv.items() if not k.startswith("_")},
                                "bowler": _bowl_baseline(db, bowler, base_f, f["venue_id"])}
        d = {"batter": {"id": batter, "name": players[batter]},
             "bowler": {"id": bowler, "name": players[bowler], **btype},
             "overall": overall, "matches": len(match_order), "innings": len(per_inn),
             "first_met": by_match[-1]["date"] if by_match else None, "last_met": by_match[0]["date"] if by_match else None,
             "scoring_distribution": scoring, "dismissals": dismissals, "phases": phases,
             "seasons": seasons, "years": years, "competitions": comps, "formats": formats, "innings_split": innings,
             "venues": venues, "home_away": side_rows, "by_match": by_match, "recent_form": recent_form,
             "cumulative": cum, "context": context,
             "formats_mixed": len({x["format"] for x in formats}) > 1,
             "notes": ["Balls faced exclude wides; no-balls count as balls faced but not legal deliveries.",
                       "Average and balls-per-dismissal use bowler-credited dismissals; run outs while facing the bowler are listed separately.",
                       "Bowler economy uses runs conceded (byes, leg-byes and penalties excluded) per legal over.",
                       "Super-over deliveries are excluded."]}
        d["insights"] = _player_insights({**d, "overall": overall})
        d["overall"] = {k: v for k, v in overall.items() if not k.startswith("_")}
        return d
    key = tuple(f.get(k) for k in ("format", "competition", "season", "date_from", "date_to", "venue_id", "innings", "side", "recent"))
    return cached(("player-matchup", batter, bowler) + key, build)


def player_venues(db: Session, batter: str, bowler: str, fmt: Optional[str]) -> List[dict]:
    """Venues where either player has appeared (for the venue selector), most-used first."""
    params = {"a": batter, "b": bowler}
    cond = ""
    if fmt:
        cond = " AND match_format = :fmt"; params["fmt"] = fmt
    rows = db.execute(text(f"""
        SELECT v.id, v.canonical_name, v.city, COUNT(DISTINCT x.match_id) AS matches FROM (
            SELECT match_id, venue_id FROM scouting_bat_innings WHERE player_id = :a{cond}
            UNION ALL SELECT match_id, venue_id FROM scouting_bowl_innings WHERE player_id = :b{cond}) x
        JOIN venues v ON v.id = x.venue_id GROUP BY v.id, v.canonical_name, v.city ORDER BY matches DESC LIMIT 300"""), params).all()
    return [{"id": r.id, "name": r.canonical_name, "city": r.city, "matches": r.matches} for r in rows]


def team_venues(db: Session, a: str, b: str, scope: Scope) -> List[dict]:
    """Venues where either team has played under the scope, with head-to-head counts."""
    params = {"a": a, "b": b}
    where = scope.where(params)
    rows = db.execute(text(f"""
        SELECT v.id, v.canonical_name, v.city,
               COUNT(*) FILTER (WHERE (m.team1_id = :a AND m.team2_id = :b) OR (m.team1_id = :b AND m.team2_id = :a)) AS h2h,
               COUNT(*) AS matches
        FROM matches m JOIN venues v ON v.id = m.venue_id
        WHERE {where} AND (m.team1_id IN (:a, :b) OR m.team2_id IN (:a, :b))
        GROUP BY v.id, v.canonical_name, v.city ORDER BY h2h DESC, matches DESC LIMIT 300"""), params).all()
    return [{"id": r.id, "name": r.canonical_name, "city": r.city, "h2h": r.h2h, "matches": r.matches} for r in rows]


def team_options(db: Session, scope: Scope) -> List[dict]:
    params: dict = {}
    where = scope.where(params)
    rows = db.execute(text(f"""
        SELECT t.id, t.canonical_name, COUNT(*) AS matches
        FROM matches m CROSS JOIN LATERAL (VALUES (m.team1_id), (m.team2_id)) x(tid) JOIN teams t ON t.id = x.tid
        WHERE {where} GROUP BY t.id, t.canonical_name ORDER BY matches DESC"""), params).all()
    return [{"id": r.id, "name": r.canonical_name, "matches": r.matches} for r in rows]


def opponents(db: Session, team_id: str, scope: Scope) -> List[dict]:
    params = {"t": team_id}
    where = scope.where(params)
    rows = db.execute(text(f"""
        SELECT t.id, t.canonical_name, COUNT(*) AS matches FROM matches m
        JOIN teams t ON t.id = CASE WHEN m.team1_id = :t THEN m.team2_id ELSE m.team1_id END
        WHERE {where} AND :t IN (m.team1_id, m.team2_id) GROUP BY t.id, t.canonical_name ORDER BY matches DESC"""), params).all()
    return [{"id": r.id, "name": r.canonical_name, "matches": r.matches} for r in rows]
