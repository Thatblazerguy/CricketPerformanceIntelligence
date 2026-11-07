"""Small process-local TTL cache for fitted similarity feature spaces."""
from threading import RLock
from time import monotonic


_lock = RLock()
_entries = {}
_TTL_SECONDS = 300


def get_or_build(key, builder):
    now = monotonic()
    with _lock:
        item = _entries.get(key)
        if item and now - item[0] < _TTL_SECONDS:
            return item[1]
    value = builder()
    with _lock:
        _entries[key] = (monotonic(), value)
    return value


def clear_similarity_cache():
    """Clear cached vectors after an ingestion or aggregate refresh."""
    with _lock:
        _entries.clear()
