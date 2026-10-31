"""Gamification hub, leaderboards and badge management."""
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import require_any, require_staff, require_student
from app.models import Badge, Category, Course, PointsLedger, User, UserBadge
from app.models.assessment import KIND_GAME, KIND_QUIZ_BEE
from app.models.gamification import BADGE_RULES, POINT_REASONS
from app.services.assessments import availability, visible_assessments
from app.services.gamification import (
    award_badge_manually,
    current_streak,
    leaderboard,
    level_info,
    my_rank,
    total_points,
    user_badges,
)
from app.services.settings_store import get_setting, set_setting
from app.templating import flash, render

router = APIRouter(tags=["gamification"])


@router.get("/gamification", name="gamification")
def hub(request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
    points = total_points(db, user.id)
    earned = user_badges(db, user.id)
    earned_ids = {ub.badge_id for ub in earned}
    locked = [b for b in db.scalars(select(Badge).where(Badge.is_active.is_(True)).order_by(Badge.id))
              if b.id not in earned_ids]
    history = db.scalars(select(PointsLedger).where(PointsLedger.user_id == user.id)
                         .order_by(PointsLedger.created_at.desc()).limit(15)).all()
    games = [{"a": a, "av": availability(db, a, user)} for a in visible_assessments(db, user, (KIND_GAME, KIND_QUIZ_BEE))]
    public = get_setting(db, "leaderboard_public")
    rank, of = my_rank(db, user.id)
    return render(request, "gamification/hub.html", {
        "active": "gamification", "points": points, "level": level_info(db, points), "earned": earned,
        "locked": locked, "history": history, "reasons": POINT_REASONS, "games": games,
        "streak": current_streak(db, user.id), "rank": rank, "of": of,
        "top": leaderboard(db, "overall", limit=5) if public else [], "public": public, "rules": BADGE_RULES,
    })


@router.get("/leaderboards", name="leaderboards")
def leaderboards(request: Request, scope: str = "overall", ref: int = 0, user: User = Depends(require_any),
                 db: Session = Depends(get_db)):
    public = get_setting(db, "leaderboard_public")
    if user.role == "student" and not public:
        return render(request, "gamification/leaderboards.html", {"active": "gamification", "hidden": True})
    if scope not in ("overall", "category", "course", "game"):
        scope = "overall"
    categories = db.scalars(select(Category).order_by(Category.sort_order)).all()
    courses = [c for c in db.scalars(select(Course).order_by(Course.category_id, Course.sort_order))
               if user.is_staff or not c.major or c.major == user.major]
    games = [a for a in visible_assessments(db, user) if a.leaderboard_public or user.is_staff]
    if scope in ("category", "course", "game") and not ref:
        first = {"category": categories, "course": courses, "game": games}[scope]
        ref = first[0].id if first else 0
    rows = leaderboard(db, scope, ref)
    return render(request, "gamification/leaderboards.html", {
        "active": "leaderboards" if user.is_staff else "gamification", "rows": rows, "scope": scope, "ref": ref,
        "categories": categories, "courses": courses, "games": games, "public": public, "hidden": False,
    })


@router.post("/leaderboards/visibility")
def leaderboard_visibility(request: Request, public: str = Form("false"), user: User = Depends(require_staff),
                           db: Session = Depends(get_db)):
    set_setting(db, "leaderboard_public", public == "true")
    flash(request, "Leaderboards are now " + ("visible to students." if public == "true" else "hidden from students."))
    return RedirectResponse("/leaderboards", status_code=303)


# ---------------------------------------------------------------- badges (staff)

@router.get("/badges", name="badges_admin")
def badges_page(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    badges = db.scalars(select(Badge).order_by(Badge.id)).all()
    counts = dict(db.execute(select(UserBadge.badge_id, func.count(UserBadge.id)).group_by(UserBadge.badge_id)).all())
    recent = db.scalars(select(UserBadge).options(selectinload(UserBadge.badge))
                        .order_by(UserBadge.awarded_at.desc()).limit(10)).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_([r.user_id for r in recent] or [0])))}
    students = db.scalars(select(User).where(User.role == "student", User.is_active.is_(True)).order_by(User.full_name)).all()
    return render(request, "gamification/badges.html", {
        "active": "badges_admin", "badges": badges, "counts": counts, "rules": BADGE_RULES, "recent": recent,
        "names": names, "students": students,
    })


def _badge_fields(name: str, description: str, icon: str, color: str, rule_type: str, threshold: float) -> dict:
    name = name.strip()
    if not (2 <= len(name) <= 100):
        raise HTTPException(400, "Badge name must be 2–100 characters.")
    if rule_type not in BADGE_RULES:
        raise HTTPException(400, "Unknown badge rule.")
    icon = re.sub(r"[^a-z0-9-]", "", icon.lower()) or "award"
    color = color if color in ("primary", "success", "info", "warning", "danger", "secondary", "dark") else "primary"
    return {"name": name, "description": description.strip()[:500], "icon": icon, "color": color,
            "rule_type": rule_type, "threshold": max(0.0, threshold)}


@router.post("/badges")
def create_badge(request: Request, name: str = Form(""), description: str = Form(""), icon: str = Form("award"),
                 color: str = Form("primary"), rule_type: str = Form("manual"), threshold: float = Form(0),
                 user: User = Depends(require_staff), db: Session = Depends(get_db)):
    fields = _badge_fields(name, description, icon, color, rule_type, threshold)
    code = re.sub(r"[^a-z0-9]+", "_", fields["name"].lower()).strip("_")[:40] or "badge"
    base, i = code, 2
    while db.scalar(select(Badge.id).where(Badge.code == code)):
        code, i = f"{base}_{i}", i + 1
    db.add(Badge(code=code, created_by_id=user.id, **fields))
    db.commit()
    flash(request, f"Badge “{fields['name']}” created.")
    return RedirectResponse("/badges", status_code=303)


@router.post("/badges/{badge_id:int}/edit")
def edit_badge(request: Request, badge_id: int, name: str = Form(""), description: str = Form(""),
               icon: str = Form("award"), color: str = Form("primary"), rule_type: str = Form("manual"),
               threshold: float = Form(0), is_active: bool = Form(False), user: User = Depends(require_staff),
               db: Session = Depends(get_db)):
    b = db.get(Badge, badge_id)
    if not b:
        raise HTTPException(404, "Badge not found")
    for k, v in _badge_fields(name, description, icon, color, rule_type, threshold).items():
        setattr(b, k, v)
    b.is_active = is_active
    db.commit()
    flash(request, "Badge updated.")
    return RedirectResponse("/badges", status_code=303)


@router.post("/badges/{badge_id:int}/award")
def award_badge(request: Request, badge_id: int, student_id: int = Form(...), user: User = Depends(require_staff),
                db: Session = Depends(get_db)):
    b = db.get(Badge, badge_id)
    student = db.get(User, student_id)
    if not b or not student or student.role != "student":
        raise HTTPException(404, "Not found")
    if award_badge_manually(db, student, b, user):
        flash(request, f"Awarded “{b.name}” to {student.full_name}.")
    else:
        flash(request, f"{student.full_name} already has “{b.name}”.", "info")
    return RedirectResponse("/badges", status_code=303)


@router.get("/api/me/points")
def my_points(user: User = Depends(require_any), db: Session = Depends(get_db)):
    pts = total_points(db, user.id)
    lv = level_info(db, pts)
    return {"points": pts, "level": lv.level, "progress_pct": lv.progress_pct}

