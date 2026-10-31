"""Question bank: list/search/filter, create/edit with duplicate check, review queue, CSV/Excel import."""
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db, utcnow
from app.deps import require_staff
from app.models import AttemptAnswer, Category, Course, Question, Topic, User
from app.models.content import DIFFICULTIES, QUESTION_STATUSES, SOURCE_TYPES
from app.services.content import apply_question, find_duplicates, stem_hash, topic_options, validate_question
from app.services.importer import parse_file, template_csv, template_xlsx, validate_rows
from app.templating import flash, render

router = APIRouter(tags=["questions"])
PAGE_SIZE = 20
FIELDS = ("stem", "choice_a", "choice_b", "choice_c", "choice_d", "correct", "rationalization", "difficulty",
          "competency", "source_url")


def _filtered(stmt, q, category, course, topic, difficulty, status, source):
    stmt = stmt.join(Topic, Question.topic_id == Topic.id).join(Course, Topic.course_id == Course.id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Question.stem).like(like), func.lower(Question.competency).like(like)))
    if category:
        stmt = stmt.where(Course.category_id == category)
    if course:
        stmt = stmt.where(Topic.course_id == course)
    if topic:
        stmt = stmt.where(Question.topic_id == topic)
    if difficulty in DIFFICULTIES:
        stmt = stmt.where(Question.difficulty == difficulty)
    if status in QUESTION_STATUSES:
        stmt = stmt.where(Question.status == status)
    if source in SOURCE_TYPES:
        stmt = stmt.where(Question.source_type == source)
    return stmt


def _load_opts():
    return (selectinload(Question.topic).selectinload(Topic.course).selectinload(Course.category),
            selectinload(Question.created_by))


