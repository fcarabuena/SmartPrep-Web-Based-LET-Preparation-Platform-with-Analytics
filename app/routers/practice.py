"""Adaptive practice: Regenerate Questions, topic practice, Study Plan, quick quiz bee."""
import random

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_any, require_student
from app.models import Assessment, Attempt, Topic, User
from app.models.assessment import KIND_PRACTICE, KIND_QUIZ_BEE
from app.services.assessments import _create_attempt, load_attempt
from app.services.mastery import topic_stats
from app.services.recommendations import adaptive_question_ids, study_plan
from app.services.settings_store import threshold_for_attempt
from app.templating import flash, render

router = APIRouter(tags=["practice"])


def _start_adaptive(db: Session, user: User, ids: list[int], title: str, assessment: Assessment | None = None,
                    minutes: int | None = None, kind: str = KIND_PRACTICE) -> Attempt | None:
    if not ids:
        return None
    attempt = _create_attempt(db, user, ids, assessment, attempt_no=1, threshold=threshold_for_attempt(db, 1),
                              rng=random.Random(), is_adaptive=True, title=title, time_limit_minutes=minutes or 0)
    attempt.kind = kind
    db.commit()
    return attempt


@router.post("/attempts/{attempt_id:int}/regenerate", name="regenerate")
def regenerate(request: Request, attempt_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    """New adaptive set for the same scope, weighted to weak topics and avoiding recently seen items."""
    src = load_attempt(db, attempt_id)
    if not src or src.user_id != user.id:
        raise HTTPException(404, "Attempt not found")
    a = src.assessment
    n = src.total_questions or 10
    if a is not None:
        ids = adaptive_question_ids(db, user, n, topic_ids=[t.id for t in a.topics] or None,
                                    course_id=a.course_id, category_id=a.category_id)
        title = f"Adaptive: {a.title}"
        minutes = a.time_limit_minutes
    else:
        topic_ids = sorted({ans.question.topic_id for ans in src.answers})
        ids = adaptive_question_ids(db, user, n, topic_ids=topic_ids)
        title = src.title or "Adaptive Practice"
        minutes = None
    attempt = _start_adaptive(db, user, ids, title, a, minutes)
    if attempt is None:
        flash(request, "Not enough approved questions to build an adaptive set.", "warning")
        return RedirectResponse(f"/attempts/{attempt_id}/result", status_code=303)
    flash(request, "New adaptive set generated from your weakest topics.", "info")
    return RedirectResponse(f"/attempts/{attempt.id}", status_code=303)


@router.get("/practice/topic/{topic_id:int}")
@router.post("/practice/topic/{topic_id:int}")
def practice_topic(request: Request, topic_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    if request.method == "GET":
        topic = db.get(Topic, topic_id)
        if not topic:
            raise HTTPException(404, "Topic not found")
        return render(request, "practice/confirm.html", {"active": "study_plan", "topic": topic})
    topic = db.get(Topic, topic_id)
    if not topic or (topic.course.major and topic.course.major != user.major and not user.is_staff):
        raise HTTPException(404, "Topic not found")
    ids = adaptive_question_ids(db, user, 10, topic_ids=[topic_id])
    attempt = _start_adaptive(db, user, ids, f"Practice: {topic.name}")
    if attempt is None:
        flash(request, "No approved questions for this topic yet.", "warning")
        return RedirectResponse("/study-plan", status_code=303)
    return RedirectResponse(f"/attempts/{attempt.id}", status_code=303)


@router.post("/practice/adaptive")
def practice_adaptive(request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Mixed adaptive set across the student's weakest topics (Study Plan)."""
    plan = study_plan(db, user, limit=6)
    ids = adaptive_question_ids(db, user, 15, topic_ids=[p["topic"].id for p in plan] or None)
    attempt = _start_adaptive(db, user, ids, "Adaptive Review: weakest topics")
    if attempt is None:
        flash(request, "No approved questions available yet.", "warning")
        return RedirectResponse("/study-plan", status_code=303)
    return RedirectResponse(f"/attempts/{attempt.id}", status_code=303)


@router.post("/games/quick-quiz-bee")
def quick_quiz_bee(request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Instant quiz bee: random questions across all subjects against a 5-minute clock."""
    ids = adaptive_question_ids(db, user, 15)
    random.shuffle(ids)
    attempt = _start_adaptive(db, user, ids, "Quick Quiz Bee", minutes=5, kind=KIND_QUIZ_BEE)
    if attempt is None:
        flash(request, "No approved questions available yet.", "warning")
        return RedirectResponse("/gamification", status_code=303)
    return RedirectResponse(f"/attempts/{attempt.id}", status_code=303)


@router.get("/study-plan", name="study_plan")
def study_plan_page(request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
    plan = study_plan(db, user)
    stats = topic_stats(db, user.id)
    answered = sum(n for n, _ in stats.values())
    return render(request, "practice/study_plan.html", {"active": "study_plan", "plan": plan, "answered": answered})
