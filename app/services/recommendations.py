"""Rule-based recommendations and adaptive question selection.

Rules (from the capstone spec):
- Resources per topic are proportional to wrong answers in that topic (1 wrong = 1, 3 wrong = 3), capped.
- First priority: practice questions from the same topic; then videos/articles.
- Mastery < 75% -> foundational content and easier questions; 75-84% -> standard; >= 85% -> fewer, advanced/harder.
- Adaptive quiz: topic weight = (1 - mastery); difficulty mix by mastery; avoid recently seen questions.
"""
import random
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import utcnow
from app.models import Attempt, AttemptAnswer, Course, Question, Resource, ResourceView, Topic, User
from app.services.mastery import topic_mastery, topic_stats
from app.services.settings_store import get_setting

DEFAULT_UNSEEN_MASTERY = 50.0
DIFFICULTY_MIX = {
    "foundational": {"easy": 0.5, "medium": 0.4, "hard": 0.1},
    "standard": {"easy": 0.2, "medium": 0.5, "hard": 0.3},
    "advanced": {"easy": 0.1, "medium": 0.4, "hard": 0.5},
}


def level_for(mastery: float | None) -> str:
    if mastery is None or mastery < 75:
        return "foundational"
    if mastery < 85:
        return "standard"
    return "advanced"


def _resources_for_topic(db: Session, user: User, topic_id: int, level: str, n: int,
                         viewed: set[int] | None = None) -> list[Resource]:
    """Approved resources for a topic, preferring the target level and unviewed items; videos/articles first."""
    if n <= 0:
        return []
    rows = db.scalars(select(Resource).where(Resource.topic_id == topic_id, Resource.approved.is_(True))).all()
    if viewed is None:
        viewed = _viewed(db, user)
    kind_rank = {"video": 0, "article": 1, "file": 2, "link": 3}
    rows = sorted(rows, key=lambda r: (r.level != level, r.id in viewed, kind_rank.get(r.kind, 4), -r.view_count))
    return list(rows[:n])


def _viewed(db: Session, user: User) -> set[int]:
    return set(db.scalars(select(ResourceView.resource_id).where(ResourceView.user_id == user.id)))


