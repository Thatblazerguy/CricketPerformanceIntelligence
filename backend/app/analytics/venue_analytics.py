"""Venue Analytics: "How does this ground influence the way cricket is played and won?"

Built on ``competition_common`` (see it for result/completeness rules). Every
figure is measured from stored matches; the only interpretive output is the
``inferred`` block of the conditions section, which is explicitly labelled as
an inference from scoring outcomes, never a pitch report.
"""
from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.competition_common import (
    MIN_SAMPLE, PHASES, PHASE_NAMES, Scope, avg, binomial_p, cached, div, fmt_p, format_baseline, histogram,
    load_matches, margin_text, med, pace_spin, pct, proportion, rate, score_bin_width, summarise_styles,
    team_result,
)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _first_scores(matches):
    return [m["first_innings"]["runs"] for m in matches if m["complete"] and m["first_innings"]]


def _second_scores(matches):
    return [m["second_innings"]["runs"] for m in matches if m["complete"] and m["second_innings"]]


def _all_innings(matches):
    return [i for m in matches for i in m["innings"]]


def overview(matches: List[dict], limited: bool) -> dict:
    inns = _all_innings(matches)
    comp = [i for i in inns if i["complete"]]
    balls = sum(i["legal_balls"] for i in inns)
    chases = [m["chase"] for m in matches if m["complete"] and m["chase"] and m["chase"]["won"] is not None]
    won_ch = [c for c in chases if c["won"]]
    held = [c for c in chases if not c["won"]]
    hi = max(inns, key=lambda i: i["runs"], default=None)
    finished = [i for i in inns if i["finished"]]
    lo = min(finished, key=lambda i: i["runs"], default=None)
    by_id = {i["innings_id"]: m for m in matches for i in m["innings"]}

    def rec(i):
        if not i:
            return None
        m = by_id[i["innings_id"]]
        team = m["team1"] if i["batting_team_id"] == m["team1_id"] else m["team2"]
        return {"runs": i["runs"], "wickets": i["wickets"], "team": team, "match_id": m["id"], "date": str(m["start_date"])}
    outcomes = defaultdict(int)
    for m in matches:
        outcomes[m["outcome"]] += 1
    return {
        "matches": len(matches), "outcomes": dict(outcomes),
        "first_played": str(matches[0]["start_date"]) if matches else None,
        "last_played": str(matches[-1]["start_date"]) if matches else None,
        "first_match_id": matches[0]["id"] if matches else None, "last_match_id": matches[-1]["id"] if matches else None,
        "average_first_innings": avg(_first_scores(matches)), "first_innings_sample": len(_first_scores(matches)),
        "average_second_innings": avg(_second_scores(matches)), "second_innings_sample": len(_second_scores(matches)),
        "highest_total": rec(hi), "lowest_total": rec(lo),
        "highest_successful_chase": max((c["runs"] for c in won_ch), default=None) if limited else None,
        "lowest_defended_total": min((c["target"] - 1 for c in held), default=None) if limited else None,
        "highest_successful_chase_match_id": max(won_ch, key=lambda c: c["runs"])["match_id"] if limited and won_ch else None,
        "lowest_defended_total_match_id": min(held, key=lambda c: c["target"])["match_id"] if limited and held else None,
        "wickets_per_innings": div(sum(i["wickets"] for i in comp), len(comp)),
        "run_rate": rate(sum(i["runs"] for i in inns), balls),
        "innings": len(inns), "complete_innings": len(comp),
        "excluded_incomplete_matches": sum(1 for m in matches if not m["complete"]),
        "super_over_ties": sum(1 for m in matches if m["outcome"] == "tie" and m["has_super_over"]),
    }


