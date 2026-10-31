"""Tiny in-process TTL cache for heavy analytics queries (single Render instance)."""
import threading
import time
from collections.abc import Callable
from typing import Any

_store: dict[Any, tuple[float, Any]] = {}
_lock = threading.Lock()


def cached(key: Any, fn: Callable[[], Any], ttl: int = 60) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = fn()
    with _lock:
        _store[key] = (now + ttl, value)
        if len(_store) > 2000:  # crude bound
            for k in [k for k, (exp, _) in _store.items() if exp <= now]:
                _store.pop(k, None)
    return value


def clear_cache() -> None:
    with _lock:
        _store.clear()
