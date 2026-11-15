"""Idempotently integrate curated bowling classifications from a CPI player CSV."""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from sqlalchemy import case, func, select

from app.db.session import SessionLocal
from app.models.models import Player, PlayerAttribute, PlayerNameAlias


CONFIDENCE = {"low": 1, "medium": 2, "high": 3}


def normalize_style(value: str | None) -> dict:
    raw = (value or "").strip()
    key = " ".join(raw.casefold().replace("–", "-").replace("—", "-").replace("/", " / ").split())
    key = key.replace("right arm", "right-arm").replace("left arm", "left-arm")
    key = key.replace("fast medium", "fast-medium").replace("medium fast", "medium-fast").replace("medium slow", "medium-slow")
    exact = {
        "right-arm off break": ("Spin", "Right-arm Off Break", "right-arm", None),
        "right arm off break": ("Spin", "Right-arm Off Break", "right-arm", None),
        "right-arm leg break": ("Spin", "Right-arm Leg Break", "right-arm", None),
        "right-arm wrist spin": ("Spin", "Right-arm Wrist Spin", "right-arm", None),
        "left-arm orthodox": ("Spin", "Left-arm Orthodox", "left-arm", None),
        "left-arm wrist spin": ("Spin", "Left-arm Wrist Spin", "left-arm", None),
        "left-arm chinaman": ("Spin", "Left-arm Chinaman / Left-arm Unorthodox", "left-arm", None),
        "left-arm unorthodox": ("Spin", "Left-arm Chinaman / Left-arm Unorthodox", "left-arm", None),
        "left-arm chinaman / left-arm unorthodox": ("Spin", "Left-arm Chinaman / Left-arm Unorthodox", "left-arm", None),
        "right-arm fast": ("Pace", "Right-arm Fast", "right-arm", "Fast"),
        "right-arm fast-medium": ("Pace", "Right-arm Fast-Medium", "right-arm", "Fast-Medium"),
        "right-arm medium-fast": ("Pace", "Right-arm Medium-Fast", "right-arm", "Medium-Fast"),
        "right-arm medium": ("Pace", "Right-arm Medium", "right-arm", "Medium"),
        "left-arm fast": ("Pace", "Left-arm Fast", "left-arm", "Fast"),
        "left-arm fast-medium": ("Pace", "Left-arm Fast-Medium", "left-arm", "Fast-Medium"),
        "left-arm medium-fast": ("Pace", "Left-arm Medium-Fast", "left-arm", "Medium-Fast"),
        "left-arm medium": ("Pace", "Left-arm Medium", "left-arm", "Medium"),
        "left-arm medium-slow": ("Pace", "Left-arm Medium-Slow", "left-arm", "Medium-Slow"),
    }
    if key in exact:
        category, style, arm, speed = exact[key]
        return {"raw": raw, "category": category, "style": style, "arm": arm, "speed": speed}
    # Retain an unrecognized but explicitly supplied source style without guessing its subtype.
    if raw:
        return {"raw": raw, "category": None, "style": "Other / Unclassified", "arm": None, "speed": None}
    return {"raw": "", "category": None, "style": None, "arm": None, "speed": None}


def put_attribute(db, player_id: str, kind: str, value: str | None, source: str, confidence: str, counts: Counter, conflicts: list, name: str):
    if not value:
        return
    attrs = db.scalars(select(PlayerAttribute).where(PlayerAttribute.player_id == player_id,
                                                      PlayerAttribute.attribute_type == kind)
                       .order_by(case((PlayerAttribute.confidence == "high", 3),
                                      (PlayerAttribute.confidence == "medium", 2),
                                      (PlayerAttribute.confidence == "low", 1), else_=0).desc(),
                                 PlayerAttribute.updated_at.desc())).all()
    current = next((a for a in attrs if a.attribute_value and a.attribute_value.strip().casefold() not in {"unknown", "not available"}), None)
    if current:
        if current.attribute_value.strip().casefold() == value.strip().casefold():
            return
        incoming_rank = CONFIDENCE.get((confidence or "").lower(), 0)
        current_rank = CONFIDENCE.get((current.confidence or "").lower(), 0)
        if kind == "bowling_style":
            old_normalized = normalize_style(current.attribute_value).get("style")
            new_normalized = normalize_style(value).get("style")
            if old_normalized == new_normalized and new_normalized not in (None, "Other / Unclassified"):
                # Canonicalize equivalent spellings without lowering stored confidence.
                current.attribute_value = new_normalized
                counts["canonicalized_styles"] += 1
                return
        if current_rank >= incoming_rank:
            conflicts.append({"player": name, "attribute": kind, "existing": current.attribute_value,
                              "existing_source": current.source, "incoming": value, "action": "preserved existing"})
            return
        conflicts.append({"player": name, "attribute": kind, "existing": current.attribute_value,
                          "existing_source": current.source, "incoming": value, "action": "replaced lower-confidence value"})
        current.attribute_value, current.source, current.confidence = value, source, confidence
        counts["updated_attributes"] += 1
        return
    db.add(PlayerAttribute(player_id=player_id, attribute_type=kind, attribute_value=value,
                           source=source, confidence=confidence))
    counts["inserted_attributes"] += 1


