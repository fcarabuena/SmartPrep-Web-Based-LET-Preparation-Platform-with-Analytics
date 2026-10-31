"""Assessment engine: question drawing, attempts with server-side deadlines, autosave, grading, grades."""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import utcnow
from app.models import (
    Assessment,
    AssessmentQuestion,
    Attempt,
    AttemptAnswer,
    Category,
    Course,
    Question,
    Topic,
    User,
)
from app.models.assessment import KIND_MOCK, KIND_PRACTICE
from app.models.content import CATEGORY_MAJOR
from app.services.settings_store import threshold_for_attempt

GRACE_SECONDS = 30  # network latency allowance after the deadline


class AttemptError(Exception):
    pass


# ------------------------------------------------------------------ visibility

def visible_to(a: Assessment, user: User) -> bool:
    """Students see published assessments of their courses; major courses only for that major."""
    if user.is_staff:
        return True
    if not a.is_published:
        return False
    if a.course is not None and a.course.major and a.course.major != user.major:
        return False
    if a.course is None and a.category is not None and a.category.code == CATEGORY_MAJOR and user.major == "elementary":
        return False
    return True


def visible_assessments(db: Session, user: User, kinds: tuple[str, ...] | None = None) -> list[Assessment]:
    stmt = (
        select(Assessment)
        .options(selectinload(Assessment.course), selectinload(Assessment.category))
        .order_by(Assessment.due_at.is_(None), Assessment.due_at, Assessment.created_at.desc())
    )
    if kinds:
        stmt = stmt.where(Assessment.kind.in_(kinds))
    if not user.is_staff:
        stmt = stmt.where(Assessment.is_published.is_(True))
    return [a for a in db.scalars(stmt) if visible_to(a, user)]


# ------------------------------------------------------------------ question pools

def scope_filter(stmt, a: Assessment, user: User | None):
    """Restrict a Question select to the assessment's scope (topics > course > category) and the user's major."""
    stmt = stmt.join(Topic, Question.topic_id == Topic.id).join(Course, Topic.course_id == Course.id)
    topic_ids = [t.id for t in a.topics]
    if topic_ids:
        stmt = stmt.where(Question.topic_id.in_(topic_ids))
    elif a.course_id:
        stmt = stmt.where(Topic.course_id == a.course_id)
    elif a.category_id:
        stmt = stmt.where(Course.category_id == a.category_id)
    if user is not None and not user.is_staff:
        stmt = stmt.where(or_(Course.major.is_(None), Course.major == (user.major or "__none__")))
    return stmt


def eligible_question_ids(db: Session, a: Assessment, user: User | None = None) -> list[int]:
    stmt = scope_filter(select(Question.id).where(Question.status == "approved"), a, user)
    if a.difficulty in ("easy", "medium", "hard"):
        stmt = stmt.where(Question.difficulty == a.difficulty)
    return list(db.scalars(stmt))


def draw_question_ids(db: Session, a: Assessment, user: User, rng: random.Random | None = None) -> list[int]:
    rng = rng or random.Random()
    if a.selection_mode == "manual":
        ids = [
            qid for qid in db.scalars(
                select(AssessmentQuestion.question_id).join(Question, AssessmentQuestion.question_id == Question.id)
                .where(AssessmentQuestion.assessment_id == a.id, Question.status == "approved")
                .order_by(AssessmentQuestion.position)
            )
        ]
    else:
        pool = eligible_question_ids(db, a, user)
        ids = rng.sample(pool, min(len(pool), max(a.question_count, 1)))
    if a.randomize_questions:
        rng.shuffle(ids)
    return ids


def _choice_order(randomize: bool, rng: random.Random) -> str:
    letters = list("ABCD")
    if randomize:
        rng.shuffle(letters)
    return "".join(letters)


# ------------------------------------------------------------------ availability

@dataclass
class Availability:
    can_start: bool
    status: str  # open | upcoming | past_due | max_reached | in_progress | unpublished | no_questions
    message: str
    attempts_used: int
    in_progress: Attempt | None = None


def submitted_attempts(db: Session, a: Assessment, user: User, include_adaptive: bool = False) -> list[Attempt]:
    stmt = select(Attempt).where(Attempt.assessment_id == a.id, Attempt.user_id == user.id,
                                 Attempt.status == "submitted")
    if not include_adaptive:
        stmt = stmt.where(Attempt.is_adaptive.is_(False))
    return list(db.scalars(stmt.order_by(Attempt.attempt_no)))


