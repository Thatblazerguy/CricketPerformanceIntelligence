from app.ml.similarity.cache import clear_similarity_cache, get_or_build


def test_similarity_cache_keeps_format_feature_spaces_separate():
    clear_similarity_cache()
    assert get_or_build(("bowler", "ODI", 5, 60), lambda: ["odi"]) == ["odi"]
    assert get_or_build(("bowler", "T20", 5, 60), lambda: ["t20"]) == ["t20"]
    assert get_or_build(("bowler", "ODI", 5, 60), lambda: ["rebuilt"]) == ["odi"]
    clear_similarity_cache()
