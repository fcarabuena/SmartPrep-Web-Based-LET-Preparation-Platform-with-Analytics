"""Student goals with automatic progress."""
from datetime import date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Attempt, AttemptAnswer, Course, Goal, PointsLedger, Question, Topic, User
from app.models.comms import GOAL_METRICS
from app.services.analytics import readiness
from app.services.notify import notify
from app.templating import LOCAL_OFFSET


def _start_utc(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time()) - LOCAL_OFFSET


def current_value(db: Session, user: User, goal: Goal) -> float:
    since = _start_utc(goal.start_date)
    sub = (Attempt.user_id == user.id, Attempt.status == "submitted", Attempt.submitted_at >= since)
    if goal.metric == "questions_answered":
        return float(db.scalar(select(func.count(AttemptAnswer.id)).join(Attempt, AttemptAnswer.attempt_id == Attempt.id)
                               .where(*sub)) or 0)
    if goal.metric == "quizzes_passed":
        return float(db.scalar(select(func.count(Attempt.id)).where(*sub, Attempt.passed.is_(True))) or 0)
    if goal.metric == "avg_score":
        v = db.scalar(select(func.avg(Attempt.score_pct)).where(*sub))
        return round(float(v), 1) if v is not None else 0.0
    if goal.metric == "points":
        return float(db.scalar(select(func.coalesce(func.sum(PointsLedger.points), 0)).where(
            PointsLedger.user_id == user.id, PointsLedger.created_at >= since)) or 0)
    if goal.metric == "readiness":
        return readiness(db, user)["score"]
    if goal.metric == "category_mastery" and goal.category_id:
        n, c = db.execute(
            select(func.count(AttemptAnswer.id), func.sum(case((AttemptAnswer.is_correct.is_(True), 1), else_=0)))
            .join(Attempt, AttemptAnswer.attempt_id == Attempt.id).join(Question, AttemptAnswer.question_id == Question.id)
            .join(Topic, Question.topic_id == Topic.id).join(Course, Topic.course_id == Course.id)
            .where(Attempt.user_id == user.id, Attempt.status == "submitted", Course.category_id == goal.category_id)
        ).one()
        return round(100.0 * (c or 0) / n, 1) if n else 0.0
    return 0.0


def goals_with_progress(db: Session, user: User, active_only: bool = False) -> list[dict]:
    stmt = select(Goal).where(Goal.user_id == user.id)
    goals = db.scalars(stmt.order_by(Goal.completed_at.is_not(None), Goal.deadline)).all()
    today = (utcnow() + LOCAL_OFFSET).date()
    out, newly = [], []
    for g in goals:
        cur = current_value(db, user, g)
        pct = min(100.0, 100.0 * cur / g.target_value) if g.target_value else 0.0
        if pct >= 100 and g.completed_at is None:
            g.completed_at = utcnow()
            newly.append(g)
        status = "done" if g.completed_at else ("overdue" if g.deadline < today else "active")
        if active_only and status != "active":
            continue
        cur_display = int(cur) if float(cur).is_integer() else cur
        out.append({"goal": g, "current": cur_display, "pct": round(pct, 1), "status": status,
                    "metric_label": GOAL_METRICS.get(g.metric, g.metric), "days_left": (g.deadline - today).days})
    if newly:
        db.commit()
        for g in newly:
            notify(db, user.id, f"Goal reached: {g.title}", "Great work! 🎯", "/goals", kind="goal",
                   dedupe_key=f"goal:{g.id}")
    return out
