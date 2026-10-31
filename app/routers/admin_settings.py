"""Admin: system settings (pass thresholds, readiness weights, points, toggles)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin
from app.models import User
from app.services.settings_store import DEFAULTS, get_setting, set_setting
from app.templating import flash, render

router = APIRouter(prefix="/admin/settings", tags=["admin"])

POINT_LABELS = {
    "complete_quiz": "Complete a quiz",
    "pass": "Pass a quiz (plus the assessment's pass bonus)",
    "perfect_score": "Perfect score",
    "improvement": "Improve on previous attempt",
    "quiz_series": "Series bonus",
    "series_count": "Quizzes needed for a series",
    "series_window_hours": "Series time window (hours)",
    "resource_view": "View a recommended resource",
    "resource_daily_cap": "Max resource-view points per day",
    "daily_streak": "Daily streak (per consecutive day)",
}


def _ctx(db: Session, errors=None) -> dict:
    return {
        "active": "admin_settings", "errors": errors or [],
        "thresholds": get_setting(db, "pass_thresholds"),
        "weights": get_setting(db, "readiness_weights"),
        "bands": get_setting(db, "readiness_bands"),
        "points": get_setting(db, "points"), "point_labels": POINT_LABELS,
        "level_step": get_setting(db, "level_step"),
        "at_risk_inactive_days": get_setting(db, "at_risk_inactive_days"),
        "at_risk_readiness": get_setting(db, "at_risk_readiness"),
        "leaderboard_public": get_setting(db, "leaderboard_public"),
        "allow_registration": get_setting(db, "allow_registration"),
        "recommendation_cap": get_setting(db, "recommendation_cap"),
    }


@router.get("", name="admin_settings")
def settings_page(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return render(request, "admin/settings.html", _ctx(db))


def _num(form, key: str, default: float, lo: float, hi: float, errors: list, label: str) -> float:
    try:
        v = float(form.get(key, default))
    except (TypeError, ValueError):
        errors.append(f"{label} must be a number.")
        return default
    if not lo <= v <= hi:
        errors.append(f"{label} must be between {lo:g} and {hi:g}.")
    return v


@router.post("")
async def save_settings(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    f = await request.form()
    errors: list[str] = []
    thresholds = [_num(f, f"threshold_{i}", 75, 1, 100, errors, f"Attempt {i} threshold") for i in (1, 2, 3)]
    weights = {
        "secondary": {k: _num(f, f"w_secondary_{k}", 0, 0, 100, errors, f"Secondary {k} weight")
                      for k in ("gen_ed", "prof_ed", "major")},
        "elementary": {k: _num(f, f"w_elementary_{k}", 0, 0, 100, errors, f"Elementary {k} weight")
                       for k in ("gen_ed", "prof_ed", "major")},
    }
    for track, w in weights.items():
        if abs(sum(w.values()) - 100) > 0.01:
            errors.append(f"{track.capitalize()} readiness weights must add up to 100 (now {sum(w.values()):g}).")
    bands = {"developing": _num(f, "band_developing", 60, 1, 100, errors, "Developing band"),
             "ready": _num(f, "band_ready", 75, 1, 100, errors, "Ready band")}
    if bands["developing"] >= bands["ready"]:
        errors.append("The 'Developing' band must start below the 'Ready' band.")
    points = {k: int(_num(f, f"pt_{k}", DEFAULTS["points"][k], 0, 1000, errors, POINT_LABELS[k])) for k in POINT_LABELS}
    level_step = int(_num(f, "level_step", 100, 10, 10000, errors, "Points per level step"))
    inactive = int(_num(f, "at_risk_inactive_days", 7, 1, 90, errors, "Inactive days"))
    risk_ready = _num(f, "at_risk_readiness", 60, 0, 100, errors, "At-risk readiness")
    cap = int(_num(f, "recommendation_cap", 5, 1, 20, errors, "Recommendation cap"))
    if errors:
        return render(request, "admin/settings.html", _ctx(db, errors), status_code=400)
    set_setting(db, "pass_thresholds", [round(t, 2) for t in thresholds])
    set_setting(db, "readiness_weights", weights)
    set_setting(db, "readiness_bands", bands)
    set_setting(db, "points", points)
    set_setting(db, "level_step", level_step)
    set_setting(db, "at_risk_inactive_days", inactive)
    set_setting(db, "at_risk_readiness", risk_ready)
    set_setting(db, "recommendation_cap", cap)
    set_setting(db, "leaderboard_public", f.get("leaderboard_public") == "true")
    set_setting(db, "allow_registration", f.get("allow_registration") == "true")
    flash(request, "Settings saved.")
    return RedirectResponse("/admin/settings", status_code=303)
