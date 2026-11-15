"""Team Analytics: "How well does this team perform, and under what conditions?"

All values derive from ``competition_common.load_matches`` (matches + persisted
innings totals). See that module for result, completeness and home/away rules.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.competition_common import (
    MIN_SAMPLE, fmt_p, PHASES, PHASE_NAMES, Scope, avg, cached, div, format_baseline, histogram, home_ground_map,
    load_matches, margin_text, med, pace_spin, pct, proportion, rate, score_bin_width, summarise_styles,
    team_result, two_proportion_p, venue_side,
)

SIDES = ("home", "away", "neutral", "unclassified")


# ----------------------------------------------------------------- building blocks

def record(matches: List[dict], team_id: str) -> dict:
    c = defaultdict(int)
    for m in matches:
        c[team_result(m, team_id)] += 1
    decided = c["won"] + c["lost"]
    return {"matches": len(matches), "won": c["won"], "lost": c["lost"], "tied": c["tie"], "drawn": c["draw"],
            "no_result": c["no_result"], "unknown": c["unknown"], "decided": decided,
            "win_percentage": pct(c["won"], decided), "win": proportion(c["won"], decided)}


def _batting_innings(matches, team_id):
    return [i for m in matches for i in m["innings"] if i["batting_team_id"] == team_id]


def _bowling_innings(matches, team_id):
    return [i for m in matches for i in m["innings"] if i["bowling_team_id"] == team_id]


def innings_block(inns: List[dict]) -> dict:
    """Scoring summary for a set of innings (one side's batting or its opponents')."""
    comp = [i for i in inns if i["complete"]]
    hi = max(inns, key=lambda i: i["runs"], default=None)
    lo = min((i for i in inns if i["finished"]), key=lambda i: i["runs"], default=None)
    runs, balls = sum(i["runs"] for i in inns), sum(i["legal_balls"] for i in inns)
    wk = sum(i["wickets"] for i in inns)
    bnd = sum(i["fours"] + i["sixes"] for i in inns)
    return {
        "innings": len(inns), "complete_innings": len(comp),
        "average_score": avg([i["runs"] for i in comp]), "median_score": med([i["runs"] for i in comp]),
        "run_rate": rate(runs, balls), "runs_per_wicket": div(runs, wk),
        "balls_per_wicket": div(balls, wk, 1),
        "wickets_per_innings": div(sum(i["wickets"] for i in comp), len(comp)),
        "boundary_percentage": pct(bnd, balls), "dot_percentage": pct(sum(i["dots"] for i in inns), balls),
        "boundary_run_percentage": pct(sum(4 * i["fours"] + 6 * i["sixes"] for i in inns), runs),
        "fours_per_innings": div(sum(i["fours"] for i in comp), len(comp)),
        "sixes_per_innings": div(sum(i["sixes"] for i in comp), len(comp)),
        "all_out_percentage": pct(sum(1 for i in comp if i["all_out"]), len(comp)),
        "highest": hi["runs"] if hi else None, "highest_match_id": hi.get("match_id") if hi else None,
        "lowest": lo["runs"] if lo else None, "lowest_match_id": lo.get("match_id") if lo else None,
    }


def phase_block(inns: List[dict], baseline: Optional[dict] = None) -> List[dict]:
    out = []
    for p in PHASES:
        used = [i for i in inns if i[f"{p}_balls"]]
        runs, balls = sum(i[f"{p}_runs"] for i in used), sum(i[f"{p}_balls"] for i in used)
        wk = sum(i[f"{p}_wkts"] for i in used)
        rr = rate(runs, balls)
        base = (baseline or {}).get(PHASE_NAMES[p], {})
        out.append({"phase": PHASE_NAMES[p], "innings": len(used), "balls": balls, "runs": runs, "wickets": wk,
                    "average_runs": div(runs, len(used), 1), "run_rate": rr,
                    "wickets_per_innings": div(wk, len(used)), "runs_per_wicket": div(runs, wk),
                    "boundary_percentage": pct(sum(i[f"{p}_bnd"] for i in used), balls),
                    "baseline_run_rate": base.get("run_rate"),
                    "run_rate_delta": round(rr - base["run_rate"], 2) if rr is not None and base.get("run_rate") is not None else None})
    return out


def order_split(matches: List[dict], team_id: str) -> dict:
    """Batting-first vs chasing records (limited overs: innings 1 vs 2)."""
    bf = [m for m in matches if m["first_batting_id"] == team_id]
    ch = [m for m in matches if m["first_batting_id"] and m["first_batting_id"] != team_id]
    return {"batting_first": record(bf, team_id), "chasing": record(ch, team_id)}


def side_split(matches: List[dict], team_id: str, limited: bool) -> dict:
    bat, bowl = _batting_innings(matches, team_id), _bowling_innings(matches, team_id)
    out = {"record": record(matches, team_id), "batting": innings_block(bat), "bowling": innings_block(bowl)}
    if limited:
        out["order"] = order_split(matches, team_id)
    return out


def chase_defence(matches: List[dict], team_id: str) -> dict:
    # Complete (non-reduced) matches only, so targets are the real first-innings totals, not DLS revisions.
    chases = [m["chase"] for m in matches if m["complete"] and m["chase"] and m["chase"]["chasing_id"] == team_id and m["chase"]["won"] is not None]
    defences = [m["chase"] for m in matches if m["complete"] and m["chase"] and m["chase"]["defending_id"] == team_id and m["chase"]["won"] is not None]
    won_ch = [c for c in chases if c["won"]]
    lost_ch = [c for c in chases if not c["won"]]
    held = [c for c in defences if not c["won"]]
    breached = [c for c in defences if c["won"]]
    return {
        "chases": {"attempts": len(chases), "successful": len(won_ch), "success": proportion(len(won_ch), len(chases)),
                   "average_successful_target": avg([c["target"] for c in won_ch]),
                   "highest_successful_target": max((c["target"] for c in won_ch), default=None),
                   "highest_successful_target_match_id": max(won_ch, key=lambda c: c["target"])["match_id"] if won_ch else None,
                   "average_failed_target": avg([c["target"] for c in lost_ch]),
                   "average_balls_remaining_in_wins": avg([c["balls_remaining"] for c in won_ch if c["balls_remaining"] is not None]),
                   "average_wickets_in_hand_in_wins": avg([c["wickets_in_hand"] for c in won_ch])},
        "defences": {"attempts": len(defences), "successful": len(held), "success": proportion(len(held), len(defences)),
                     "average_defended_total": avg([c["target"] - 1 for c in held]),
                     "lowest_defended_total": min((c["target"] - 1 for c in held), default=None),
                     "lowest_defended_total_match_id": min(held, key=lambda c: c["target"])["match_id"] if held else None,
                     "average_breached_total": avg([c["target"] - 1 for c in breached])},
    }


def wicket_distribution(inns: List[dict]) -> List[dict]:
    comp = [i for i in inns if i["complete"]]
    return [{"wickets": w, "innings": sum(1 for i in comp if min(i["wickets"], 10) == w)} for w in range(11)]


def season_rows(matches: List[dict], team_id: str) -> List[dict]:
    by = defaultdict(list)
    for m in matches:
        by[m["season"]].append(m)
    out = []
    for season in sorted(by):
        ms = by[season]
        rec = record(ms, team_id)
        bat, bowl = innings_block(_batting_innings(ms, team_id)), innings_block(_bowling_innings(ms, team_id))
        out.append({"season": season, **{k: rec[k] for k in ("matches", "won", "lost", "tied", "drawn", "no_result", "win_percentage")},
                    "run_rate": bat["run_rate"], "economy": bowl["run_rate"], "average_score": bat["average_score"],
                    "average_conceded": bowl["average_score"], "batting_average": bat["runs_per_wicket"],
                    "bowling_average": bowl["runs_per_wicket"]})
    return out


def rolling_form(matches: List[dict], team_id: str, window: int = 10) -> List[dict]:
    decided = [m for m in matches if m["outcome"] == "decided"]
    out = []
    for idx in range(len(decided)):
        if idx + 1 < window:
            continue
        chunk = decided[idx + 1 - window: idx + 1]
        out.append({"date": str(decided[idx]["start_date"]), "match_index": idx + 1, "match_id": decided[idx]["id"],
                    "win_percentage": pct(sum(1 for m in chunk if m["winner_id"] == team_id), window)})
    return out


def opposition_table(matches: List[dict], team_id: str) -> List[dict]:
    by = defaultdict(list)
    for m in matches:
        opp = m["team2_id"] if m["team1_id"] == team_id else m["team1_id"]
        by[opp].append(m)
    out = []
    for opp, ms in by.items():
        name = ms[0]["team2"] if ms[0]["team1_id"] == team_id else ms[0]["team1"]
        rec = record(ms, team_id)
        bat, bowl = innings_block(_batting_innings(ms, team_id)), innings_block(_bowling_innings(ms, team_id))
        out.append({"team_id": opp, "team": name, **{k: rec[k] for k in ("matches", "won", "lost", "tied", "drawn", "no_result", "win_percentage")},
                    "average_score": bat["average_score"], "average_conceded": bowl["average_score"],
                    "run_rate": bat["run_rate"], "economy": bowl["run_rate"], "last_played": str(ms[-1]["start_date"]),
                    "last_match_id": ms[-1]["id"]})
    return sorted(out, key=lambda r: (-r["matches"], r["team"] or ""))


def match_row(m: dict, team_id: str) -> dict:
    opp_is_2 = m["team1_id"] == team_id
    ours = next((i for i in m["innings"] if i["batting_team_id"] == team_id), None)
    theirs = next((i for i in m["innings"] if i["bowling_team_id"] == team_id), None)
    return {"match_id": m["id"], "date": str(m["start_date"]), "opponent": m["team2"] if opp_is_2 else m["team1"],
            "opponent_id": m["team2_id"] if opp_is_2 else m["team1_id"], "venue": m["venue"], "venue_id": m["venue_id"],
            "competition": m["competition"], "result": team_result(m, team_id), "margin": margin_text(m),
            "batted_first": m["first_batting_id"] == team_id if m["first_batting_id"] else None,
            "score": f"{ours['runs']}/{ours['wickets']}" if ours else None,
            "opponent_score": f"{theirs['runs']}/{theirs['wickets']}" if theirs else None,
            "close": m["close"], "reduced": m["reduced"]}


def suppression(matches: List[dict], team_id: str, team_rr: Dict[str, Optional[float]]) -> dict:
    """Opponents' run rate against this team vs those opponents' own run rate across the same filters."""
    actual_runs = actual_balls = expected = 0.0
    for m in matches:
        for i in m["innings"]:
            if i["bowling_team_id"] != team_id or not i["legal_balls"]:
                continue
            opp_rr = team_rr.get(i["batting_team_id"])
            if opp_rr is None:
                continue
            actual_runs += i["runs"]; actual_balls += i["legal_balls"]
            expected += opp_rr * i["legal_balls"] / 6
    actual_rr = rate(actual_runs, actual_balls)
    exp_rr = rate(expected, actual_balls)
    return {"opponent_run_rate_against": actual_rr, "opponent_usual_run_rate": exp_rr,
            "suppression_percentage": round(100 * (expected - actual_runs) / expected, 1) if expected else None,
            "balls": int(actual_balls),
            "note": "Positive = opponents scored slower against this team than they did on average (same filters)."}


# ---------------------------------------------------------------------- insights

def _insights(p: dict, limited: bool) -> List[dict]:
    out = []
    ha = p["home_away"]["sides"]
    h, a = ha["home"]["record"], ha["away"]["record"]
    if h["decided"] >= MIN_SAMPLE and a["decided"] >= MIN_SAMPLE:
        diff = (h["win_percentage"] or 0) - (a["win_percentage"] or 0)
        pval = two_proportion_p(h["won"], h["decided"], a["won"], a["decided"])
        sig = pval is not None and pval < 0.05
        out.append({"tone": "pos" if diff > 0 else "neg" if diff < 0 else "neutral", "kind": "home_away",
                    "text": (f"Wins {h['win_percentage']}% at home (n={h['decided']}) vs {a['win_percentage']}% away (n={a['decided']}): "
                             + (f"a {abs(diff):.1f}-point gap that is statistically significant ({fmt_p(pval)})." if sig
                                else f"a {abs(diff):.1f}-point gap that is within normal variation ({fmt_p(pval)}).")),
                    "significant": sig})
    elif h["decided"] or a["decided"]:
        out.append({"tone": "neutral", "kind": "home_away", "text": f"Home/away sample is small (home n={h['decided']}, away n={a['decided']} decided); no home-advantage conclusion drawn."})
    if limited:
        o = p["situations"]["order"]
        bf, ch = o["batting_first"], o["chasing"]
        if bf["decided"] >= MIN_SAMPLE and ch["decided"] >= MIN_SAMPLE:
            pval = two_proportion_p(bf["won"], bf["decided"], ch["won"], ch["decided"])
            better = "chasing" if (ch["win_percentage"] or 0) > (bf["win_percentage"] or 0) else "batting first"
            gap = abs((ch["win_percentage"] or 0) - (bf["win_percentage"] or 0))
            out.append({"tone": "neutral", "kind": "order", "significant": bool(pval is not None and pval < 0.05),
                        "text": f"Better when {better}: {bf['win_percentage']}% batting first (n={bf['decided']}) vs {ch['win_percentage']}% chasing (n={ch['decided']})"
                                + (f" — significant ({fmt_p(pval)})." if pval is not None and pval < 0.05 else f" — not significant ({fmt_p(pval)}).")})
        for ph in p["batting"]["phases"]:
            if ph["run_rate_delta"] is not None and ph["balls"] >= 300 and abs(ph["run_rate_delta"]) >= 0.3:
                out.append({"tone": "pos" if ph["run_rate_delta"] > 0 else "neg", "kind": "phase",
                            "text": f"Batting in the {ph['phase']}: {ph['run_rate']} RPO vs format {ph['baseline_run_rate']} ({ph['run_rate_delta']:+.2f}, {ph['balls'] // 6} overs)."})
        for ph in p["bowling"]["phases"]:
            if ph["run_rate_delta"] is not None and ph["balls"] >= 300 and abs(ph["run_rate_delta"]) >= 0.3:
                out.append({"tone": "pos" if ph["run_rate_delta"] < 0 else "neg", "kind": "phase",
                            "text": f"Bowling in the {ph['phase']}: concedes {ph['run_rate']} RPO vs format {ph['baseline_run_rate']} ({ph['run_rate_delta']:+.2f}, {ph['balls'] // 6} overs)."})
        cl = p["situations"]["close"]
        if cl["record"]["decided"] >= MIN_SAMPLE:
            out.append({"tone": "pos" if (cl["record"]["win_percentage"] or 0) >= 55 else "neg" if (cl["record"]["win_percentage"] or 0) <= 45 else "neutral",
                        "kind": "close", "text": f"Close matches: {cl['record']['won']}–{cl['record']['lost']} ({cl['record']['win_percentage']}%, n={cl['record']['decided']})."})
    sup = p["bowling"]["suppression"]
    if sup["suppression_percentage"] is not None and sup["balls"] >= 600 and abs(sup["suppression_percentage"]) >= 4:
        out.append({"tone": "pos" if sup["suppression_percentage"] > 0 else "neg", "kind": "suppression",
                    "text": f"Opponents score {abs(sup['suppression_percentage'])}% {'slower' if sup['suppression_percentage'] > 0 else 'faster'} against this attack than their own average ({sup['opponent_run_rate_against']} vs {sup['opponent_usual_run_rate']} RPO)."})
    form = p["form"]["last10"]
    if len(form) >= 10 and p["overview"]["record"]["decided"] >= 20:
        recent = sum(1 for r in form if r["result"] == "won") / max(1, sum(1 for r in form if r["result"] in ("won", "lost")))
        overall = (p["overview"]["record"]["win_percentage"] or 0) / 100
        if abs(recent - overall) >= 0.2:
            out.append({"tone": "pos" if recent > overall else "neg", "kind": "form",
                        "text": f"Recent form {'above' if recent > overall else 'below'} long-run level: {round(100 * recent)}% of the last 10 decided vs {round(100 * overall)}% overall (small window — indicative only)."})
    return out


# ----------------------------------------------------------------------- profile

def team_profile(db: Session, team_id: str, scope: Scope, opponent_id: Optional[str] = None) -> Optional[dict]:
    def build():
        team = db.execute(text("SELECT id, canonical_name, country, country_confidence FROM teams WHERE id = :t"), {"t": team_id}).mappings().first()
        if not team:
            return None
        params = {"tid": team_id}
        extra = ":tid IN (m.team1_id, m.team2_id)"
        if opponent_id:
            extra += " AND :oid IN (m.team1_id, m.team2_id)"; params["oid"] = opponent_id
        matches = load_matches(db, scope, extra, params)
        base = format_baseline(db, scope)
        homes = home_ground_map(db, scope.format)
        limited = scope.limited
        bat, bowl = _batting_innings(matches, team_id), _bowling_innings(matches, team_id)

        # Home / away
        sides = {s: [] for s in SIDES}
        methods = defaultdict(int)
        for m in matches:
            side, method = venue_side(m, team_id, homes)
            m["_side"] = side
            sides[side].append(m)
            methods[method or "none"] += 1
        home_away = {"sides": {s: side_split(ms, team_id, limited) for s, ms in sides.items()},
                     "methods": dict(methods),
                     "method_note": ("Home/away is evidence-based: verified national-team country, or a franchise's home ground "
                                     "detected from fixture concentration in that tournament season. Matches without such evidence are "
                                     "'unclassified' and excluded from the comparison."),
                     "significance_p": None}
        h, a = home_away["sides"]["home"]["record"], home_away["sides"]["away"]["record"]
        home_away["significance_p"] = two_proportion_p(h["won"], h["decided"], a["won"], a["decided"])
        home_away["grounds"] = _ground_table(sides["home"], team_id)

        # Batting & bowling by innings number
        def by_inns(inns, n):
            return innings_block([i for i in inns if i["innings_number"] == n])
        batting = {"overall": innings_block(bat),
                   "first_innings": by_inns(bat, 1), "second_innings": by_inns(bat, 2),
                   "phases": phase_block(bat, base["phases"]) if limited else None,
                   "wicket_distribution": wicket_distribution(bat),
                   "score_distribution": {"bin_width": score_bin_width(scope.format),
                                          "scored": histogram([i["runs"] for i in bat if i["complete"]], score_bin_width(scope.format)),
                                          "conceded": histogram([i["runs"] for i in bowl if i["complete"]], score_bin_width(scope.format))}}
        if not limited:
            batting["by_innings"] = [{"innings": n, **by_inns(bat, n)} for n in (1, 2, 3, 4)]
        team_styles = pace_spin(db, scope, "b.team_id = :tid AND :tid IN (m.team1_id, m.team2_id)" + (" AND :oid IN (m.team1_id, m.team2_id)" if opponent_id else ""), params)
        bowling = {"overall": innings_block(bowl),
                   "defending": by_inns(bowl, 2), "bowling_first": by_inns(bowl, 1),
                   "phases": phase_block(bowl, base["phases"]) if limited else None,
                   "pace_spin": summarise_styles(team_styles, base["pace_spin"]),
                   "suppression": suppression(matches, team_id, base["team_run_rate"])}
        if bowling["overall"]["balls_per_wicket"] is not None:
            bowling["overall"]["strike_rate"] = bowling["overall"]["balls_per_wicket"]

        rec = record(matches, team_id)
        close = [m for m in matches if m["close"]]
        situations = {"close": {"record": record(close, team_id),
                                "definition": "Tie, or decided by ≤{0} runs, ≤2 wickets, or a chase won with ≤{1} balls left.".format(*({"T20": (10, 6), "T20I": (10, 6)}.get(scope.format, (20, 12))))
                                if limited else "Ties only (no margin thresholds for multi-day cricket)."},
                      "opposition": opposition_table(matches, team_id)}
        if limited:
            situations["order"] = order_split(matches, team_id)
            situations.update(chase_defence(matches, team_id))
            situations["order_by_side"] = {s: order_split(sides[s], team_id) for s in ("home", "away")}
        last = [match_row(m, team_id) for m in reversed(matches[-10:])]
        decided_last = [r for r in last if r["result"] in ("won", "lost")]
        profile = {
            "team": {"id": team["id"], "name": team["canonical_name"],
                     "country": team["country"] if team["country_confidence"] == "high" else None},
            "scope": {**{k: v for k, v in zip(("format", "gender", "competition", "season", "start_year", "end_year"), scope.key())},
                      "opponent_id": opponent_id},
            "limited_overs": limited,
            "overview": {"record": rec, "batting": batting["overall"], "bowling": bowling["overall"],
                         "average_first_innings_score": batting["first_innings"]["average_score"],
                         "average_second_innings_score": batting["second_innings"]["average_score"],
                         "first_played": str(matches[0]["start_date"]) if matches else None,
                         "last_played": str(matches[-1]["start_date"]) if matches else None,
                         "excluded_incomplete_matches": sum(1 for m in matches if not m["complete"]),
                         "reduced_matches": sum(1 for m in matches if m["reduced"]),
                         "super_over_ties": sum(1 for m in matches if m["outcome"] == "tie" and m["has_super_over"])},
            "home_away": home_away,
            "batting": batting,
            "bowling": bowling,
            "situations": situations,
            "trends": {"seasons": season_rows(matches, team_id), "rolling": rolling_form(matches, team_id)},
            "form": {"last10": last, "last10_record": f"{sum(1 for r in decided_last if r['result'] == 'won')}W–{sum(1 for r in decided_last if r['result'] == 'lost')}L"},
            "baseline": {k: base[k] for k in ("run_rate", "average_first_innings", "average_second_innings", "wickets_per_innings", "boundary_percentage", "phases")},
            "notes": [
                "Super-over innings are excluded from every scoring metric; a super-over tie stays a tie.",
                "Score averages, medians and lowest totals use complete innings only (no-result and reduced-overs matches excluded); results use every match.",
                "Win % = wins ÷ (wins + losses); ties, draws and no-results are shown separately.",
                "Format baseline = all teams in the same format and filters.",
            ],
        }
        profile["insights"] = _insights(profile, limited)
        return profile
    return cached(("team-profile", team_id, opponent_id) + scope.key(), build)


def _ground_table(matches, team_id):
    by = defaultdict(list)
    for m in matches:
        by[(m["venue_id"], m["venue"])].append(m)
    rows = []
    for (vid, name), ms in by.items():
        rec = record(ms, team_id)
        rows.append({"venue_id": vid, "venue": name, "matches": rec["matches"], "won": rec["won"], "lost": rec["lost"],
                     "win_percentage": rec["win_percentage"]})
    return sorted(rows, key=lambda r: -r["matches"])[:12]


def head_to_head(db: Session, a: str, b: str, scope: Scope) -> dict:
    matches = load_matches(db, scope, "((m.team1_id = :a AND m.team2_id = :b) OR (m.team1_id = :b AND m.team2_id = :a))", {"a": a, "b": b})
    ra, rb = record(matches, a), record(matches, b)
    return {"matches": len(matches), "a": ra, "b": rb,
            "a_batting": innings_block(_batting_innings(matches, a)), "b_batting": innings_block(_batting_innings(matches, b)),
            "recent": [match_row(m, a) for m in reversed(matches[-10:])]}


# --------------------------------------------------------------------- directory

def team_directory(db: Session, scope: Scope) -> List[dict]:
    def build():
        matches = load_matches(db, scope)
        homes = home_ground_map(db, scope.format)
        by = defaultdict(list)
        names = {}
        for m in matches:
            for tid, name in ((m["team1_id"], m["team1"]), (m["team2_id"], m["team2"])):
                if tid:
                    by[tid].append(m); names[tid] = name
        rows = []
        for tid, ms in by.items():
            rec = record(ms, tid)
            bat, bowl = innings_block(_batting_innings(ms, tid)), innings_block(_bowling_innings(ms, tid))
            home = [m for m in ms if venue_side(m, tid, homes)[0] == "home"]
            away = [m for m in ms if venue_side(m, tid, homes)[0] == "away"]
            rh, ra = record(home, tid), record(away, tid)
            row = {"team_id": tid, "team": names[tid], **{k: rec[k] for k in ("matches", "won", "lost", "tied", "drawn", "no_result", "decided", "win_percentage")},
                   "run_rate": bat["run_rate"], "economy": bowl["run_rate"], "average_score": bat["average_score"],
                   "net_run_rate": round(bat["run_rate"] - bowl["run_rate"], 2) if bat["run_rate"] is not None and bowl["run_rate"] is not None else None,
                   "home_decided": rh["decided"], "home_win_percentage": rh["win_percentage"],
                   "away_decided": ra["decided"], "away_win_percentage": ra["win_percentage"],
                   "last_played": str(ms[-1]["start_date"]), "last_match_id": ms[-1]["id"],
                   "form": [team_result(m, tid) for m in ms[-5:]][::-1],
                   "form_match_ids": [m["id"] for m in ms[-5:]][::-1]}
            if scope.limited:
                o = order_split(ms, tid)
                row["batting_first_win_percentage"] = o["batting_first"]["win_percentage"]
                row["chasing_win_percentage"] = o["chasing"]["win_percentage"]
            rows.append(row)
        return sorted(rows, key=lambda r: -r["matches"])
    return cached(("team-directory",) + scope.key(), build)
