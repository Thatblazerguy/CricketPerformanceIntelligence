from app.analytics.grounds import FORMAT_BUCKETS, classify_bowling_style, format_phase_case


def test_ground_format_buckets_keep_t20i_visible():
    assert FORMAT_BUCKETS["ODI"] == ("ODI", "ODM")
    assert FORMAT_BUCKETS["T20"] == ("T20", "T20I")
    assert FORMAT_BUCKETS["Test"] == ("Test", "MDM")


def test_bowling_style_classification_is_conservative():
    assert classify_bowling_style("pace") == "pace"
    assert classify_bowling_style("Right arm fast medium") == "pace"
    assert classify_bowling_style("Left arm orthodox") == "spin"
    assert classify_bowling_style("Right arm off break") == "spin"
    assert classify_bowling_style(None) == "unknown"
    assert classify_bowling_style("bowling") == "unknown"


def test_phase_case_uses_format_specific_ranges_and_test_progression():
    sql = format_phase_case()
    assert "d.over_number BETWEEN 0 AND 5" in sql
    assert "d.over_number BETWEEN 6 AND 14" in sql
    assert "d.over_number BETWEEN 15 AND 19" in sql
    assert "d.over_number BETWEEN 0 AND 9" in sql
    assert "d.over_number BETWEEN 10 AND 39" in sql
    assert "d.over_number BETWEEN 40 AND 49" in sql
    assert "Overs " in sql
    assert "Test" in sql and "MDM" in sql

