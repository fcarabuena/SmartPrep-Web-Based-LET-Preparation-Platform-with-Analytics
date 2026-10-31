"""Admin-configurable system settings with defaults (stored as JSON in system_settings)."""
import json
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from app.models import SystemSetting

DEFAULTS: dict[str, Any] = {
    # pass threshold per attempt number (attempt 3+ uses the last value)
    "pass_thresholds": [75, 80, 85],
    # LET readiness weights per track (percent; categories by code)
    "readiness_weights": {
        "secondary": {"gen_ed": 20, "prof_ed": 40, "major": 40},
        "elementary": {"gen_ed": 40, "prof_ed": 60, "major": 0},
    },
    "readiness_bands": {"developing": 60, "ready": 75},
    "at_risk_inactive_days": 7,
    "at_risk_readiness": 60,
    "points": {
        "complete_quiz": 5,
        "pass": 10,
        "perfect_score": 20,
        "improvement": 10,
        "quiz_series": 15,
        "series_count": 3,
        "series_window_hours": 24,
        "resource_view": 2,
        "resource_daily_cap": 10,
        "daily_streak": 3,
    },
    "level_step": 100,  # points per level (level n needs step * n*(n-1)/2)
    "leaderboard_public": True,
    "allow_registration": True,
    "recommendation_cap": 5,
}

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
TTL = 30


def get_setting(db: Session, key: str) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    row = db.get(SystemSetting, key)
    value = DEFAULTS.get(key)
    if row is not None:
        try:
            value = json.loads(row.value)
        except ValueError:
            pass
    if isinstance(DEFAULTS.get(key), dict) and isinstance(value, dict):
        value = {**DEFAULTS[key], **value}
    with _lock:
        _cache[key] = (now + TTL, value)
    return value


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=json.dumps(value)))
    else:
        row.value = json.dumps(value)
    db.commit()
    with _lock:
        _cache.pop(key, None)


def clear_settings_cache() -> None:
    with _lock:
        _cache.clear()


def threshold_for_attempt(db: Session, attempt_no: int) -> float:
    ts = get_setting(db, "pass_thresholds") or [75, 80, 85]
    idx = min(max(attempt_no, 1), len(ts)) - 1
    return float(ts[idx])