def recommendations_for_attempt(db: Session, attempt: Attempt) -> dict:
    user = attempt.user
    cap = int(get_setting(db, "recommendation_cap") or 5)
    wrong_by_topic: dict[int, int] = defaultdict(int)
    for ans in attempt.answers:
        if not ans.is_correct:
            wrong_by_topic[ans.question.topic_id] += 1
    mastery = topic_mastery(db, user.id)
    topics, resources, seen = [], [], set()
    names = {t.id: t for t in db.scalars(select(Topic).where(Topic.id.in_(list(wrong_by_topic) or [0])))}
    for tid, wrong in sorted(wrong_by_topic.items(), key=lambda kv: -kv[1]):
        m = mastery.get(tid)
        level = level_for(m)
        n = min(wrong, cap)
        if level == "advanced":
            n = max(1, n // 2)  # fewer recommendations for strong topics
        available = db.scalar(select(func.count(Question.id)).where(Question.topic_id == tid,
                                                                    Question.status == "approved")) or 0
        topic = names.get(tid)
        topics.append({"id": tid, "name": topic.name if topic else "Topic", "wrong": wrong, "mastery": m or 0.0,
                       "level": level, "questions_available": available,
                       "practice_url": f"/practice/topic/{tid}" if available else None, "resource_count": n})
        for r in _resources_for_topic(db, user, tid, level, n):
            if r.id not in seen:
                seen.add(r.id)
                resources.append(r)
    return {"topics": topics, "resources": resources}


def recommended_resource_ids(db: Session, user: User) -> set[int]:
    """Resources currently recommended to the user (weak-topic resources); used to award view points."""
    out: set[int] = set()
    viewed = _viewed(db, user)
    for tid, m in topic_mastery(db, user.id).items():
        if m < 85:
            out.update(r.id for r in _resources_for_topic(db, user, tid, level_for(m), 5, viewed))
    return out


# ---------------------------------------------------------------- study plan

def study_plan(db: Session, user: User, limit: int = 12) -> list[dict]:
    """Weakest topics first (attempted topics by mastery, then not-yet-started topics)."""
    stats = topic_stats(db, user.id)
    topics = db.scalars(
        select(Topic).join(Course).options(selectinload(Topic.course).selectinload(Course.category))
        .where(or_(Course.major.is_(None), Course.major == (user.major or "__none__")))
    ).all()
    counts = dict(db.execute(select(Question.topic_id, func.count(Question.id)).where(Question.status == "approved")
                             .group_by(Question.topic_id)).all())
    plan = []
    for t in topics:
        available = counts.get(t.id, 0)
        answered, correct = stats.get(t.id, (0, 0))
        if not available and not answered:
            continue
        m = 100.0 * correct / answered if answered else None
        plan.append({"topic": t, "mastery": m, "answered": answered, "correct": correct, "available": available,
                     "level": level_for(m)})
    plan.sort(key=lambda p: (p["mastery"] is None, p["mastery"] if p["mastery"] is not None else 0, -p["available"]))
    plan = plan[:limit]
    viewed = _viewed(db, user)
    for p in plan:
        n = 1 if p["level"] == "advanced" else (2 if p["level"] == "standard" else 3)
        p["resources"] = _resources_for_topic(db, user, p["topic"].id, p["level"], n, viewed)
    return plan


# ---------------------------------------------------------------- adaptive selection

def _recent_question_ids(db: Session, user_id: int, days: int = 7) -> set[int]:
    since = utcnow() - timedelta(days=days)
    return set(db.scalars(
        select(AttemptAnswer.question_id).join(Attempt, AttemptAnswer.attempt_id == Attempt.id)
        .where(Attempt.user_id == user_id, Attempt.started_at >= since)
    ))


def adaptive_question_ids(db: Session, user: User, n: int, topic_ids: list[int] | None = None,
                          course_id: int | None = None, category_id: int | None = None,
                          rng: random.Random | None = None) -> list[int]:
    rng = rng or random.Random()
    stmt = (select(Question.id, Question.topic_id, Question.difficulty)
            .join(Topic, Question.topic_id == Topic.id).join(Course, Topic.course_id == Course.id)
            .where(Question.status == "approved",
                   or_(Course.major.is_(None), Course.major == (user.major or "__none__"))))
    if topic_ids:
        stmt = stmt.where(Question.topic_id.in_(topic_ids))
    elif course_id:
        stmt = stmt.where(Topic.course_id == course_id)
    elif category_id:
        stmt = stmt.where(Course.category_id == category_id)
    pool: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for qid, tid, diff in db.execute(stmt).all():
        pool[tid][diff].append(qid)
    if not pool:
        return []
    recent = _recent_question_ids(db, user.id)
    mastery = topic_mastery(db, user.id)
    weights = {tid: max(0.05, 1 - mastery.get(tid, DEFAULT_UNSEEN_MASTERY) / 100.0) for tid in pool}
    chosen: list[int] = []
    used: set[int] = set()
    total = sum(len(q) for d in pool.values() for q in d.values())
    n = min(n, total)
    while len(chosen) < n:
        live = [t for t in pool if any(q not in used for qs in pool[t].values() for q in qs)]
        if not live:
            break
        tid = rng.choices(live, weights=[weights[t] for t in live])[0]
        mix = DIFFICULTY_MIX[level_for(mastery.get(tid))]
        diffs = [d for d in mix if any(q not in used for q in pool[tid].get(d, []))]
        diff = rng.choices(diffs, weights=[mix[d] for d in diffs])[0]
        candidates = [q for q in pool[tid][diff] if q not in used]
        fresh = [q for q in candidates if q not in recent]
        qid = rng.choice(fresh or candidates)
        used.add(qid)
        chosen.append(qid)
    rng.shuffle(chosen)
    return chosen
