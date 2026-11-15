"""
Integration tests for the Cricsheet parser against real match files.
"""
import pytest
from pathlib import Path
from app.ingestion.providers.cricsheet import CricsheetParser, CricsheetParseError
from app.domain.enums import Phase, ResultType, MatchFormat

REAL_IPL_FILE = Path(__file__).parent.parent.parent.parent / "data/raw/ipl/matches/1082591.json"
REAL_T20I_FILE = Path(__file__).parent.parent.parent.parent / "data/raw/t20i/matches/1001349.json"

pytestmark = pytest.mark.skipif(
    not REAL_IPL_FILE.exists(),
    reason="Real Cricsheet files not found — run data download first"
)


class TestCricsheetParserIPL:
    @pytest.fixture(scope="class")
    def parsed_match(self):
        parser = CricsheetParser()
        match, warnings = parser.parse_file(REAL_IPL_FILE)
        return match, warnings

    def test_no_critical_errors(self, parsed_match):
        match, warnings = parsed_match
        # Warnings about run inconsistencies would be a failure
        assert all("inconsistent" not in w for w in warnings), f"Warnings: {warnings}"

    def test_match_format(self, parsed_match):
        match, _ = parsed_match
        assert match.match_format == MatchFormat.T20

    def test_teams_present(self, parsed_match):
        match, _ = parsed_match
        assert "Sunrisers Hyderabad" in match.teams
        assert "Royal Challengers Bangalore" in match.teams

    def test_winner_correct(self, parsed_match):
        match, _ = parsed_match
        assert match.winner == "Sunrisers Hyderabad"
        assert match.result_margin_runs == 35
        assert match.result_type == ResultType.WIN

    def test_season(self, parsed_match):
        match, _ = parsed_match
        assert match.season == "2017"

    def test_competition(self, parsed_match):
        match, _ = parsed_match
        assert match.competition_name == "Indian Premier League"

    def test_innings_count(self, parsed_match):
        match, _ = parsed_match
        regular_innings = [i for i in match.innings if not i.is_super_over]
        assert len(regular_innings) == 2

    def test_first_innings_team(self, parsed_match):
        match, _ = parsed_match
        assert match.innings[0].batting_team == "Sunrisers Hyderabad"

    def test_first_innings_runs(self, parsed_match):
        """Verify innings 1 total = 207 (from actual scorecard)."""
        match, _ = parsed_match
        inn1 = match.innings[0]
        total = sum(d.total_runs for d in inn1.deliveries)
        assert total == 207

    def test_first_innings_overs(self, parsed_match):
        """20 complete overs = 120 legal balls."""
        match, _ = parsed_match
        inn1 = match.innings[0]
        legal = sum(1 for d in inn1.deliveries if d.is_legal_ball)
        assert legal == 120

    def test_second_innings_runs(self, parsed_match):
        """Verify innings 2 total = 172."""
        match, _ = parsed_match
        inn2 = match.innings[1]
        total = sum(d.total_runs for d in inn2.deliveries)
        assert total == 172

    def test_run_total_consistency(self, parsed_match):
        """Every delivery must satisfy: batter_runs + extras_runs == total_runs."""
        match, _ = parsed_match
        for inn in match.innings:
            for dl in inn.deliveries:
                assert dl.batter_runs + dl.extras_runs == dl.total_runs, (
                    f"Delivery {dl.source_delivery_label}: "
                    f"{dl.batter_runs} + {dl.extras_runs} != {dl.total_runs}"
                )

    def test_phase_assignment(self, parsed_match):
        """Overs 0-5 should be POWERPLAY."""
        match, _ = parsed_match
        inn1 = match.innings[0]
        for dl in inn1.deliveries:
            if dl.over_number <= 5:
                assert dl.phase == Phase.POWERPLAY
            elif 6 <= dl.over_number <= 14:
                assert dl.phase == Phase.MIDDLE
            elif dl.over_number >= 15:
                assert dl.phase == Phase.DEATH

    def test_registry_has_player_ids(self, parsed_match):
        """All players in registry should have source IDs."""
        match, _ = parsed_match
        assert len(match.registry) > 0
        # DA Warner should have an ID
        assert "DA Warner" in match.registry
        assert len(match.registry["DA Warner"]) == 8  # Cricsheet IDs are 8-char hex

    def test_wickets_have_kinds(self, parsed_match):
        """Every wicket must have a non-empty kind."""
        match, _ = parsed_match
        for inn in match.innings:
            for dl in inn.deliveries:
                for wk in dl.wickets:
                    assert wk.kind, f"Wicket with no kind on delivery {dl.source_delivery_label}"

    def test_boundary_detection(self, parsed_match):
        """Boundaries should be detected by batter_runs == 4 or 6."""
        match, _ = parsed_match
        fours = sum(1 for inn in match.innings for d in inn.deliveries if d.is_boundary_four)
        sixes = sum(1 for inn in match.innings for d in inn.deliveries if d.is_boundary_six)
        # Match 1082591: 17+15=32 fours, 9+8=17 sixes (from inspection script)
        assert fours == 32
        assert sixes == 17

    def test_checksum_is_sha256(self, parsed_match):
        match, _ = parsed_match
        assert len(match.checksum) == 64
        assert all(c in "0123456789abcdef" for c in match.checksum)


class TestCricsheetParserErrors:
    def test_invalid_json_raises(self):
        parser = CricsheetParser()
        with pytest.raises(CricsheetParseError):
            parser.parse_bytes(b"not json at all", "bad.json")

    def test_missing_info_raises(self):
        parser = CricsheetParser()
        import json
        bad_data = json.dumps({"meta": {}, "innings": []}).encode()
        with pytest.raises(CricsheetParseError, match="missing 'info'"):
            parser.parse_bytes(bad_data, "bad.json")

    @pytest.mark.parametrize("match_type,team_type,expected", [
        ("MDM", "club", MatchFormat.MDM),
        ("ODM", "club", MatchFormat.ODM),
        ("T20", "club", MatchFormat.T20),
        ("T20", "international", MatchFormat.T20I),
    ])
    def test_all_source_formats_remain_distinct(self, match_type, team_type, expected):
        import json
        data = {"meta": {"data_version": "1.3.0"}, "info": {
            "teams": ["A", "B"], "match_type": match_type, "team_type": team_type,
            "dates": ["2024-01-01"], "players": {"A": [], "B": []},
        }, "innings": []}
        match, _ = CricsheetParser().parse_bytes(json.dumps(data).encode(), "123.json")
        assert match.match_format == expected
