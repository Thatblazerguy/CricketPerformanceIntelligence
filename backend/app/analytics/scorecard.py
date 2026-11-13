"""Pure scorecard reconstruction from one innings of canonical delivery rows."""
from collections import defaultdict


def _overs(legal_balls: int) -> str:
    return f"{legal_balls // 6}.{legal_balls % 6}"


def _phase(match_format: str, over_index: int, innings_overs: int):
    fmt = (match_format or "").upper()
    if fmt in {"T20", "T20I"}:
        return "Powerplay" if over_index < 6 else "Middle" if over_index < 15 else "Death"
    if fmt in {"ODI", "ODM"}:
        return "Powerplay" if over_index < 10 else "Middle" if over_index < 40 else "Death"
    # Multi-day cricket has no limited-overs powerplay phases.
    if fmt in {"TEST", "MDM"}:
        third = max(1, (innings_overs + 2) // 3)
        return "Innings progression 1" if over_index < third else "Innings progression 2" if over_index < 2 * third else "Innings progression 3"
    return None


def build_innings_scorecard(innings: dict, match_format: str) -> dict:
    """Calculate batting, bowling, partnerships and progression from delivery rows.

    Expected delivery dictionaries retain IDs and names, credited-dismissal flags,
    delivery extras, legal-ball status, and team/batter runs.
    """
    deliveries = innings.get("deliveries", [])
    batting, bowling = {}, {}
    extras = defaultdict(int)
    over_rows = defaultdict(lambda: {"runs": 0, "legal_balls": 0, "wickets": 0})
    phase_rows = defaultdict(lambda: {"runs": 0, "legal_balls": 0, "wickets": 0})
    falls, partnerships = [], []
    total_runs = legal_balls = wickets_lost = 0
    running_score = 0
    partnership = {"number": 1, "runs": 0, "balls": 0, "batters": set(), "delivery_breakdown": []}

    innings_overs = max((d.get("over_index", 0) for d in deliveries), default=0) + 1
    for d in deliveries:
        batter_id, bowler_id = d.get("batter_id"), d.get("bowler_id")
        batter_name, bowler_name = d.get("batter"), d.get("bowler")
        br, total, conceded = int(d.get("batter_runs") or 0), int(d.get("total_runs") or 0), int(d.get("bowling_runs") or 0)
        is_legal = bool(d.get("legal"))
        over_index = int(d.get("over_index", 0))
        total_runs += total
        running_score += total
        if is_legal:
            legal_balls += 1
        over_rows[over_index]["runs"] += total
        over_rows[over_index]["legal_balls"] += int(is_legal)
        phase = "Super Over" if innings.get("is_super_over") else _phase(match_format, over_index, innings_overs)
        if phase:
            phase_rows[phase]["runs"] += total
            phase_rows[phase]["legal_balls"] += int(is_legal)

        if batter_id:
            row = batting.setdefault(batter_id, {"player_id": batter_id, "player": batter_name, "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dismissal": None})
            row["runs"] += br
            row["balls"] += int(bool(d.get("faced")))
            row["fours"] += int(bool(d.get("four")))
            row["sixes"] += int(bool(d.get("six")))
        if bowler_id:
            row = bowling.setdefault(bowler_id, {"player_id": bowler_id, "player": bowler_name, "legal_balls": 0, "runs": 0, "wickets": 0, "wides": 0, "no_balls": 0, "overs": defaultdict(lambda: {"runs": 0, "legal": 0, "wickets": 0})})
            row["legal_balls"] += int(is_legal)
            row["runs"] += conceded
            row["overs"][over_index]["runs"] += conceded
            row["overs"][over_index]["legal"] += int(is_legal)
            for e in d.get("extra_types", []):
                typ, runs = (e.get("type") or "").lower(), int(e.get("runs") or 0)
                if typ in {"wides", "wide"}:
                    row["wides"] += runs
                elif typ in {"noballs", "no_ball", "no-balls", "no-balls"}:
                    row["no_balls"] += runs

        for e in d.get("extra_types", []):
            typ = (e.get("type") or "").lower()
            normalized = {"wide": "wides", "no_ball": "noballs", "no-ball": "noballs", "leg_byes": "legbyes", "leg-byes": "legbyes"}.get(typ, typ)
            if normalized in {"wides", "noballs", "byes", "legbyes", "penalty"}:
                extras[normalized] += int(e.get("runs") or 0)

        partnership["runs"] += total
        partnership["balls"] += int(is_legal)
        partnership["batters"].update(n for n in (batter_name, d.get("non_striker")) if n)
        partnership["delivery_breakdown"].append({
            "over": d.get("over_display"), "batter": batter_name, "bowler": bowler_name,
            "batter_runs": br, "total_runs": total, "legal": is_legal,
            "extras": d.get("extra_types", []),
            "wickets": [{"player": w.get("player_out"), "kind": w.get("kind")} for w in d.get("wickets", [])],
        })
        for w in d.get("wickets", []):
            out_id = w.get("player_out_id")
            if out_id and out_id not in batting:
                batting[out_id] = {"player_id": out_id, "player": w.get("player_out"), "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dismissal": None}
            kind = (w.get("kind") or "dismissed").lower()
            fielder = w.get("fielder")
            if kind in {"run out", "obstructing the field"}:
                detail = f"{kind}" + (f" ({fielder})" if fielder else "")
            elif kind in {"retired hurt", "retired out", "absent hurt"}:
                detail = kind
            elif kind == "caught and bowled":
                detail = f"c & b {bowler_name}" if bowler_name else kind
            elif kind == "caught":
                detail = "c" + (f" {fielder}" if fielder else "") + (f" b {bowler_name}" if bowler_name else "")
            else:
                detail = kind + (f" b {bowler_name}" if bowler_name else "")
            if out_id in batting:
                batting[out_id]["dismissal"] = detail
            if w.get("batter_dismissed", True):
                wickets_lost += 1
                over_rows[over_index]["wickets"] += 1
                if phase:
                    phase_rows[phase]["wickets"] += 1
                if bowler_id:
                    bowling[bowler_id]["overs"][over_index]["wickets"] += int(bool(w.get("bowler_credited")))
                falls.append({"wicket": wickets_lost, "score": running_score, "over": d.get("over_display"), "batter": w.get("player_out")})
                partnerships.append({"number": partnership["number"], "runs": partnership["runs"], "balls": partnership["balls"], "batters": sorted(partnership["batters"]), "ended_at_wicket": wickets_lost, "delivery_breakdown": partnership["delivery_breakdown"]})
                partnership = {"number": partnership["number"] + 1, "runs": 0, "balls": 0, "batters": set(), "delivery_breakdown": []}
            if w.get("bowler_credited") and bowler_id:
                bowling[bowler_id]["wickets"] += 1

    if partnership["runs"] or partnership["balls"]:
        partnerships.append({"number": partnership["number"], "runs": partnership["runs"], "balls": partnership["balls"], "batters": sorted(partnership["batters"]), "ended_at_wicket": None, "delivery_breakdown": partnership["delivery_breakdown"]})

    batting_rows = []
    for row in batting.values():
        balls = row["balls"]
        batting_rows.append({**row, "dismissal": row["dismissal"] or "not out", "strike_rate": round(row["runs"] * 100 / balls, 2) if balls else None})
        row.pop("dismissal", None)
    bowling_rows = []
    for row in bowling.values():
        maidens = sum(1 for ov in row["overs"].values() if ov["legal"] == 6 and ov["runs"] == 0)
        balls, runs, wkts = row["legal_balls"], row["runs"], row["wickets"]
        over_breakdown = [{"over": idx + 1, "runs": over["runs"], "legal_balls": over["legal"], "wickets": over["wickets"]} for idx, over in sorted(row["overs"].items())]
        bowling_rows.append({"player_id": row["player_id"], "player": row["player"], "overs": _overs(balls), "legal_balls": balls, "maidens": maidens, "runs": runs, "wickets": wkts, "economy": round(runs * 6 / balls, 2) if balls else None, "wides": row["wides"], "no_balls": row["no_balls"], "over_breakdown": over_breakdown})

    overs_out, cumulative = [], 0
    for idx in sorted(over_rows):
        bucket = over_rows[idx]
        cumulative += bucket["runs"]
        overs_out.append({"over": idx + 1, **bucket, "score": cumulative, "run_rate": round(cumulative * 6 / max(1, sum(v["legal_balls"] for k, v in over_rows.items() if k <= idx)), 2)})
    phases_out = [{"phase": name, **values, "economy": round(values["runs"] * 6 / values["legal_balls"], 2) if values["legal_balls"] else None} for name, values in phase_rows.items()]
    return {"total": total_runs, "wickets": wickets_lost, "legal_balls": legal_balls, "overs": _overs(legal_balls), "extras": dict(extras), "batting": batting_rows, "bowling": bowling_rows, "fall_of_wickets": falls, "partnerships": partnerships, "overs_progression": overs_out, "phases": phases_out}
