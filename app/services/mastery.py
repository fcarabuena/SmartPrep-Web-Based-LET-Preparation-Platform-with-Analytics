"""Mastery aggregation (SQL): answered/correct per topic, course and category for one or many users."""
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Attempt, AttemptAnswer, Course, Question, Topic

CORRECT = func.sum(case((AttemptAnswer.is_correct.is_(True), 1), else_=0))


def _base(user_id: int | None):
    stmt = (
        select()
        .select_from(AttemptAnswer)
        .join(Attempt, AttemptAnswer.attempt_id == Attempt.id)
        .join(Question, AttemptAnswer.question_id == Question.id)
        .where(Attempt.status == "submitted")
    )
    if user_id is not None:
        stmt = stmt.where(Attempt.user_id == user_id)
    return stmt


def topic_stats(db: Session, user_id: int) -> dict[int, tuple[int, int]]:
    """{topic_id: (answered, correct)} across all submitted attempts of the user."""
    stmt = _base(user_id).add_columns(Question.topic_id, func.count(AttemptAnswer.id), CORRECT).group_by(Question.topic_id)
    return {tid: (n, int(c or 0)) for tid, n, c in db.execute(stmt).all()}


def topic_mastery(db: Session, user_id: int) -> dict[int, float]:
    """{topic_id: mastery 0-100}."""
    return {tid: 100.0 * c / n for tid, (n, c) in topic_stats(db, user_id).items() if n}


def course_stats(db: Session, user_id: int | None = None) -> dict[int, tuple[int, int]]:
    stmt = (_base(user_id).join(Topic, Question.topic_id == Topic.id)
            .add_columns(Topic.course_id, func.count(AttemptAnswer.id), CORRECT).group_by(Topic.course_id))
    return {cid: (n, int(c or 0)) for cid, n, c in db.execute(stmt).all()}


def category_stats(db: Session, user_id: int | None = None) -> dict[int, tuple[int, int]]:
    stmt = (_base(user_id).join(Topic, Question.topic_id == Topic.id).join(Course, Topic.course_id == Course.id)
            .add_columns(Course.category_id, func.count(AttemptAnswer.id), CORRECT).group_by(Course.category_id))
    return {cid: (n, int(c or 0)) for cid, n, c in db.execute(stmt).all()}


def category_mastery_by_user(db: Session, user_ids: list[int] | None = None) -> dict[int, dict[int, tuple[int, int]]]:
    """{user_id: {category_id: (answered, correct)}} in one grouped query (class analytics)."""
    stmt = (
        select(Attempt.user_id, Course.category_id, func.count(AttemptAnswer.id), CORRECT)
        .select_from(AttemptAnswer)
        .join(Attempt, AttemptAnswer.attempt_id == Attempt.id)
        .join(Question, AttemptAnswer.question_id == Question.id)
        .join(Topic, Question.topic_id == Topic.id)
        .join(Course, Topic.course_id == Course.id)
        .where(Attempt.status == "submitted")
        .group_by(Attempt.user_id, Course.category_id)
    )
    if user_ids is not None:
        stmt = stmt.where(Attempt.user_id.in_(user_ids))
    out: dict[int, dict[int, tuple[int, int]]] = {}
    for uid, cat, n, c in db.execute(stmt).all():
        out.setdefault(uid, {})[cat] = (n, int(c or 0))
    return out


def pct(answered: int, correct: int) -> float | None:
    return round(100.0 * correct / answered, 1) if answered else None