def toss_analysis(matches: List[dict], limited: bool) -> dict:
    tossed = [m for m in matches if m["toss_winner_id"] and m["toss_decision"] in ("bat", "field")]
    decided = [m for m in tossed if m["outcome"] == "decided"]
    tw_wins = sum(1 for m in decided if m["winner_id"] == m["toss_winner_id"])

    def choice(decision):
        ms = [m for m in decided if m["toss_decision"] == decision]
        k = sum(1 for m in ms if m["winner_id"] == m["toss_winner_id"])
        return {"chosen": sum(1 for m in tossed if m["toss_decision"] == decision),
                "chosen_percentage": pct(sum(1 for m in tossed if m["toss_decision"] == decision), len(tossed)),
                "decided": len(ms), "toss_winner_won": k, "win": proportion(k, len(ms)), "p_value": binomial_p(k, len(ms))}
    first = [m for m in matches if m["outcome"] == "decided" and m["first_batting_id"]]
    bf = sum(1 for m in first if m["winner_id"] == m["first_batting_id"])
    p = binomial_p(tw_wins, len(decided))
    bat, field = choice("bat"), choice("field")
    verdict, tone = _toss_verdict(tw_wins, len(decided), p)
    # Did the popular toss choice match what actually wins here?
    alignment = None
    if len(first) >= MIN_SAMPLE and tossed:
        favoured = "bat" if bf * 2 > len(first) else "field" if bf * 2 < len(first) else None
        popular = "bat" if bat["chosen"] > field["chosen"] else "field"
        if favoured:
            alignment = {"favoured_by_results": favoured, "most_chosen": popular, "aligned": favoured == popular}
    return {
        "tosses": len(tossed), "decided_after_toss": len(decided),
        "chose_bat": bat, "chose_field": field,
        "toss_winner_won": tw_wins, "toss_winner": proportion(tw_wins, len(decided)), "p_value": p,
        "batting_first_wins": bf, "chasing_wins": len(first) - bf,
        "batting_first": proportion(bf, len(first)), "chasing": proportion(len(first) - bf, len(first)),
        "batting_first_p_value": binomial_p(bf, len(first)),
        "verdict": verdict, "verdict_tone": tone, "alignment": alignment,
        "label_first": "Batting first" if limited else "Batting in innings 1",
        "label_second": "Chasing" if limited else "Fielding first",
        "method": "Toss advantage tested with an exact two-sided binomial test of toss-winner wins against 50% over decided matches; "
                  "ties, draws and no-results excluded. 95% intervals are Wilson score intervals.",
    }


def _toss_verdict(k, n, p):
    if n < MIN_SAMPLE:
        return f"Too few decided matches (n={n}) to assess the toss.", "neutral"
    share = round(100 * k / n, 1)
    if p is not None and p < 0.05:
        return (f"Measurable toss effect: toss winners won {share}% of {n} decided matches ({fmt_p(p)}).",
                "pos" if share > 50 else "neg")
    return f"No measurable toss advantage: toss winners won {share}% of {n} decided matches ({fmt_p(p)}).", "neutral"


