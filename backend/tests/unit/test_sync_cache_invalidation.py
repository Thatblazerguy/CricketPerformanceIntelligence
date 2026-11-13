"""The API drops analytics caches when another process (the sync worker) imports data."""
from app.analytics import grounds
from app.ml.similarity import cache as similarity_cache
from app.services import data_version


class FakeConn:
    def __init__(self, box):
        self.box = box

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, _sql):
        box = self.box

        class R:
            def scalar(self):
                return box["marker"]
        return R()


class FakeEngine:
    def __init__(self, box):
        self.box = box

    def connect(self):
        return FakeConn(self.box)


def test_caches_cleared_only_when_marker_moves(monkeypatch):
    monkeypatch.setattr(data_version, "CHECK_SECONDS", 0.0)
    monkeypatch.setattr(data_version, "_last_poll", 0.0)
    monkeypatch.setattr(data_version, "_initialised", False)
    monkeypatch.setattr(data_version, "_last_marker", None)
    box = {"marker": 7}
    engine = FakeEngine(box)

    grounds._CACHE[("x", "T20")] = (None, {"cached": True})
    similarity_cache.get_or_build("k", lambda: 1)

    assert data_version.maybe_invalidate_caches(engine) is False  # first poll only records the baseline
    assert grounds._CACHE
    assert data_version.maybe_invalidate_caches(engine) is False  # unchanged
    box["marker"] = 8                                              # worker imported matches
    assert data_version.maybe_invalidate_caches(engine) is True
    assert not grounds._CACHE
    assert not similarity_cache._entries
