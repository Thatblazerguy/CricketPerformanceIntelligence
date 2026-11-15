"""
Cricsheet JSON Provider Adapter
Parses Cricsheet JSON format (data_version 1.3.x) into canonical CPI entities.

This adapter is the ONLY place where Cricsheet-specific field names appear.
All downstream code uses CanonicalMatch / CanonicalDelivery exclusively.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional, List, Tuple

from app.domain.entities import (
    CanonicalDelivery,
    CanonicalExtra,
    CanonicalInnings,
    CanonicalMatch,
    CanonicalPlayer,
    CanonicalVenue,
    CanonicalWicket,
)
from app.domain.enums import (
    Gender,
    MatchFormat,
    ResultType,
    TossDecision,
    Phase,
)
from app.domain.cricket_rules import (
    is_legal_delivery,
    is_ball_faced_by_batter,
    bowling_runs_for_delivery,
    is_bowler_wicket,
    is_batter_dismissed,
    get_phase,
    normalise_season,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "cricsheet"


class CricsheetParseError(Exception):
    """Raised when a required field is missing or malformed."""
    pass


class CricsheetParser:
    """
    Parses a single Cricsheet JSON file into a CanonicalMatch.

    Usage:
        parser = CricsheetParser()
        match, warnings = parser.parse_file(Path("1082591.json"))
    """

    def parse_file(self, path: Path) -> Tuple[CanonicalMatch, List[str]]:
        """
        Parse a Cricsheet JSON file.

        Args:
            path: Absolute path to the JSON file.

        Returns:
            Tuple of (CanonicalMatch, list of warning strings).

        Raises:
            CricsheetParseError: If the file cannot be parsed or required fields are missing.
        """
        raw_bytes = path.read_bytes()
        checksum = hashlib.sha256(raw_bytes).hexdigest()

        try:
            data = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            raise CricsheetParseError(f"Invalid JSON in {path.name}: {exc}") from exc

        warnings: List[str] = []
        match = self._parse_match(data, path.name, checksum, warnings)
        return match, warnings

    def parse_bytes(
        self, raw_bytes: bytes, file_name: str
    ) -> Tuple[CanonicalMatch, List[str]]:
        """
        Parse Cricsheet JSON from bytes (useful for testing without disk I/O).
        """
        checksum = hashlib.sha256(raw_bytes).hexdigest()
        try:
            data = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            raise CricsheetParseError(f"Invalid JSON in {file_name}: {exc}") from exc

        warnings: List[str] = []
        match = self._parse_match(data, file_name, checksum, warnings)
        return match, warnings

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _parse_match(
        self, data: dict, file_name: str, checksum: str, warnings: List[str]
    ) -> CanonicalMatch:
        meta = data.get("meta", {})
        info = data.get("info")
        innings_raw = data.get("innings", [])

        if info is None:
            raise CricsheetParseError(f"{file_name}: missing 'info' key")

        # Source match ID is the filename stem (Cricsheet uses numeric IDs as filenames)
        source_match_id = Path(file_name).stem

        data_version = meta.get("data_version", "unknown")
        source_revision = int(meta.get("revision", 0))

        # --- Basic match metadata ---
        teams = info.get("teams", [])
        if len(teams) != 2:
            raise CricsheetParseError(
                f"{file_name}: expected 2 teams, got {len(teams)}"
            )

        # Format
        raw_format = info.get("match_type", "")
        team_type = info.get("team_type", "")
        if team_type == "international" and raw_format in ("T20", "IT20"):
            match_format = MatchFormat.T20I
        elif raw_format == "T20":
            match_format = MatchFormat.T20
        elif raw_format == "IT20":
            match_format = MatchFormat.T20I
        elif raw_format == "ODI":
            match_format = MatchFormat.ODI
        elif raw_format == "Test":
            match_format = MatchFormat.TEST
        else:
            try:
                match_format = MatchFormat(raw_format)
            except ValueError:
                match_format = MatchFormat.OTHER
                warnings.append(f"Unknown match_type '{raw_format}'; defaulted to OTHER")

        # Gender
        raw_gender = info.get("gender", "male")
        try:
            gender = Gender(raw_gender)
        except ValueError:
            gender = Gender.MALE
            warnings.append(f"Unknown gender '{raw_gender}'; defaulted to MALE")

        # Date
        dates = info.get("dates", [])
        if not dates:
            raise CricsheetParseError(f"{file_name}: no dates in info")
        start_date = date.fromisoformat(dates[0])

        # Season
        season = normalise_season(info.get("season", ""))

        # Event
        event = info.get("event", {})
        competition_name: Optional[str] = event.get("name")
        match_number: Optional[int] = event.get("match_number")

        # Venue
        venue_name: str = info.get("venue", "")
        city: Optional[str] = info.get("city")
        registry = info.get("registry", {})
        people_registry: dict = registry.get("people", {})
        venue_registry: dict = registry.get("venues", {})
        venue_source_id = venue_registry.get(venue_name)

        # Toss
        toss = info.get("toss", {})
        toss_winner = toss.get("winner", "")
        raw_toss_decision = toss.get("decision", "field")
        try:
            toss_decision = TossDecision(raw_toss_decision)
        except ValueError:
            toss_decision = TossDecision.FIELD
            warnings.append(
                f"Unknown toss decision '{raw_toss_decision}'; defaulted to field"
            )

        # Outcome
        outcome = info.get("outcome", {})
        winner, result_type, runs_margin, wickets_margin = self._parse_outcome(
            outcome, warnings
        )

        # Player of match
        player_of_match: List[str] = info.get("player_of_match", [])

        # Players per team
        players_by_team: dict = info.get("players", {})

        # --- Innings ---
        innings = self._parse_innings_list(
            innings_raw, people_registry, warnings, file_name, match_format.value
        )

        return CanonicalMatch(
            source_match_id=source_match_id,
            provider_name=PROVIDER_NAME,
            source_file_name=file_name,
            checksum=checksum,
            data_version=data_version,
            source_revision=source_revision,
            match_format=match_format,
            gender=gender,
            start_date=start_date,
            season=season,
            competition_name=competition_name,
            match_number=match_number,
            venue_name=venue_name,
            venue_source_id=venue_source_id,
            city=city,
            teams=teams,
            toss_winner=toss_winner,
            toss_decision=toss_decision,
            winner=winner,
            result_type=result_type,
            result_margin_runs=runs_margin,
            result_margin_wickets=wickets_margin,
            player_of_match=player_of_match,
            registry=people_registry,
            venue_registry=venue_registry,
            innings=innings,
            players=players_by_team,
        )

    def _parse_outcome(
        self, outcome: dict, warnings: List[str]
    ) -> Tuple[Optional[str], Optional[ResultType], Optional[int], Optional[int]]:
        winner: Optional[str] = outcome.get("winner")
        result_type: Optional[ResultType] = None
        runs_margin: Optional[int] = None
        wickets_margin: Optional[int] = None

        if winner:
            result_type = ResultType.WIN
            by = outcome.get("by", {})
            runs_margin = by.get("runs")
            wickets_margin = by.get("wickets")
        elif "result" in outcome:
            raw_result = outcome["result"]
            try:
                result_type = ResultType(raw_result)
            except ValueError:
                warnings.append(f"Unknown outcome result '{raw_result}'")

        return winner, result_type, runs_margin, wickets_margin

    def _parse_innings_list(
        self,
        innings_raw: list,
        people_registry: dict,
        warnings: List[str],
        file_name: str,
        match_format: str = "T20",
    ) -> List[CanonicalInnings]:
        innings_list: List[CanonicalInnings] = []

        # Assign innings numbers, handling super overs
        regular_count = 0
        super_over_count = 0

        for inn_raw in innings_raw:
            is_super_over = bool(inn_raw.get("super_over", False))

            if is_super_over:
                super_over_count += 1
                innings_number = 100 + super_over_count  # Super overs get 101, 102...
            else:
                regular_count += 1
                innings_number = regular_count

            innings = self._parse_innings(
                inn_raw,
                innings_number,
                is_super_over,
                people_registry,
                warnings,
                file_name,
                match_format,
            )
            innings_list.append(innings)

        return innings_list

    def _parse_innings(
        self,
        inn_raw: dict,
        innings_number: int,
        is_super_over: bool,
        people_registry: dict,
        warnings: List[str],
        file_name: str,
        match_format: str = "T20",
    ) -> CanonicalInnings:
        batting_team = inn_raw.get("team", "")
        absent_hurt: List[str] = inn_raw.get("absent_hurt", [])

        # Target (second innings / DLS)
        target_obj = inn_raw.get("target")
        target_runs: Optional[int] = None
        target_overs: Optional[int] = None
        if target_obj:
            target_runs = target_obj.get("runs")
            target_overs = target_obj.get("overs")

        # Parse deliveries
        deliveries: List[CanonicalDelivery] = []
        overs_raw = inn_raw.get("overs", [])

        # Warn if miscounted overs present
        if inn_raw.get("miscounted_overs"):
            warnings.append(
                f"{file_name} innings {innings_number}: miscounted_overs flagged in source"
            )

        for over_obj in overs_raw:
            over_number = int(over_obj.get("over", 0))
            phase = get_phase(over_number, is_super_over, match_format)
            deliveries_raw = over_obj.get("deliveries", [])

            for seq_idx, dl_raw in enumerate(deliveries_raw):
                delivery = self._parse_delivery(
                    dl_raw,
                    over_number,
                    seq_idx,
                    phase,
                    people_registry,
                    warnings,
                    file_name,
                    innings_number,
                )
                deliveries.append(delivery)

        return CanonicalInnings(
            innings_number=innings_number,
            batting_team=batting_team,
            is_super_over=is_super_over,
            target_runs=target_runs,
            target_overs=target_overs,
            absent_hurt=absent_hurt,
            deliveries=deliveries,
        )

    def _parse_delivery(
        self,
        dl_raw: dict,
        over_number: int,
        seq_idx: int,
        phase: Phase,
        people_registry: dict,
        warnings: List[str],
        file_name: str,
        innings_number: int,
    ) -> CanonicalDelivery:
        source_label = str(dl_raw.get("actual_delivery", f"{over_number}.?"))

        batter = dl_raw.get("batter", "")
        bowler = dl_raw.get("bowler", "")
        non_striker = dl_raw.get("non_striker", "")

        batter_source_id = people_registry.get(batter)
        bowler_source_id = people_registry.get(bowler)
        non_striker_source_id = people_registry.get(non_striker)

        # Runs
        runs_obj = dl_raw.get("runs", {})
        batter_runs = int(runs_obj.get("batter", 0))
        extras_runs = int(runs_obj.get("extras", 0))
        total_runs = int(runs_obj.get("total", 0))

        # Validate run consistency
        if batter_runs + extras_runs != total_runs:
            warnings.append(
                f"{file_name} innings {innings_number} over {over_number} "
                f"delivery {seq_idx}: runs inconsistent "
                f"({batter_runs} + {extras_runs} != {total_runs})"
            )

        # Extras
        extras_raw = dl_raw.get("extras", {})
        canonical_extras = [
            CanonicalExtra(extra_type=et, runs=rv)
            for et, rv in extras_raw.items()
        ]

        # Legal ball classification
        legal = is_legal_delivery(extras_raw)
        ball_faced = is_ball_faced_by_batter(extras_raw)
        bowling_runs = bowling_runs_for_delivery(batter_runs, extras_raw)

        # Boundaries (determined by batter runs, not total)
        is_four = batter_runs == 4
        is_six = batter_runs == 6

        # Wickets
        wickets_raw = dl_raw.get("wickets", [])
        canonical_wickets = [
            self._parse_wicket(wk, people_registry, warnings, file_name, innings_number, over_number)
            for wk in wickets_raw
        ]

        # Replacement (impact player)
        has_replacement = bool(dl_raw.get("replacements"))

        return CanonicalDelivery(
            over_number=over_number,
            delivery_sequence=seq_idx,
            source_delivery_label=source_label,
            batter=batter,
            batter_source_id=batter_source_id,
            bowler=bowler,
            bowler_source_id=bowler_source_id,
            non_striker=non_striker,
            non_striker_source_id=non_striker_source_id,
            batter_runs=batter_runs,
            extras_runs=extras_runs,
            total_runs=total_runs,
            is_legal_ball=legal,
            is_ball_faced_by_batter=ball_faced,
            bowling_runs=bowling_runs,
            phase=phase,
            extras=canonical_extras,
            wickets=canonical_wickets,
            has_replacement=has_replacement,
            is_boundary_four=is_four,
            is_boundary_six=is_six,
        )

    def _parse_wicket(
        self,
        wk_raw: dict,
        people_registry: dict,
        warnings: List[str],
        file_name: str,
        innings_number: int,
        over_number: int,
    ) -> CanonicalWicket:
        kind = wk_raw.get("kind", "unknown")
        player_out = wk_raw.get("player_out", "")
        player_out_source_id = people_registry.get(player_out)

        if not player_out:
            warnings.append(
                f"{file_name} innings {innings_number} over {over_number}: "
                f"wicket with no player_out"
            )

        bowler_credit = is_bowler_wicket(kind)
        batter_dismissed = is_batter_dismissed(kind)

        # Fielder (optional)
        fielders = wk_raw.get("fielders", [])
        fielder_name: Optional[str] = None
        fielder_source_id: Optional[str] = None
        if fielders:
            fielder_name = fielders[0].get("name")
            if fielder_name:
                fielder_source_id = people_registry.get(fielder_name)

        return CanonicalWicket(
            player_out=player_out,
            player_out_source_id=player_out_source_id,
            kind=kind,
            is_bowler_wicket=bowler_credit,
            is_batter_dismissed=batter_dismissed,
            fielder_name=fielder_name,
            fielder_source_id=fielder_source_id,
        )