def availability(db: Session, a: Assessment, user: User) -> Availability:
    now = utcnow()
    in_progress = db.scalar(select(Attempt).where(Attempt.assessment_id == a.id, Attempt.user_id == user.id,
                                                  Attempt.status == "in_progress", Attempt.is_adaptive.is_(False)))
    used = len(submitted_attempts(db, a, user))
    if in_progress:
        return Availability(True, "in_progress", "You have an attempt in progress.", used, in_progress)
    if not a.is_published and not user.is_staff:
        return Availability(False, "unpublished", "This assessment is not available.", used)
    if a.open_at and now < a.open_at:
        return Availability(False, "upcoming", "This assessment is not open yet.", used)
    if a.due_at and now > a.due_at:
        return Availability(False, "past_due", "Past due.", used)
    if a.max_attempts and used >= a.max_attempts:
        return Availability(False, "max_reached", f"You have used all {a.max_attempts} attempt(s).", used)
    return Availability(True, "open", "Open", used)


# ------------------------------------------------------------------ attempts

def start_attempt(db: Session, a: Assessment, user: User, access_code: str = "", rng: random.Random | None = None) -> Attempt:
    if not visible_to(a, user):
        raise AttemptError("This assessment is not available to you.")
    av = availability(db, a, user)
    if av.in_progress:
        return av.in_progress
    if not av.can_start:
        raise AttemptError(av.message)
    if a.access_code and access_code.strip() != a.access_code.strip():
        raise AttemptError("Incorrect access code.")
    rng = rng or random.Random()
    ids = draw_question_ids(db, a, user, rng)
    if not ids:
        raise AttemptError("No approved questions are available for this assessment yet.")
    attempt_no = av.attempts_used + 1
    return _create_attempt(db, user, ids, a, attempt_no, threshold_for_attempt(db, attempt_no), rng, is_adaptive=False)


def _create_attempt(db: Session, user: User, ids: list[int], a: Assessment | None, attempt_no: int, threshold: float,
                    rng: random.Random, is_adaptive: bool, title: str | None = None,
                    time_limit_minutes: int | None = None) -> Attempt:
    now = utcnow()
    deadline = None
    limit = time_limit_minutes if time_limit_minutes is not None else (a.time_limit_minutes if a else None)
    if limit:
        deadline = now + timedelta(minutes=limit)
    if a and a.due_at and not is_adaptive:
        deadline = min(deadline, a.due_at) if deadline else a.due_at
    attempt = Attempt(
        user_id=user.id, assessment_id=a.id if a else None, attempt_no=attempt_no,
        kind=a.kind if a else KIND_PRACTICE, is_adaptive=is_adaptive, title=title, status="in_progress",
        started_at=now, deadline_at=deadline, total_questions=len(ids), threshold=threshold,
    )
    randomize_choices = a.randomize_choices if a else True
    attempt.answers = [
        AttemptAnswer(question_id=qid, position=i, choice_order=_choice_order(randomize_choices, rng))
        for i, qid in enumerate(ids)
    ]
    db.add(attempt)
    db.commit()
    return attempt


def is_expired(attempt: Attempt, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return bool(attempt.deadline_at and now > attempt.deadline_at + timedelta(seconds=GRACE_SECONDS))


def save_answers(db: Session, attempt: Attempt, answers: dict, times: dict | None = None) -> None:
    """Autosave: answers {answer_id: 'A'..'D' or ''}, times {answer_id: seconds spent since last save}."""
    if attempt.status != "in_progress":
        raise AttemptError("This attempt has already been submitted.")
    if is_expired(attempt):
        submit_attempt(db, attempt, auto=True)
        raise AttemptError("Time is up. Your attempt was submitted automatically.")
    by_id = {ans.id: ans for ans in attempt.answers}
    now = utcnow()
    for key, letter in (answers or {}).items():
        ans = by_id.get(_int(key))
        if ans is None:
            continue
        letter = (letter or "").upper()
        if letter in ("A", "B", "C", "D"):
            if ans.chosen != letter:
                ans.chosen, ans.answered_at = letter, now
        elif letter == "":
            ans.chosen = None
    for key, secs in (times or {}).items():
        ans = by_id.get(_int(key))
        s = _int(secs)
        if ans is not None and 0 < s <= 3600:
            ans.time_spent_seconds = (ans.time_spent_seconds or 0) + s
    attempt.last_saved_at = now
    db.commit()


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def submit_attempt(db: Session, attempt: Attempt, auto: bool = False) -> Attempt:
    if attempt.status == "submitted":
        return attempt
    now = utcnow()
    answers = db.scalars(
        select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id).options(selectinload(AttemptAnswer.question))
    ).all()
    correct = 0
    for ans in answers:
        ans.is_correct = ans.chosen is not None and ans.chosen == ans.question.correct
        correct += int(bool(ans.is_correct))
    total = len(answers)
    end = min(now, attempt.deadline_at) if attempt.deadline_at else now
    attempt.correct_count = correct
    attempt.total_questions = total
    attempt.score_pct = round(100.0 * correct / total, 2) if total else 0.0
    attempt.passed = attempt.score_pct >= attempt.threshold
    attempt.submitted_at = end
    attempt.time_spent_seconds = max(0, int((end - attempt.started_at).total_seconds()))
    attempt.status = "submitted"
    attempt.auto_submitted = auto
    db.commit()
    try:
        from app.services.gamification import on_attempt_submitted
    except ImportError:
        pass
    else:
        on_attempt_submitted(db, attempt)
    return attempt


