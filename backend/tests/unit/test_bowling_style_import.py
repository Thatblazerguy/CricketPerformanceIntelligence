from scripts.import_player_bowling_styles import normalize_style


def test_maps_specific_pace_style_without_losing_arm_or_speed():
    assert normalize_style("Right-arm fast-medium") == {
        "raw": "Right-arm fast-medium", "category": "Pace",
        "style": "Right-arm Fast-Medium", "arm": "right-arm", "speed": "Fast-Medium",
    }


def test_maps_spin_subtypes_without_assuming_spinner_type():
    assert normalize_style("Left-arm wrist spin")["style"] == "Left-arm Wrist Spin"
    assert normalize_style("Right-arm leg break")["style"] == "Right-arm Leg Break"
    assert normalize_style("Right-arm leg break")["category"] == "Spin"


def test_unverified_or_missing_style_is_not_guessed():
    assert normalize_style(None) == {"raw": "", "category": None, "style": None, "arm": None, "speed": None}
    unknown = normalize_style("Mystery variation")
    assert unknown["category"] is None
    assert unknown["style"] == "Other / Unclassified"
    assert unknown["arm"] is None and unknown["speed"] is None


def test_existing_space_variant_canonicalizes():
    assert normalize_style("Right Arm Fast Medium")["style"] == "Right-arm Fast-Medium"
