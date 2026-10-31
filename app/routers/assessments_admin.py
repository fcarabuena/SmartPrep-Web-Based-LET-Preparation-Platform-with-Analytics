"""Staff: create/edit/publish assessments, pick questions, view submissions."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import require_staff
from app.models import (
    ASSESSMENT_KINDS,
    Assessment,
    AssessmentQuestion,
    Attempt,
    Category,
    Course,
    Question,
    Topic,
    User,
)
from app.services.assessments import question_counts_by_assessment, scope_filter
from app.services.content import topic_options
from app.templating import flash, fmt_input_dt, from_local, render

router = APIRouter(tags=["assessments-admin"])
PAGE_SIZE = 30


def _get(db: Session, aid: int) -> Assessment:
    a = db.scalar(select(Assessment).where(Assessment.id == aid).options(
        selectinload(Assessment.topics), selectinload(Assessment.course), selectinload(Assessment.category)))
    if not a:
        raise HTTPException(404, "Assessment not found")
    return a


@router.get("/assessments", name="assessments_admin")
def list_assessments(request: Request, kind: str = "", category: int = 0, q: str = "",
                     user: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = select(Assessment).options(selectinload(Assessment.course), selectinload(Assessment.category),
                                      selectinload(Assessment.topics))
    if kind in ASSESSMENT_KINDS:
        stmt = stmt.where(Assessment.kind == kind)
    if category:
        stmt = stmt.where(Assessment.category_id == category)
    if q:
        stmt = stmt.where(func.lower(Assessment.title).like(f"%{q.lower()}%"))
    items = db.scalars(stmt.order_by(Assessment.created_at.desc())).all()
    stats = dict(
        (aid, (n, avg, passed)) for aid, n, avg, passed in db.execute(
            select(Attempt.assessment_id, func.count(Attempt.id), func.avg(Attempt.score_pct),
                   func.sum(cast(Attempt.passed, Integer)))
            .where(Attempt.status == "submitted", Attempt.is_adaptive.is_(False)).group_by(Attempt.assessment_id)
        ).all()
    )
    return render(request, "assessments/admin_list.html", {
        "active": "assessments_admin", "items": items, "kinds": ASSESSMENT_KINDS, "kind": kind, "q": q,
        "category": category, "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "pool": question_counts_by_assessment(db, items), "stats": stats,
    })


def _form_ctx(db: Session, form: dict, a: Assessment | None = None, errors=None) -> dict:
    return {
        "active": "assessments_admin", "form": form, "a": a, "errors": errors or [], "kinds": ASSESSMENT_KINDS,
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "courses": db.scalars(select(Course).order_by(Course.category_id, Course.sort_order)).all(),
        "topic_groups": topic_options(db),
    }


DEFAULT_FORM = {
    "title": "", "kind": "practice", "description": "", "instructions": "", "category_id": 0, "course_id": 0,
    "topic_ids": [], "question_count": 10, "selection_mode": "auto", "difficulty": "mixed",
    "randomize_questions": True, "randomize_choices": False, "time_limit_minutes": "", "access_code": "",
    "open_at": "", "due_at": "", "max_attempts": "", "is_published": False, "points_per_correct": 1,
    "pass_bonus": 10, "leaderboard_public": True,
}


@router.get("/assessments/new")
def new_assessment(request: Request, kind: str = "practice", user: User = Depends(require_staff),
                   db: Session = Depends(get_db)):
    form = dict(DEFAULT_FORM, kind=kind if kind in ASSESSMENT_KINDS else "practice")
    if form["kind"] == "mock_exam":
        form.update(question_count=50, time_limit_minutes=60, max_attempts=3, randomize_choices=True,
                    instructions="Read each item carefully and choose the best answer. The timer starts when you begin "
                                 "and your answers are saved automatically. The exam is submitted when time runs out.")
    elif form["kind"] in ("game", "quiz_bee"):
        form.update(question_count=15, time_limit_minutes=5, randomize_choices=True)
    return render(request, "assessments/admin_form.html", _form_ctx(db, form))


def _parse_dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return from_local(datetime.fromisoformat(value))
    except ValueError:
        return None


def _opt_int(value) -> int | None:
    try:
        v = int(str(value).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


async def _read(request: Request, db: Session) -> tuple[dict, list[str]]:
    f = await request.form()
    form = {k: f.get(k, "") for k in DEFAULT_FORM}
    form["topic_ids"] = [int(t) for t in f.getlist("topic_ids") if str(t).isdigit()]
    for b in ("randomize_questions", "randomize_choices", "is_published", "leaderboard_public"):
        form[b] = f.get(b) == "true"
    errors = []
    form["title"] = str(form["title"]).strip()
    if not (3 <= len(form["title"]) <= 200):
        errors.append("Title must be 3–200 characters.")
    if form["kind"] not in ASSESSMENT_KINDS:
        errors.append("Invalid assessment type.")
    form["category_id"] = _opt_int(form["category_id"]) or 0
    form["course_id"] = _opt_int(form["course_id"]) or 0
    course = db.get(Course, form["course_id"]) if form["course_id"] else None
    if course:
        if form["category_id"] and course.category_id != form["category_id"]:
            errors.append("The course does not belong to the selected category.")
        form["category_id"] = course.category_id
    if form["topic_ids"]:
        topics = db.scalars(select(Topic).where(Topic.id.in_(form["topic_ids"]))).all()
        if course and any(t.course_id != course.id for t in topics):
            errors.append("Selected topics must belong to the selected course.")
    qc = _opt_int(form["question_count"])
    if not qc or qc > 200:
        errors.append("Question count must be between 1 and 200.")
    form["question_count"] = qc or 10
    if form["selection_mode"] not in ("auto", "manual"):
        form["selection_mode"] = "auto"
    if form["difficulty"] not in ("mixed", "easy", "medium", "hard"):
        form["difficulty"] = "mixed"
    form["time_limit_minutes"] = _opt_int(form["time_limit_minutes"])
    if form["time_limit_minutes"] and form["time_limit_minutes"] > 600:
        errors.append("Time limit must be at most 600 minutes.")
    form["max_attempts"] = _opt_int(form["max_attempts"])
    form["open_at_dt"], form["due_at_dt"] = _parse_dt(form["open_at"]), _parse_dt(form["due_at"])
    if form["open_at_dt"] and form["due_at_dt"] and form["due_at_dt"] <= form["open_at_dt"]:
        errors.append("Due date must be after the open date.")
    form["access_code"] = str(form["access_code"]).strip()[:40]
    form["points_per_correct"] = max(0, min(_opt_int(form["points_per_correct"]) or 0, 100))
    form["pass_bonus"] = max(0, min(_opt_int(form["pass_bonus"]) or 0, 1000))
    return form, errors


def _apply(a: Assessment, form: dict, db: Session) -> None:
    a.title, a.kind = form["title"], form["kind"]
    a.description = str(form["description"]).strip() or None
    a.instructions = str(form["instructions"]).strip() or None
    a.category_id = form["category_id"] or None
    a.course_id = form["course_id"] or None
    a.topics = list(db.scalars(select(Topic).where(Topic.id.in_(form["topic_ids"])))) if form["topic_ids"] else []
    a.question_count, a.selection_mode, a.difficulty = form["question_count"], form["selection_mode"], form["difficulty"]
    a.randomize_questions, a.randomize_choices = form["randomize_questions"], form["randomize_choices"]
    a.time_limit_minutes, a.max_attempts = form["time_limit_minutes"], form["max_attempts"]
    a.access_code = form["access_code"] or None
    a.open_at, a.due_at = form["open_at_dt"], form["due_at_dt"]
    a.points_per_correct, a.pass_bonus = form["points_per_correct"], form["pass_bonus"]
    a.leaderboard_public = form["leaderboard_public"]


@router.post("/assessments/new")
async def create_assessment(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    form, errors = await _read(request, db)
    if errors:
        return render(request, "assessments/admin_form.html", _form_ctx(db, form, errors=errors), status_code=400)
    a = Assessment(created_by_id=user.id, is_published=False)
    _apply(a, form, db)
    db.add(a)
    db.commit()
    if form["is_published"]:
        _publish(db, a)
    flash(request, "Assessment created." + (" Now pick its questions." if a.selection_mode == "manual" else ""))
    return RedirectResponse(f"/assessments/{a.id}/questions" if a.selection_mode == "manual" else "/assessments",
                            status_code=303)


@router.get("/assessments/{aid:int}/edit")
def edit_assessment(request: Request, aid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    a = _get(db, aid)
    form = {k: getattr(a, k) for k in DEFAULT_FORM if hasattr(a, k)}
    form.update(topic_ids=[t.id for t in a.topics], open_at=fmt_input_dt(a.open_at), due_at=fmt_input_dt(a.due_at),
                category_id=a.category_id or 0, course_id=a.course_id or 0,
                time_limit_minutes=a.time_limit_minutes or "", max_attempts=a.max_attempts or "",
                access_code=a.access_code or "", description=a.description or "", instructions=a.instructions or "")
    return render(request, "assessments/admin_form.html", _form_ctx(db, form, a))


@router.post("/assessments/{aid:int}/edit")
async def update_assessment(request: Request, aid: int, user: User = Depends(require_staff),
                            db: Session = Depends(get_db)):
    a = _get(db, aid)
    form, errors = await _read(request, db)
    if errors:
        return render(request, "assessments/admin_form.html", _form_ctx(db, form, a, errors), status_code=400)
    was_published = a.is_published
    _apply(a, form, db)
    db.commit()
    if form["is_published"] and not was_published:
        _publish(db, a)
    elif not form["is_published"] and was_published:
        a.is_published = False
        db.commit()
    flash(request, "Assessment updated.")
    return RedirectResponse("/assessments", status_code=303)


@router.post("/assessments/{aid:int}/publish")
def toggle_publish(request: Request, aid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    a = _get(db, aid)
    if a.is_published:
        a.is_published = False
        db.commit()
        flash(request, f"“{a.title}” unpublished.")
    else:
        _publish(db, a)
        flash(request, f"“{a.title}” published. Students can now see it.")
    return RedirectResponse(request.headers.get("referer") or "/assessments", status_code=303)


@router.post("/assessments/{aid:int}/delete")
def delete_assessment(request: Request, aid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    a = _get(db, aid)
    db.delete(a)
    db.commit()
    flash(request, "Assessment and its attempts deleted.")
    return RedirectResponse("/assessments", status_code=303)


def _publish(db: Session, a: Assessment) -> None:
    a.is_published = True
    db.commit()
    try:
        from app.services.notify import notify_assessment_published
    except ImportError:
        return
    notify_assessment_published(db, a)


# ---------------------------------------------------------------- manual question picking

@router.get("/assessments/{aid:int}/questions")
def pick_questions(request: Request, aid: int, q: str = "", topic: int = 0, difficulty: str = "",
                   user: User = Depends(require_staff), db: Session = Depends(get_db)):
    a = _get(db, aid)
    chosen = db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == a.id)
                        .options(selectinload(AssessmentQuestion.question)).order_by(AssessmentQuestion.position)).all()
    chosen_ids = {c.question_id for c in chosen}
    stmt = scope_filter(select(Question).where(Question.status == "approved"), a, None)
    if topic:
        stmt = stmt.where(Question.topic_id == topic)
    if difficulty in ("easy", "medium", "hard"):
        stmt = stmt.where(Question.difficulty == difficulty)
    if q:
        stmt = stmt.where(func.lower(Question.stem).like(f"%{q.lower()}%"))
    pool = [x for x in db.scalars(stmt.options(selectinload(Question.topic)).order_by(Question.id).limit(200))
            if x.id not in chosen_ids]
    return render(request, "assessments/pick.html", {
        "active": "assessments_admin", "a": a, "chosen": chosen, "pool": pool, "q": q, "topic": topic,
        "difficulty": difficulty, "topic_groups": topic_options(db),
    })


@router.post("/assessments/{aid:int}/questions")
async def update_picks(request: Request, aid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    a = _get(db, aid)
    f = await request.form()
    add = [int(i) for i in f.getlist("add") if str(i).isdigit()]
    remove = {int(i) for i in f.getlist("remove") if str(i).isdigit()}
    existing = db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == a.id)
                          .order_by(AssessmentQuestion.position)).all()
    for item in existing:
        if item.question_id in remove:
            db.delete(item)
    have = {i.question_id for i in existing if i.question_id not in remove}
    pos = max((i.position for i in existing), default=0) + 1
    valid = set(db.scalars(select(Question.id).where(Question.id.in_(add), Question.status == "approved"))) if add else set()
    for qid in add:
        if qid in valid and qid not in have:
            db.add(AssessmentQuestion(assessment_id=a.id, question_id=qid, position=pos))
            have.add(qid)
            pos += 1
    a.selection_mode = "manual"
    a.question_count = len(have)
    db.commit()
    flash(request, f"Question list updated: {len(have)} item(s).")
    return RedirectResponse(f"/assessments/{a.id}/questions", status_code=303)


# ---------------------------------------------------------------- submissions

@router.get("/submissions", name="submissions")
def submissions(request: Request, assessment: int = 0, q: str = "", result: str = "", page: int = 1,
                user: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = (select(Attempt).join(User, Attempt.user_id == User.id).where(Attempt.status == "submitted")
            .options(selectinload(Attempt.user), selectinload(Attempt.assessment)))
    if assessment:
        stmt = stmt.where(Attempt.assessment_id == assessment)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    if result == "passed":
        stmt = stmt.where(Attempt.passed.is_(True))
    elif result == "failed":
        stmt = stmt.where(Attempt.passed.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page = max(page, 1)
    items = db.scalars(stmt.order_by(Attempt.submitted_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    filters = {"assessment": assessment, "q": q, "result": result}
    return render(request, "assessments/submissions.html", {
        "active": "submissions", "items": items, "total": total, "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)), "filters": filters,
        "qs": "&".join(f"{k}={v}" for k, v in filters.items() if v),
        "assessments": db.scalars(select(Assessment).order_by(Assessment.title)).all(),
    })
