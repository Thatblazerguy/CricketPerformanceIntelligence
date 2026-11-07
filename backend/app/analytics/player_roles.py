"""Evidence-based role classification from explicit metadata and observed usage."""

ROLE_LABELS = {
    "batter": "Specialist Batter",
    "bowler": "Specialist Bowler",
    "batting_all_rounder": "Batting All-Rounder",
    "bowling_all_rounder": "Bowling All-Rounder",
    "wicketkeeper_batter": "Wicketkeeper-Batter",
    "unknown": "Unclassified",
}


def classify_player_role(batting_balls, batting_innings, bowling_balls, bowling_innings, metadata_role=None):
    """Return (label, source, confidence); metadata is honored only when explicit."""
    if metadata_role:
        normalized = str(metadata_role).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in ROLE_LABELS and normalized != "unknown":
            return ROLE_LABELS[normalized], "verified player metadata", "high"
    bat_balls, bat_inns = int(batting_balls or 0), int(batting_innings or 0)
    bowl_balls, bowl_inns = int(bowling_balls or 0), int(bowling_innings or 0)
    has_bat_usage = bat_balls >= 120 and bat_inns >= 8
    has_bowl_usage = bowl_balls >= 120 and bowl_inns >= 8
    if has_bat_usage and has_bowl_usage:
        # Role variant follows which discipline has the stronger observed workload.
        return ("Batting All-Rounder" if bat_balls >= bowl_balls else "Bowling All-Rounder"), "delivery usage", "medium"
    if has_bowl_usage:
        return "Specialist Bowler", "delivery usage", "medium"
    if has_bat_usage:
        return "Specialist Batter", "delivery usage", "medium"
    return "Unclassified", "insufficient observed usage", "low"