@router.get("/questions", name="question_bank")
def bank(request: Request, q: str = "", category: int = 0, course: int = 0, topic: int = 0, difficulty: str = "",
         status: str = "", source: str = "", page: int = 1,
         user: User = Depends(require_staff), db: Session = Depends(get_db)):
    base = _filtered(select(Question), q, category, course, topic, difficulty, status, source)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    page = max(page, 1)
    items = db.scalars(base.options(*_load_opts()).order_by(Question.created_at.desc(), Question.id.desc())
                       .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    status_counts = dict(db.execute(select(Question.status, func.count(Question.id)).group_by(Question.status)).all())
    filters = {"q": q, "category": category, "course": course, "topic": topic, "difficulty": difficulty,
               "status": status, "source": source}
    qs = "&".join(f"{k}={v}" for k, v in filters.items() if v)
    return render(request, "questions/bank.html", {
        "active": "question_bank", "items": items, "total": total, "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)), "filters": filters, "qs": qs, "status_counts": status_counts,
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "courses": db.scalars(select(Course).order_by(Course.category_id, Course.sort_order)).all(),
        "topic_groups": topic_options(db), "difficulties": DIFFICULTIES, "statuses": QUESTION_STATUSES,
        "sources": SOURCE_TYPES,
    })


def _form_ctx(db: Session, form: dict, question: Question | None = None, errors=None, duplicates=None) -> dict:
    return {"active": "question_bank", "form": form, "question": question, "errors": errors or [],
            "duplicates": duplicates or [], "topic_groups": topic_options(db), "difficulties": DIFFICULTIES,
            "statuses": QUESTION_STATUSES}


@router.get("/questions/new")
def new_question(request: Request, topic: int = 0, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return render(request, "questions/form.html", _form_ctx(db, {"topic_id": topic, "difficulty": "medium",
                                                                  "status": "approved", "correct": "A"}))


async def _read_form(request: Request) -> dict:
    form = await request.form()
    data = {k: str(form.get(k, "")) for k in FIELDS}
    data["topic_id"] = str(form.get("topic_id", ""))
    data["status"] = str(form.get("status", "draft"))
    data["allow_similar"] = form.get("allow_similar") == "1"
    return data


def _check_topic(db: Session, data: dict, errors: list) -> int | None:
    try:
        tid = int(data.get("topic_id") or 0)
    except ValueError:
        tid = 0
    if not tid or not db.get(Topic, tid):
        errors.append("Please choose a topic.")
        return None
    return tid


@router.post("/questions/new")
async def create_question(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    data = await _read_form(request)
    errors = validate_question(data)
    tid = _check_topic(db, data, errors)
    dups = find_duplicates(db, data["stem"]) if data["stem"] else []
    exact = [d for d in dups if d.stem_hash == stem_hash(data["stem"])]
    if exact:
        errors.append("An identical question already exists (see below).")
    elif dups and not data["allow_similar"]:
        errors.append("Similar questions exist. Review them below, then tick “Save anyway” if yours is different.")
    if errors:
        return render(request, "questions/form.html", _form_ctx(db, data, errors=errors, duplicates=dups), status_code=400)
    q = apply_question(Question(topic_id=tid, source_type="manual", created_by_id=user.id), data)
    q.status = data["status"] if data["status"] in QUESTION_STATUSES else "draft"
    if q.status == "approved":
        q.reviewed_by_id, q.reviewed_at = user.id, utcnow()
    db.add(q)
    db.commit()
    _after_approval(db, [q])
    flash(request, "Question saved.")
    if (await request.form()).get("save_and_new"):
        return RedirectResponse(f"/questions/new?topic={tid}", status_code=303)
    return RedirectResponse("/questions", status_code=303)


def _get(db: Session, qid: int) -> Question:
    q = db.scalar(select(Question).where(Question.id == qid).options(*_load_opts()))
    if not q:
        raise HTTPException(404, "Question not found")
    return q


@router.get("/questions/{qid:int}")
def view_question(request: Request, qid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    q = _get(db, qid)
    stats = db.execute(
        select(func.count(), func.sum(cast(AttemptAnswer.is_correct, Integer)))
        .where(AttemptAnswer.question_id == qid, AttemptAnswer.chosen.is_not(None))
    ).one()
    return render(request, "questions/view.html", {"active": "question_bank", "q": q,
                                                   "answered": stats[0] or 0, "correct": stats[1] or 0})


@router.get("/questions/{qid:int}/edit")
def edit_question(request: Request, qid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    q = _get(db, qid)
    form = {k: getattr(q, k) or "" for k in FIELDS}
    form.update(topic_id=q.topic_id, status=q.status)
    return render(request, "questions/form.html", _form_ctx(db, form, q))


@router.post("/questions/{qid:int}/edit")
async def update_question(request: Request, qid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    q = _get(db, qid)
    data = await _read_form(request)
    errors = validate_question(data)
    tid = _check_topic(db, data, errors)
    dups = [d for d in find_duplicates(db, data["stem"], exclude_id=q.id) if d.stem_hash == stem_hash(data["stem"])]
    if dups:
        errors.append("Another question with the same stem already exists.")
    if errors:
        return render(request, "questions/form.html", _form_ctx(db, data, q, errors, dups), status_code=400)
    was_approved = q.status == "approved"
    apply_question(q, data)
    q.topic_id = tid
    new_status = data["status"] if data["status"] in QUESTION_STATUSES else q.status
    if new_status == "approved" and not was_approved:
        q.reviewed_by_id, q.reviewed_at = user.id, utcnow()
    q.status = new_status
    db.commit()
    if not was_approved and q.status == "approved":
        _after_approval(db, [q])
    flash(request, "Question updated.")
    nxt = (await request.form()).get("next") or ""
    return RedirectResponse(nxt if nxt.startswith("/questions") else "/questions", status_code=303)


@router.post("/questions/{qid:int}/delete")
def delete_question(request: Request, qid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    q = _get(db, qid)
    db.delete(q)
    db.commit()
    flash(request, "Question deleted.")
    return RedirectResponse("/questions", status_code=303)


@router.post("/questions/bulk")
async def bulk_action(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    form = await request.form()
    action = form.get("action")
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    back = form.get("back") or "/questions"
    if not ids:
        flash(request, "Select at least one question.", "warning")
        return RedirectResponse(back, status_code=303)
    items = db.scalars(select(Question).where(Question.id.in_(ids))).all()
    if action == "delete":
        for q in items:
            db.delete(q)
    elif action in ("approved", "rejected", "pending_review", "draft"):
        newly = []
        for q in items:
            if action == "approved" and q.status != "approved":
                newly.append(q)
            q.status = action
            if action in ("approved", "rejected"):
                q.reviewed_by_id, q.reviewed_at = user.id, utcnow()
        db.commit()
        _after_approval(db, newly)
    else:
        flash(request, "Unknown action.", "danger")
        return RedirectResponse(back, status_code=303)
    db.commit()
    flash(request, f"{len(items)} question(s) updated.")
    return RedirectResponse(back if back.startswith("/questions") else "/questions", status_code=303)


# ---- review queue ----

@router.get("/questions/review", name="review_queue")
def review_queue(request: Request, source: str = "", topic: int = 0, user: User = Depends(require_staff),
                 db: Session = Depends(get_db)):
    stmt = select(Question).where(Question.status == "pending_review")
    if source in SOURCE_TYPES:
        stmt = stmt.where(Question.source_type == source)
    if topic:
        stmt = stmt.where(Question.topic_id == topic)
    items = db.scalars(stmt.options(*_load_opts()).order_by(Question.created_at).limit(50)).all()
    pending = db.scalar(select(func.count(Question.id)).where(Question.status == "pending_review"))
    by_source = dict(db.execute(select(Question.source_type, func.count(Question.id))
                                .where(Question.status == "pending_review").group_by(Question.source_type)).all())
    return render(request, "questions/review.html", {
        "active": "review_queue", "items": items, "pending": pending, "by_source": by_source, "source": source,
        "sources": SOURCE_TYPES, "topic": topic,
    })


@router.post("/questions/{qid:int}/review")
def review_decision(request: Request, qid: int, decision: str = Form(...), note: str = Form(""),
                    user: User = Depends(require_staff), db: Session = Depends(get_db)):
    q = _get(db, qid)
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "Invalid decision")
    q.status = decision
    q.reviewed_by_id, q.reviewed_at = user.id, utcnow()
    q.review_note = note.strip() or None
    db.commit()
    if decision == "approved":
        _after_approval(db, [q])
    flash(request, f"Question #{q.id} {decision}.")
    return RedirectResponse("/questions/review", status_code=303)


# ---- duplicate check API ----

@router.get("/api/questions/duplicates")
def duplicates_api(stem: str = "", exclude: int = 0, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    if len(stem.strip()) < 15:
        return JSONResponse({"items": []})
    items = find_duplicates(db, stem, exclude_id=exclude or None)
    return JSONResponse({"items": [{"id": q.id, "stem": q.stem[:160], "status": q.status} for q in items]})


# ---- import ----

@router.get("/questions/import", name="question_import")
def import_page(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return render(request, "questions/import.html", {"active": "question_import", "topic_groups": topic_options(db)})


@router.get("/questions/import/template.csv")
def import_template_csv(user: User = Depends(require_staff)):
    return Response(template_csv(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="smartprep_questions_template.csv"'})


@router.get("/questions/import/template.xlsx")
def import_template_xlsx(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return Response(template_xlsx(db), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="smartprep_questions_template.xlsx"'})


@router.post("/questions/import")
async def import_preview(request: Request, file: UploadFile = File(...), default_topic: int = Form(0),
                         status: str = Form("pending_review"), user: User = Depends(require_staff),
                         db: Session = Depends(get_db)):
    data = await file.read(5 * 1024 * 1024 + 1)
    ctx = {"active": "question_import", "topic_groups": topic_options(db), "status": status,
           "default_topic": default_topic}
    if len(data) > 5 * 1024 * 1024:
        return render(request, "questions/import.html", {**ctx, "errors": ["File too large (max 5 MB)."]}, 400)
    rows, error = parse_file(file.filename or "", data)
    if error:
        return render(request, "questions/import.html", {**ctx, "errors": [error]}, 400)
    checked = validate_rows(db, rows, default_topic or None)
    valid = [{**r["data"], "topic_id": r["topic_id"]} for r in checked if not r["errors"]]
    return render(request, "questions/import.html", {
        **ctx, "checked": checked, "valid_count": len(valid), "payload": json.dumps(valid), "filename": file.filename,
    })


@router.post("/questions/import/confirm")
def import_confirm(request: Request, payload: str = Form("[]"), status: str = Form("pending_review"),
                   user: User = Depends(require_staff), db: Session = Depends(get_db)):
    try:
        rows = json.loads(payload)
        assert isinstance(rows, list)
    except (ValueError, AssertionError):
        raise HTTPException(400, "Invalid import payload")
    status = status if status in ("draft", "pending_review", "approved") else "pending_review"
    # re-validate on the server: never trust the hidden field
    checked = validate_rows(db, [{k: str(v or "") for k, v in r.items()} for r in rows if isinstance(r, dict)])
    created = []
    for r in checked:
        if r["errors"] or not r["topic_id"]:
            continue
        q = apply_question(Question(topic_id=r["topic_id"], source_type="csv_import", created_by_id=user.id), r["data"])
        q.status = status
        if status == "approved":
            q.reviewed_by_id, q.reviewed_at = user.id, utcnow()
        db.add(q)
        created.append(q)
    db.commit()
    if status == "approved":
        _after_approval(db, created)
    skipped = len(checked) - len(created)
    flash(request, f"Imported {len(created)} question(s)" + (f"; skipped {skipped} invalid/duplicate row(s)." if skipped else "."))
    return RedirectResponse("/questions?source=csv_import", status_code=303)


def _after_approval(db: Session, questions: list[Question]) -> None:
    """Hook for newly approved questions (notifications are added in a later phase)."""
    try:
        from app.services.notify import notify_new_questions
    except ImportError:
        return
    if questions:
        notify_new_questions(db, questions)
