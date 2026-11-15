#!/usr/bin/env python3
"""
Milestone 1 Inspection Script
Parses a sample of Cricsheet files and prints a readable summary.
Run from the backend/ directory: python scripts/inspect_cricsheet.py
"""
import sys
import json
import logging
from pathlib import Path

# Add backend/app to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ingestion.providers.cricsheet import CricsheetParser
from app.domain.cricket_rules import format_overs

logging.basicConfig(level=logging.WARNING)


def summarise_match(match, warnings):
    innings_summary = []
    for inn in match.innings:
        legal_balls = sum(1 for d in inn.deliveries if d.is_legal_ball)
        total_runs = sum(d.total_runs for d in inn.deliveries)
        batter_runs = sum(d.batter_runs for d in inn.deliveries)
        extras = sum(d.extras_runs for d in inn.deliveries)
        wickets = sum(1 for d in inn.deliveries for w in d.wickets if w.is_bowler_wicket)
        all_wickets = sum(len(d.wickets) for d in inn.deliveries)
        fours = sum(1 for d in inn.deliveries if d.is_boundary_four)
        sixes = sum(1 for d in inn.deliveries if d.is_boundary_six)
        super_tag = " [SUPER OVER]" if inn.is_super_over else ""
        innings_summary.append(
            f"  Innings {inn.innings_number}{super_tag}: {inn.batting_team} "
            f"| {total_runs} runs ({batter_runs} bat + {extras} extras) "
            f"| {format_overs(legal_balls)} overs "
            f"| {wickets} bowler-wkts / {all_wickets} total wkts "
            f"| 4s:{fours} 6s:{sixes}"
        )
    return "\n".join(innings_summary)


def inspect_files(data_dirs, max_files=10):
    parser = CricsheetParser()
    total_files = 0
    total_warnings = 0

    for data_dir in data_dirs:
        p = Path(data_dir)
        if not p.exists():
            print(f"[SKIP] {data_dir} does not exist")
            continue

        files = sorted(p.glob("*.json"))
        sample = files[:max_files]
        print(f"\n{'='*70}")
        print(f"Directory: {data_dir}  ({len(files)} total files)")
        print(f"Inspecting {len(sample)} sample files")
        print(f"{'='*70}")

        for path in sample:
            try:
                match, warnings = parser.parse_file(path)
                total_files += 1
                total_warnings += len(warnings)
                result_str = (
                    f"{match.winner} won by {match.result_margin_runs}R"
                    if match.result_margin_runs
                    else (
                        f"{match.winner} won by {match.result_margin_wickets}W"
                        if match.result_margin_wickets and match.winner
                        else str(match.result_type or "Unknown result")
                    )
                )
                print(f"\n[{path.name}]")
                print(
                    f"  {match.competition_name} {match.season} | "
                    f"{match.start_date} | {match.venue_name}"
                )
                print(f"  Teams: {' vs '.join(match.teams)}")
                print(f"  Result: {result_str}")
                print(
                    f"  Registry: {len(match.registry)} players "
                    f"| {len(match.innings)} innings (incl. super overs)"
                )
                print(summarise_match(match, warnings))
                if warnings:
                    for w in warnings:
                        print(f"  ⚠ {w}")
            except Exception as e:
                print(f"\n[ERROR] {path.name}: {e}")

    print(f"\n{'='*70}")
    print(
        f"TOTAL: {total_files} files parsed successfully | {total_warnings} warnings"
    )


if __name__ == "__main__":
    inspect_files(
        [
            "../data/raw/ipl/matches",
            "../data/raw/t20i/matches",
        ],
        max_files=5,
    )

