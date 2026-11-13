from app.analytics.scorecard import build_innings_scorecard


def delivery(over, batter, batter_id, bowler_runs, *, runs=0, total=None, legal=True, faced=True, extras=None, wickets=None, non_striker="Partner"):
    return {
        "over_index": over, "batter": batter, "batter_id": batter_id,
        "bowler": "Bowler", "bowler_id": "bowler-id", "non_striker": non_striker,
        "batter_runs": runs, "total_runs": runs if total is None else total,
        "bowling_runs": bowler_runs, "legal": legal, "faced": faced,
        "four": runs == 4, "six": runs == 6, "extra_types": extras or [], "wickets": wickets or [],
        "over_display": f"{over + 1}.1",
    }


def test_reconstructs_score_extras_and_figures_with_illegal_deliveries():
    innings = {"deliveries": [
        delivery(0, "Batter A", "a", 4, runs=4),
        delivery(0, "Batter A", "a", 1, total=1, legal=False, faced=False, extras=[{"type": "wides", "runs": 1}]),
        delivery(0, "Batter A", "a", 2, runs=2),
        delivery(0, "Batter A", "a", 1, total=1, legal=False, extras=[{"type": "noballs", "runs": 1}], wickets=[{"player_out_id": "a", "player_out": "Batter A", "kind": "caught", "fielder": "Fielder", "bowler_credited": True}]),
        delivery(0, "Batter A", "a", 0, total=1, extras=[{"type": "byes", "runs": 1}]),
    ]}
    result = build_innings_scorecard(innings, "T20")
    assert (result["total"], result["wickets"], result["overs"]) == (9, 1, "0.3")
    assert result["extras"] == {"wides": 1, "noballs": 1, "byes": 1}
    batter = result["batting"][0]
    assert (batter["runs"], batter["balls"], batter["fours"], batter["dismissal"]) == (6, 4, 1, "c Fielder b Bowler")
    bowler = result["bowling"][0]
    assert (bowler["legal_balls"], bowler["runs"], bowler["wickets"], bowler["wides"], bowler["no_balls"]) == (3, 8, 1, 1, 1)
    assert sum(p["runs"] for p in result["partnerships"]) == result["total"]
    assert sum(d["total_runs"] for p in result["partnerships"] for d in p["delivery_breakdown"]) == result["total"]
    assert bowler["over_breakdown"][0]["wickets"] == 1


def test_non_bowler_dismissals_are_in_fow_but_not_bowler_wickets_and_tests_have_no_pp():
    innings = {"deliveries": [
        delivery(0, "Batter B", "b", 0, runs=1, wickets=[{"player_out_id": "b", "player_out": "Batter B", "kind": "run out", "fielder": "Fielder", "bowler_credited": False}]),
        delivery(10, "Batter C", "c", 0, legal=False, faced=False, wickets=[{"player_out_id": "c", "player_out": "Batter C", "kind": "retired hurt", "batter_dismissed": False, "bowler_credited": False}]),
    ]}
    result = build_innings_scorecard(innings, "Test")
    assert result["wickets"] == 1
    assert result["fall_of_wickets"][0]["batter"] == "Batter B"
    assert result["batting"][1]["dismissal"] == "retired hurt"
    assert all(not phase["phase"].startswith("Powerplay") for phase in result["phases"])
    assert all(b["wickets"] == 0 for b in result["bowling"])