def run(csv_path: Path, report_path: Path) -> None:
    counts = Counter()
    conflicts: list[dict] = []
    style_counts = Counter()
    db = SessionLocal()
    try:
        players = db.scalars(select(Player)).all()
        by_id = {p.id: p for p in players}
        by_name: dict[str, list[Player]] = {}
        for player in players:
            by_name.setdefault(player.canonical_name.strip().casefold(), []).append(player)
        aliases: dict[str, set[str]] = {}
        for pid, alias in db.execute(select(PlayerNameAlias.player_id, PlayerNameAlias.alias)).all():
            aliases.setdefault(alias.strip().casefold(), set()).add(pid)

        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"player_id", "canonical_name", "bowling_style", "bowling_type"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise ValueError(f"CSV is missing required columns: {sorted(required - set(reader.fieldnames or []))}")
            for row in reader:
                counts["csv_rows"] += 1
                player = by_id.get((row.get("player_id") or "").strip())
                if player:
                    counts["matched_by_player_id"] += 1
                else:
                    name_key = (row.get("canonical_name") or "").strip().casefold()
                    candidates = by_name.get(name_key, [])
                    if not candidates and name_key in aliases:
                        candidates = [by_id[pid] for pid in aliases[name_key] if pid in by_id]
                    if len(candidates) == 1:
                        player = candidates[0]
                        counts["matched_by_verified_name"] += 1
                    else:
                        counts["unmatched_rows"] += 1
                        continue
                source_raw = (row.get("bowling_style_source") or "corrected_player_database_csv").strip() or "corrected_player_database_csv"
                confidence = (row.get("bowling_style_confidence") or "medium").strip().lower()
                if confidence not in CONFIDENCE:
                    confidence = "medium"
                incoming = normalize_style(row.get("bowling_style"))
                raw_category = (row.get("bowling_type") or "").strip().title()
                category = incoming["category"] or (raw_category if raw_category in {"Pace", "Spin"} else None)
                if incoming["category"] in {"Pace", "Spin"} and raw_category in {"Pace", "Spin"} and incoming["category"] != raw_category:
                    conflicts.append({"player": player.canonical_name, "attribute": "bowling_type/style",
                                      "existing": raw_category, "incoming": incoming["category"], "action": "style-derived category used"})
                if incoming["style"]:
                    style_counts[incoming["style"]] += 1
                put_attribute(db, player.id, "bowling_style_source_value", incoming["raw"], source_raw, confidence, counts, conflicts, player.canonical_name)
                put_attribute(db, player.id, "bowling_style", incoming["style"], source_raw, confidence, counts, conflicts, player.canonical_name)
                put_attribute(db, player.id, "bowling_type", category, source_raw, confidence, counts, conflicts, player.canonical_name)
                put_attribute(db, player.id, "bowling_arm", incoming["arm"], source_raw, confidence, counts, conflicts, player.canonical_name)
                put_attribute(db, player.id, "bowling_speed_category", incoming["speed"], source_raw, confidence, counts, conflicts, player.canonical_name)

        # Legacy broad values in bowling_style are category labels, not specific styles.
        # Preserve the raw string separately and keep the category in bowling_type.
        broad_rows = db.scalars(select(PlayerAttribute).where(
            PlayerAttribute.attribute_type == "bowling_style",
            func.lower(PlayerAttribute.attribute_value).in_(["pace", "spin"]),
        )).all()
        for broad in broad_rows:
            category = broad.attribute_value.strip().title()
            put_attribute(db, broad.player_id, "bowling_style_source_value", broad.attribute_value,
                          broad.source or "legacy_player_attribute", broad.confidence or "low", counts, conflicts,
                          by_id[broad.player_id].canonical_name if broad.player_id in by_id else broad.player_id)
            put_attribute(db, broad.player_id, "bowling_type", category,
                          broad.source or "legacy_player_attribute", broad.confidence or "low", counts, conflicts,
                          by_id[broad.player_id].canonical_name if broad.player_id in by_id else broad.player_id)
            db.delete(broad)
            counts["legacy_broad_style_values_normalized"] += 1
        db.flush()

        # Final database coverage (values are read back from the effective, confidence-ranked records).
        final_players = db.scalar(select(func.count()).select_from(Player)) or 0
        rows = db.execute(select(PlayerAttribute.player_id, PlayerAttribute.attribute_type, PlayerAttribute.attribute_value,
                                 PlayerAttribute.confidence).where(PlayerAttribute.attribute_type.in_(
                                     ["bowling_type", "bowling_style"])).order_by(
                                         PlayerAttribute.player_id,
                                         case((PlayerAttribute.confidence == "high", 3), (PlayerAttribute.confidence == "medium", 2), (PlayerAttribute.confidence == "low", 1), else_=0).desc(),
                                         PlayerAttribute.updated_at.desc())).all()
        effective: dict[str, dict[str, str]] = {}
        for pid, kind, value, _ in rows:
            effective.setdefault(pid, {}).setdefault(kind, value)
        categories = Counter((v.get("bowling_type") or "Missing") for v in effective.values())
        styles = Counter((v.get("bowling_style") or "Missing") for v in effective.values())
        classified_categories = {"Pace", "Spin"}
        style_specific = {k: v for k, v in styles.items() if k not in {"Missing", "Other / Unclassified"}}
        broad_only = sum(1 for v in effective.values() if v.get("bowling_type") in classified_categories and not v.get("bowling_style"))
        missing = sum(1 for player in players if player.id not in effective or not effective[player.id].get("bowling_type"))
        counts["players_in_database"] = final_players
        counts["players_pace"] = categories.get("Pace", 0)
        counts["players_spin"] = categories.get("Spin", 0)
        counts["players_other_unclassified_category"] = categories.get("Other / Unclassified", 0)
        counts["players_other_unclassified_style"] = styles.get("Other / Unclassified", 0)
        counts["players_with_specific_style"] = sum(style_specific.values())
        counts["players_broad_category_only"] = broad_only
        counts["players_missing_bowling_information"] = missing
        db.commit()

        lines = ["# Bowling Style Integration Audit", "", f"Source CSV: `{csv_path.name}`", "",
                 "## Import results", "", f"- CSV rows: {counts['csv_rows']}",
                 f"- Matched by player ID: {counts['matched_by_player_id']}",
                 f"- Matched by unique canonical name / verified alias: {counts['matched_by_verified_name']}",
                 f"- Unmatched or ambiguous rows: {counts['unmatched_rows']}",
                 f"- Attribute values inserted: {counts['inserted_attributes']}",
                 f"- Lower-confidence values updated: {counts['updated_attributes']}",
                 f"- Existing conflicting classifications preserved or documented: {len(conflicts)}", "",
                 "## Final database coverage", "", f"- Total players: {final_players}",
                 f"- Pace: {counts['players_pace']}", f"- Spin: {counts['players_spin']}",
                 f"- Other / Unclassified category: {counts['players_other_unclassified_category']}",
                 f"- Other / Unclassified specific style: {counts['players_other_unclassified_style']}",
                 f"- Players with a specific style: {counts['players_with_specific_style']}",
                 f"- Broad category only: {counts['players_broad_category_only']}",
                 f"- Missing bowling information: {counts['players_missing_bowling_information']}", "",
                 "### Specific styles", ""]
        lines.extend(f"- {style}: {count}" for style, count in sorted(style_specific.items()))
        lines += ["", "## Conflicts", "", "Conflicting higher-confidence or source-category evidence was not silently overwritten.", ""]
        lines.extend(f"- {item['player']} · {item['attribute']}: {item.get('existing')} → {item.get('incoming')} ({item['action']})" for item in conflicts)
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(dict(counts))
        print(f"Audit written: {report_path}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=Path.home() / "Downloads/players_database_corrected (3).csv")
    parser.add_argument("--report", type=Path, default=root / "BOWLING_STYLE_AUDIT.md")
    args = parser.parse_args()
    run(args.csv, args.report)
