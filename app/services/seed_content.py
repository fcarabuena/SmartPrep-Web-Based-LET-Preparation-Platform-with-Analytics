"""Idempotent seeding of sample questions, resources and default badges."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Badge, Course, Question, Resource, Topic
from app.services.content import stem_hash
from app.services.seed_data.generators import generated_questions
from app.services.seed_data.questions import SAMPLE_QUESTIONS, SAMPLE_RESOURCES
from app.services.seed_data.questions_extra import EXTRA_QUESTIONS

DEFAULT_BADGES = [
    # code, name, description, icon, color, rule_type, threshold
    ("first_steps", "First Steps", "Completed your first quiz.", "flag", "primary", "first_attempt", 1),
    ("accuracy_ace", "Accuracy Ace", "Scored at least 75% on a quiz.", "bullseye", "success", "accuracy", 75),
    ("persistence_pro", "Persistence Pro", "Improved by 20 points or more over consecutive attempts.", "graph-up-arrow",
     "info", "improvement", 20),
    ("master_of_categories", "Master of Categories", "Scored at least 90% on a quiz in a category.", "mortarboard",
     "warning", "category_mastery", 90),
    ("perfect_score", "Perfect Score", "Scored 100% on a quiz.", "star-fill", "danger", "perfect", 100),
    ("streak_7", "Streak 7", "Studied 7 days in a row.", "fire", "danger", "streak", 7),
]


def _topic_id(db: Session, course: str, topic: str) -> int | None:
    return db.scalar(select(Topic.id).join(Course).where(Course.name == course, Topic.name == topic))


def _insert_questions(db: Session, bank: dict[tuple[str, str], list[tuple]], created_by_id: int | None = None) -> int:
    existing = set(db.scalars(select(Question.stem_hash)))
    created = 0
    for (course, topic), items in bank.items():
        tid = _topic_id(db, course, topic)
        if tid is None:
            continue
        for stem, a, b, c, d, correct, rat, diff, comp in items:
            h = stem_hash(stem)
            if h in existing:
                continue
            existing.add(h)
            db.add(Question(topic_id=tid, stem=stem, choice_a=a, choice_b=b, choice_c=c, choice_d=d, correct=correct,
                            rationalization=rat, difficulty=diff, competency=comp, source_type="manual",
                            status="approved", stem_hash=h, reviewed_at=utcnow(), created_by_id=created_by_id,
                            reviewed_by_id=created_by_id))
            created += 1
    db.commit()
    return created


def seed_extra_questions(db: Session, created_by_id: int | None = None) -> int:
    """Demo bank: 60 more handwritten items plus ~190 generated computation items."""
    return _insert_questions(db, EXTRA_QUESTIONS, created_by_id) + _insert_questions(db, generated_questions(),
                                                                                     created_by_id)


def seed_sample_questions(db: Session) -> dict[str, int]:
    created_r = 0
    created_q = _insert_questions(db, SAMPLE_QUESTIONS)
    for course, topic, title, kind, url, level, desc in SAMPLE_RESOURCES:
        if db.scalar(select(Resource.id).where(Resource.url == url)):
            continue
        db.add(Resource(title=title, kind=kind, url=url, topic_id=_topic_id(db, course, topic), level=level,
                        description=desc, approved=True))
        created_r += 1
    db.commit()
    return {"questions": created_q, "resources": created_r}


def seed_badges(db: Session) -> int:
    created = 0
    for code, name, desc, icon, color, rule, threshold in DEFAULT_BADGES:
        if db.scalar(select(Badge.id).where(Badge.code == code)):
            continue
        db.add(Badge(code=code, name=name, description=desc, icon=icon, color=color, rule_type=rule, threshold=threshold))
        created += 1
    db.commit()
    return created