def expire_overdue(db: Session, user_id: int | None = None) -> int:
    """Lazily auto-submit attempts whose deadline has passed (called on page loads; no cron)."""
    cutoff = utcnow() - timedelta(seconds=GRACE_SECONDS)
    stmt = select(Attempt).where(Attempt.status == "in_progress", Attempt.deadline_at.is_not(None),
                                 Attempt.deadline_at < cutoff)
    if user_id is not None:
        stmt = stmt.where(Attempt.user_id == user_id)
    n = 0
    for attempt in db.scalars(stmt).all():
        submit_attempt(db, attempt, auto=True)
        n += 1
    return n


def load_attempt(db: Session, attempt_id: int) -> Attempt | None:
    return db.scalar(
        select(Attempt).where(Attempt.id == attempt_id).options(
            selectinload(Attempt.answers).selectinload(AttemptAnswer.question).selectinload(Question.topic)
            .selectinload(Topic.course),
            selectinload(Attempt.assessment).selectinload(Assessment.category),
        )
    )


# ------------------------------------------------------------------ grades

@dataclass
class GradeRow:
    assessment: Assessment
    status: str  # Passed | Failed | Missing | Not attempted | In progress
    best: Attempt | None
    attempts: int
    first_attempt_passed: bool


def grade_rows(db: Session, user: User, category_id: int = 0, course_id: int = 0) -> list[GradeRow]:
    items = [a for a in visible_assessments(db, user) if a.is_published]
    if category_id:
        items = [a for a in items if a.category_id == category_id or (a.course and a.course.category_id == category_id)]
    if course_id:
        items = [a for a in items if a.course_id == course_id]
    if not items:
        return []
    ids = [a.id for a in items]
    attempts = db.scalars(select(Attempt).where(Attempt.user_id == user.id, Attempt.assessment_id.in_(ids),
                                                Attempt.is_adaptive.is_(False))).all()
    by_a: dict[int, list[Attempt]] = {}
    for at in attempts:
        by_a.setdefault(at.assessment_id, []).append(at)
    now = utcnow()
    rows = []
    for a in items:
        ats = by_a.get(a.id, [])
        done = [x for x in ats if x.status == "submitted"]
        best = max(done, key=lambda x: (x.score_pct or 0, -x.attempt_no)) if done else None
        if best:
            status = "Passed" if any(x.passed for x in done) else "Failed"
        elif any(x.status == "in_progress" for x in ats):
            status = "In progress"
        elif a.due_at and a.due_at < now:
            status = "Missing"
        else:
            status = "Not attempted"
        first = next((x for x in done if x.attempt_no == 1), None)
        rows.append(GradeRow(a, status, best, len(done), bool(first and first.passed)))
    return rows


def categories_with_courses(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).options(selectinload(Category.courses)).order_by(Category.sort_order)))


def question_counts_by_assessment(db: Session, assessments: list[Assessment]) -> dict[int, int]:
    """Number of approved questions available for each assessment (for staff lists)."""
    out = {}
    for a in assessments:
        if a.selection_mode == "manual":
            out[a.id] = db.scalar(select(func.count(AssessmentQuestion.id)).where(AssessmentQuestion.assessment_id == a.id)) or 0
        else:
            out[a.id] = len(eligible_question_ids(db, a))
    return out


EXAM_TABS = [("prof_ed", "Professional Education"), ("major", "Major Core"), ("gen_ed", "General Education")]
KIND_EXAM = KIND_MOCK
