"""Role-specific dashboards."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import require_any
from app.models import Attempt, User
from app.services.analytics import admin_metrics, at_risk_students, class_overview, readiness, upcoming_deadlines
from app.services.assessments import expire_overdue
from app.services.gamification import level_info, my_rank, total_points, user_badges
from app.services.recommendations import study_plan
from app.templating import render

router = APIRouter(tags=["dashboard"])


def _student_ctx(db: Session, user: User) -> dict:
    expire_overdue(db, user.id)
    points = total_points(db, user.id)
    rank, of = my_rank(db, user.id)
    recent = db.scalars(select(Attempt).where(Attempt.user_id == user.id, Attempt.status == "submitted")
                        .options(selectinload(Attempt.assessment)).order_by(Attempt.submitted_at.desc()).limit(5)).all()
    in_progress = db.scalars(select(Attempt).where(Attempt.user_id == user.id, Attempt.status == "in_progress")
                             .options(selectinload(Attempt.assessment))).all()
    ctx = {
        "ready": readiness(db, user), "points": points, "level": level_info(db, points), "rank": rank, "of": of,
        "badges": user_badges(db, user.id)[:6], "deadlines": upcoming_deadlines(db, user), "recent": recent,
        "in_progress": in_progress, "plan": study_plan(db, user, limit=3),
        "completed": db.scalar(select(func.count(Attempt.id)).where(Attempt.user_id == user.id,
                                                                    Attempt.status == "submitted")) or 0,
        "goals": [],
    }
    try:
        from app.services.goals import goals_with_progress
    except ImportError:
        pass
    else:
        ctx["goals"] = goals_with_progress(db, user, active_only=True)[:3]
    return ctx


@router.get("/dashboard", name="dashboard")
def dashboard(request: Request, user: User = Depends(require_any), db: Session = Depends(get_db)):
    if user.role == "admin":
        return render(request, "dashboard/admin.html", {"active": "dashboard", "m": admin_metrics(db),
                                                        "c": class_overview(db, 30)})
    if user.role == "faculty":
        return render(request, "dashboard/faculty.html", {"active": "dashboard", "c": class_overview(db, 30),
                                                          "risk": at_risk_students(db)[:5],
                                                          "risk_count": len(at_risk_students(db))})
    return render(request, "dashboard/student.html", {"active": "dashboard", **_student_ctx(db, user)})