def bat_first_vs_chase(matches: List[dict], fmt: str) -> dict:
    complete = [m for m in matches if m["complete"] and m["first_innings"]]
    first = _first_scores(matches)
    winning = [m["first_innings"]["runs"] for m in complete if m["outcome"] == "decided" and m["winner_id"] == m["first_batting_id"]]
    losing = [m["first_innings"]["runs"] for m in complete if m["outcome"] == "decided" and m["winner_id"] != m["first_batting_id"]]
    chases = [m["chase"] for m in complete if m["chase"] and m["chase"]["won"] is not None]
    won = [c for c in chases if c["won"]]
    decided = [m for m in matches if m["outcome"] == "decided" and m["first_batting_id"]]
    bf_wins = sum(1 for m in decided if m["winner_id"] == m["first_batting_id"])
    width = score_bin_width(fmt)
    start = None
    allv = first + _second_scores(matches)
    if allv:
        start = (min(allv) // width) * width
    f_bins = {b["bin_start"]: b["count"] for b in histogram(first, width, start)}
    s_bins = {b["bin_start"]: b["count"] for b in histogram(_second_scores(matches), width, start)}
    edges = sorted(set(f_bins) | set(s_bins))
    # Win rate when batting first, by first-innings score band ("par score" curve).
    bands = []
    for e in edges:
        ms = [m for m in complete if m["outcome"] == "decided" and e <= m["first_innings"]["runs"] < e + width]
        k = sum(1 for m in ms if m["winner_id"] == m["first_batting_id"])
        bands.append({"label": f"{int(e)}–{int(e + width - 1)}", "bin_start": e, "matches": len(ms), "batting_first_win_percentage": pct(k, len(ms))})
    return {
        "batting_first": {
            "average_score": avg(first), "median_score": med(first), "sample": len(first),
            "average_winning_total": avg(winning), "winning_sample": len(winning),
            "average_losing_total": avg(losing), "losing_sample": len(losing),
            "win": proportion(bf_wins, len(decided)), "successful_defences": bf_wins,
        },
        "chasing": {
            "average_score": avg(_second_scores(matches)), "sample": len(_second_scores(matches)),
            "success": proportion(len(won), len(chases)), "attempts": len(chases),
            "average_successful_target": avg([c["target"] for c in won]),
            "highest_successful_chase": max((c["runs"] for c in won), default=None),
            "lowest_successful_chase": min((c["runs"] for c in won), default=None),
            "highest_successful_chase_match_id": max(won, key=lambda c: c["runs"])["match_id"] if won else None,
            "lowest_successful_chase_match_id": min(won, key=lambda c: c["runs"])["match_id"] if won else None,
            "highest_target_chased": max((c["target"] for c in won), default=None),
            "average_wickets_in_hand": avg([c["wickets_in_hand"] for c in won]),
            "average_balls_remaining": avg([c["balls_remaining"] for c in won if c["balls_remaining"] is not None]),
            "wickets_in_hand_distribution": [{"wickets": w, "chases": sum(1 for c in won if c["wickets_in_hand"] == w)} for w in range(1, 11)],
            "completion_over_distribution": _over_distribution(won, fmt),
        },
        "score_distribution": {"bin_width": width, "bins": [{"label": f"{int(e)}–{int(e + width - 1)}", "bin_start": e,
                                                             "first_innings": f_bins.get(e, 0), "second_innings": s_bins.get(e, 0)} for e in edges]},
        "par_curve": bands,
        "note": "Complete matches only (no-result and reduced-overs matches excluded) so targets are genuine first-innings totals.",
    }


def _over_distribution(won, fmt):
    step = 2 if fmt in ("T20", "T20I") else 5
    top = 20 if fmt in ("T20", "T20I") else 50
    out = []
    for lo in range(1, top + 1, step):
        hi = min(top, lo + step - 1)
        out.append({"label": f"{lo}–{hi}", "chases": sum(1 for c in won if lo <= c["over_completed"] <= hi)})
    return out


def conditions(matches: List[dict], base: dict, styles: dict, limited: bool) -> dict:
    inns = _all_innings(matches)
    comp = [i for i in inns if i["complete"]]
    balls = sum(i["legal_balls"] for i in inns)
    runs = sum(i["runs"] for i in inns)
    measured = {
        "run_rate": rate(runs, balls), "baseline_run_rate": base["run_rate"],
        "wickets_per_innings": div(sum(i["wickets"] for i in comp), len(comp)), "baseline_wickets_per_innings": base["wickets_per_innings"],
        "boundary_percentage": pct(sum(i["fours"] + i["sixes"] for i in inns), balls), "baseline_boundary_percentage": base["boundary_percentage"],
        "fours_per_innings": div(sum(i["fours"] for i in comp), len(comp)),
        "sixes_per_innings": div(sum(i["sixes"] for i in comp), len(comp)), "baseline_sixes_per_innings": base["sixes_per_innings"],
        "balls_per_six": div(balls, sum(i["sixes"] for i in inns), 1),
        "dot_percentage": pct(sum(i["dots"] for i in inns), balls),
        "runs_per_wicket": div(runs, sum(i["wickets"] for i in inns)),
        "balls": balls, "innings": len(inns),
    }
    by_n = {}
    for n in (1, 2, 3, 4):
        xs = [i for i in inns if i["innings_number"] == n]
        if xs:
            c = [i for i in xs if i["complete"]]
            by_n[n] = {"innings": n, "sample": len(c), "average_score": avg([i["runs"] for i in c]),
                       "run_rate": rate(sum(i["runs"] for i in xs), sum(i["legal_balls"] for i in xs)),
                       "wickets_per_innings": div(sum(i["wickets"] for i in c), len(c))}
    phases = None
    if limited:
        phases = []
        for p in PHASES:
            for n in (1, 2):
                xs = [i for i in inns if i["innings_number"] == n and i[f"{p}_balls"]]
                b = sum(i[f"{p}_balls"] for i in xs)
                rr = rate(sum(i[f"{p}_runs"] for i in xs), b)
                br = base["phases"][PHASE_NAMES[p]]["run_rate"]
                phases.append({"phase": PHASE_NAMES[p], "innings": n, "sample": len(xs), "balls": b, "run_rate": rr,
                               "average_runs": div(sum(i[f"{p}_runs"] for i in xs), len(xs), 1),
                               "wickets_per_innings": div(sum(i[f"{p}_wkts"] for i in xs), len(xs)),
                               "boundary_percentage": pct(sum(i[f"{p}_bnd"] for i in xs), b),
                               "baseline_run_rate": br,
                               "run_rate_delta": round(rr - br, 2) if rr is not None and br is not None else None})
    return {"measured": measured, "by_innings": list(by_n.values()), "phases": phases, "pace_spin": styles,
            "inferred": _infer(measured, styles, len(matches), by_n)}


def _infer(meas, styles, n_matches, by_n):
    """Tendencies inferred from scoring outcomes, with the evidence and a confidence flag."""
    tags = []
    conf = "low" if n_matches < MIN_SAMPLE else "moderate" if n_matches < 30 else "high"
    rr, brr = meas["run_rate"], meas["baseline_run_rate"]
    if rr is not None and brr:
        idx = round(100 * rr / brr)
        if idx >= 105:
            tags.append({"tag": "Batting-friendly", "tone": "bat", "evidence": f"Run rate {rr} vs format {brr} (scoring index {idx})."})
        elif idx <= 95:
            tags.append({"tag": "Bowling-friendly", "tone": "bowl", "evidence": f"Run rate {rr} vs format {brr} (scoring index {idx})."})
        else:
            tags.append({"tag": "Neutral scoring", "tone": "neutral", "evidence": f"Run rate {rr} vs format {brr} (scoring index {idx})."})
    w, bw = meas["wickets_per_innings"], meas["baseline_wickets_per_innings"]
    if w is not None and bw and abs(w - bw) >= 0.5:
        tags.append({"tag": "Wicket-taking ground" if w > bw else "Wickets harder to take", "tone": "bowl" if w > bw else "bat",
                     "evidence": f"{w} wickets per innings vs format {bw}."})
    s, bs = meas["sixes_per_innings"], meas["baseline_sixes_per_innings"]
    if s is not None and bs and abs(s - bs) / bs >= 0.15:
        tags.append({"tag": "Six-hitting venue" if s > bs else "Fewer sixes", "tone": "bat" if s > bs else "bowl",
                     "evidence": f"{s} sixes per innings vs format {bs} (consistent with ground dimensions or conditions; not measured directly)."})
    st = {x["style"]: x for x in styles["styles"]}
    if st.get("spin") and st.get("pace") and min(st["spin"]["balls"], st["pace"]["balls"]) >= 600:
        sd, pd = st["spin"]["economy_delta"], st["pace"]["economy_delta"]
        if sd is not None and pd is not None and abs(sd - pd) >= 0.4:
            better = "spin" if sd < pd else "pace"
            tags.append({"tag": f"Favours {better} (relative to format)", "tone": "bowl",
                         "evidence": f"Spin economy {st['spin']['economy']} ({sd:+.2f} vs format spin), pace {st['pace']['economy']} ({pd:+.2f} vs format pace)."})
    if 1 in by_n and 2 in by_n and by_n[1]["average_score"] and by_n[2]["average_score"] and min(by_n[1]["sample"], by_n[2]["sample"]) >= MIN_SAMPLE:
        diff = round(by_n[1]["average_score"] - by_n[2]["average_score"], 1)
        if abs(diff) >= 10:
            tags.append({"tag": "Scoring drops in the second innings" if diff > 0 else "Scoring rises in the second innings",
                         "tone": "neutral", "evidence": f"Innings 1 averages {by_n[1]['average_score']} vs {by_n[2]['average_score']} in innings 2 ({diff:+} runs)."})
    return {"tags": tags, "confidence": conf,
            "disclaimer": "Inferred from match scoring outcomes only. CPI has no pitch, weather, dew or boundary-size data, "
                          "so these are tendencies in results, not statements about the surface."}


def trends(matches: List[dict], base: dict, limited: bool) -> dict:
    def summarise(ms):
        first = _first_scores(ms)
        decided = [m for m in ms if m["outcome"] == "decided" and m["first_batting_id"]]
        bf = sum(1 for m in decided if m["winner_id"] == m["first_batting_id"])
        inns = _all_innings(ms)
        return {"matches": len(ms), "average_first_innings": avg(first), "first_innings_sample": len(first),
                "average_second_innings": avg(_second_scores(ms)),
                "run_rate": rate(sum(i["runs"] for i in inns), sum(i["legal_balls"] for i in inns)),
                "batting_first_win_percentage": pct(bf, len(decided)), "decided": len(decided)}
    by_season, by_month, by_comp = defaultdict(list), defaultdict(list), defaultdict(list)
    for m in matches:
        by_season[m["season"]].append(m)
        by_month[m["start_date"].month].append(m)
        by_comp[m["competition"] or "Unknown competition"].append(m)
    teams = defaultdict(list)
    names = {}
    for m in matches:
        for tid, name in ((m["team1_id"], m["team1"]), (m["team2_id"], m["team2"])):
            if tid:
                teams[tid].append(m); names[tid] = name
    team_rows = []
    for tid, ms in teams.items():
        c = defaultdict(int)
        for m in ms:
            c[team_result(m, tid)] += 1
        scores = [i["runs"] for m in ms for i in m["innings"] if i["batting_team_id"] == tid and i["complete"]]
        team_rows.append({"team_id": tid, "team": names[tid], "matches": len(ms), "won": c["won"], "lost": c["lost"],
                          "other": len(ms) - c["won"] - c["lost"], "win_percentage": pct(c["won"], c["won"] + c["lost"]),
                          "average_score": avg(scores)})
    inns = _all_innings(matches)
    by_id = {i["innings_id"]: m for m in matches for i in m["innings"]}

    def inn_row(i):
        m = by_id[i["innings_id"]]
        return {"runs": i["runs"], "wickets": i["wickets"], "innings": i["innings_number"], "match_id": m["id"], "date": str(m["start_date"]),
                "team": m["team1"] if i["batting_team_id"] == m["team1_id"] else m["team2"],
                "opponent": m["team2"] if i["batting_team_id"] == m["team1_id"] else m["team1"]}
    first = _first_scores(matches)
    p25, p75 = base.get("first_innings_p25"), base.get("first_innings_p75")
    recent = []
    for m in reversed(matches[-10:]):
        recent.append({"match_id": m["id"], "date": str(m["start_date"]), "team1": m["team1"], "team2": m["team2"],
                       "first_innings": f"{m['first_innings']['runs']}/{m['first_innings']['wickets']}" if m["first_innings"] else None,
                       "second_innings": f"{m['second_innings']['runs']}/{m['second_innings']['wickets']}" if m["second_innings"] else None,
                       "winner": (m["team1"] if m["winner_id"] == m["team1_id"] else m["team2"]) if m["winner_id"] else None,
                       "margin": margin_text(m), "batting_first_won": (m["winner_id"] == m["first_batting_id"]) if m["outcome"] == "decided" else None,
                       "competition": m["competition"]})
    recent_summary = summarise(matches[-10:]) if matches else None
    return {
        "seasons": [{"season": s, **summarise(ms)} for s, ms in sorted(by_season.items())],
        "months": [{"month": MONTHS[k - 1], "month_number": k, **summarise(ms)} for k, ms in sorted(by_month.items())],
        "competitions": sorted([{"competition": c, **summarise(ms)} for c, ms in by_comp.items()], key=lambda r: -r["matches"]),
        "teams": sorted(team_rows, key=lambda r: -r["matches"]),
        "recent": recent, "recent_summary": recent_summary, "overall_summary": summarise(matches),
        "highest_totals": [inn_row(i) for i in sorted(inns, key=lambda i: -i["runs"])[:5]],
        "lowest_totals": [inn_row(i) for i in sorted([i for i in inns if i["finished"]], key=lambda i: i["runs"])[:5]],
        "scoring_bands": {
            "high_threshold": p75, "low_threshold": p25, "sample": len(first),
            "high_scoring": proportion(sum(1 for r in first if p75 is not None and r >= p75), len(first)),
            "low_scoring": proportion(sum(1 for r in first if p25 is not None and r <= p25), len(first)),
            "note": "High/low = first-innings total at or above the format's 75th / at or below its 25th percentile under the same filters "
                    "(≈25% each at a typical venue).",
        },
        "day_night": {"available": False, "reason": "Cricsheet match records carry no day/night or floodlight flag, so day vs night splits cannot be measured."},
    }


def _insights(p):
    out = []
    t = p["toss"]
    out.append({"tone": t["verdict_tone"], "kind": "toss", "text": t["verdict"]})
    bf = t["batting_first"]
    if bf["n"] >= MIN_SAMPLE:
        pv = t["batting_first_p_value"]
        lean = "batting first" if bf["value"] > 50 else "chasing" if bf["value"] < 50 else "neither side"
        sig = pv is not None and pv < 0.05
        out.append({"tone": "neutral", "kind": "order", "significant": sig,
                    "text": f"{t['label_first']} won {bf['value']}% of {bf['n']} decided matches — "
                            + (f"results genuinely lean toward {lean} ({fmt_p(pv)})." if sig else f"no significant lean ({fmt_p(pv)}).")})
    if t["alignment"] and not t["alignment"]["aligned"] and t["tosses"] >= MIN_SAMPLE:
        out.append({"tone": "neg", "kind": "toss", "text": f"Captains mostly choose to {t['alignment']['most_chosen']} here, yet results favour teams that {'bat first' if t['alignment']['favoured_by_results'] == 'bat' else 'chase'}."})
    for tag in p["conditions"]["inferred"]["tags"]:
        out.append({"tone": "neutral", "kind": "inferred", "text": f"{tag['tag']} (inferred): {tag['evidence']}"})
    r, o = p["trends"]["recent_summary"], p["trends"]["overall_summary"]
    if r and o and r["first_innings_sample"] >= 5 and r["average_first_innings"] and o["average_first_innings"] and p["overview"]["matches"] >= 20:
        d = round(r["average_first_innings"] - o["average_first_innings"], 1)
        if abs(d) >= 10:
            out.append({"tone": "neutral", "kind": "trend", "text": f"Recent first-innings scores are {'up' if d > 0 else 'down'} {abs(d)} runs on the venue average (last {r['first_innings_sample']} complete matches)."})
    return out


def venue_profile(db: Session, venue_id: str, scope: Scope, team_id: Optional[str] = None) -> Optional[dict]:
    def build():
        v = db.execute(text("SELECT id, canonical_name, city, country FROM venues WHERE id = :v"), {"v": venue_id}).mappings().first()
        if not v:
            return None
        params = {"vid": venue_id}
        extra = "m.venue_id = :vid"
        if team_id:
            extra += " AND :tid IN (m.team1_id, m.team2_id)"; params["tid"] = team_id
        matches = load_matches(db, scope, extra, params)
        base = format_baseline(db, scope)
        styles = summarise_styles(pace_spin(db, scope, extra, params), base["pace_spin"])
        limited = scope.limited
        p = {
            "venue": {"id": v["id"], "name": v["canonical_name"], "city": v["city"], "country": v["country"]},
            "scope": {**dict(zip(("format", "gender", "competition", "season", "start_year", "end_year"), scope.key())), "team_id": team_id},
            "limited_overs": limited,
            "overview": overview(matches, limited),
            "toss": toss_analysis(matches, limited),
            "batting_first_vs_chasing": bat_first_vs_chase(matches, scope.format) if limited else None,
            "conditions": conditions(matches, base, styles, limited),
            "trends": trends(matches, base, limited),
            "baseline": {k: base[k] for k in ("run_rate", "average_first_innings", "average_second_innings", "wickets_per_innings",
                                               "boundary_percentage", "sixes_per_innings", "batting_first_win_percentage",
                                               "toss_winner_win_percentage", "phases")},
            "notes": [
                "Super-over innings are excluded from all scoring metrics; super-over ties remain ties.",
                "Averages, medians, distributions and chase/defence records use complete matches only (no-result and reduced-overs excluded).",
                "Format baseline = every venue in the same format and filters.",
            ],
        }
        p["insights"] = _insights(p)
        return p
    return cached(("venue-profile", venue_id, team_id) + scope.key(), build)


def venue_directory(db: Session, scope: Scope, team_id: Optional[str] = None) -> List[dict]:
    def build():
        params, extra = {}, ""
        if team_id:
            extra, params = ":tid IN (m.team1_id, m.team2_id)", {"tid": team_id}
        matches = load_matches(db, scope, extra, params)
        styles = defaultdict(dict)
        for r in pace_spin(db, scope, extra, params, group_by="m.venue_id"):
            styles[r["venue_id"]][r["style"]] = r
        by = defaultdict(list)
        for m in matches:
            if m["venue_id"]:
                by[m["venue_id"]].append(m)
        rows = []
        for vid, ms in by.items():
            o = overview(ms, scope.limited)
            t = toss_analysis(ms, scope.limited)
            st = styles.get(vid, {})
            ps = {}
            for s in ("pace", "spin"):
                r = st.get(s)
                ps[f"{s}_economy"] = rate(int(r["runs"] or 0), int(r["balls"] or 0)) if r else None
                ps[f"{s}_strike_rate"] = div(int(r["balls"] or 0), int(r["wickets"] or 0), 1) if r else None
            classified = sum(int(st[s]["wickets"] or 0) for s in ("pace", "spin") if s in st)
            rows.append({"venue_id": vid, "venue": ms[0]["venue"], "city": ms[0]["city"], "country": ms[0]["venue_country"],
                         "matches": len(ms), "average_first_innings": o["average_first_innings"], "first_innings_sample": o["first_innings_sample"],
                         "average_second_innings": o["average_second_innings"], "run_rate": o["run_rate"],
                         "wickets_per_innings": o["wickets_per_innings"],
                         "batting_first_win_percentage": t["batting_first"]["value"], "decided": t["batting_first"]["n"],
                         "chasing_win_percentage": t["chasing"]["value"],
                         "toss_winner_win_percentage": t["toss_winner"]["value"], "toss_p_value": t["p_value"],
                         "chose_field_percentage": t["chose_field"]["chosen_percentage"],
                         "highest_total": o["highest_total"]["runs"] if o["highest_total"] else None,
                         "highest_total_match_id": o["highest_total"]["match_id"] if o["highest_total"] else None,
                         "spin_wicket_share": pct(int(st["spin"]["wickets"] or 0), classified) if "spin" in st else None,
                         **ps, "last_played": o["last_played"], "last_match_id": o["last_match_id"]})
        return sorted(rows, key=lambda r: -r["matches"])
    return cached(("venue-directory", team_id) + scope.key(), build)
