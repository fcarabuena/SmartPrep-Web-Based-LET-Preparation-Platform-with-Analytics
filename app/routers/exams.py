"""Students: Examinations and Quizzes pages, taking assessments (timer, autosave), results, grades."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import require_any, require_student
from app.models import Assessment, Attempt, Category, Course, User
from app.models.assessment import KIND_GAME, KIND_MOCK, KIND_PRACTICE, KIND_QUIZ_BEE
from app.services.assessments import (
    EXAM_TABS,
    AttemptError,
    availability,
    expire_overdue,
    grade_rows,
    is_expired,
    load_attempt,
    save_answers,
    start_attempt,
    submit_attempt,
    visible_assessments,
    visible_to,
)
from app.services.content import nav_categories
from app.services.pdf import table_pdf
from app.services.settings_store import threshold_for_attempt
from app.templating import flash, fmt_dt, render

router = APIRouter(tags=["exams"])


def _with_availability(db: Session, user: User, items: list[Assessment]) -> list[dict]:
    return [{"a": a, "av": availability(db, a, user)} for a in items]


@router.get("/examinations", name="examinations")
def examinations(request: Request, tab: str = "prof_ed", user: User = Depends(require_student),
                 db: Session = Depends(get_db)):
    expire_overdue(db, user.id)
    exams = visible_assessments(db, user, (KIND_MOCK,))
    tabs = []
    for code, label in EXAM_TABS:
        if code == "major" and user.major == "elementary":
            continue
        items = [a for a in exams if a.category and a.category.code == code]
        tabs.append({"code": code, "label": label, "items": _with_availability(db, user, items)})
    other = [a for a in exams if not a.category or a.category.code not in dict(EXAM_TABS)]
    if other:
        tabs.append({"code": "other", "label": "Other", "items": _with_availability(db, user, other)})
    if tab not in [t["code"] for t in tabs]:
        tab = tabs[0]["code"] if tabs else ""
    return render(request, "exams/examinations.html", {"active": "examinations", "tabs": tabs, "tab": tab})


@router.get("/quizzes", name="quizzes")
def quizzes(request: Request, category: int = 0, course: int = 0, user: User = Depends(require_student),
            db: Session = Depends(get_db)):
    expire_overdue(db, user.id)
    items = visible_assessments(db, user, (KIND_PRACTICE,))
    cats = nav_categories(db, user.major)
    if course:
        items = [a for a in items if a.course_id == course]
    elif category:
        items = [a for a in items if a.category_id == category or (a.course and a.course.category_id == category)]
    groups: dict[str, list] = {}
    course_names = {c["id"]: (cat["name"], c["name"]) for cat in cats for c in cat["courses"]}
    for a in items:
        if a.course_id in course_names:
            key = " › ".join(course_names[a.course_id])
        elif a.category:
            key = a.category.name
        else:
            key = "Mixed subjects"
        groups.setdefault(key, []).append({"a": a, "av": availability(db, a, user)})
    title = "All quizzes"
    if course:
        title = " › ".join(course_names.get(course, ("Quizzes", "")))
    elif category:
        title = next((c["name"] for c in cats if c["id"] == category), "Quizzes")
    return render(request, "exams/quizzes.html", {"active": "quizzes", "groups": groups, "cats": cats,
                                                   "category": category, "course": course, "title": title})


def _get_assessment(db: Session, aid: int) -> Assessment:
    a = db.get(Assessment, aid)
    if not a:
        raise HTTPException(404, "Assessment not found")
    return a


@router.get("/assessments/{aid:int}/start")
def start_page(request: Request, aid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    a = _get_assessment(db, aid)
    if not visible_to(a, user):
        raise HTTPException(404, "Assessment not found")
    av = availability(db, a, user)
    history = db.scalars(select(Attempt).where(Attempt.assessment_id == a.id, Attempt.user_id == user.id,
                                               Attempt.status == "submitted").order_by(Attempt.attempt_no)).all()
    next_threshold = threshold_for_attempt(db, av.attempts_used + 1)
    return render(request, "exams/start.html", {"active": "examinations" if a.kind == KIND_MOCK else "quizzes",
                                                "a": a, "av": av, "history": history,
                                                "next_threshold": next_threshold})


@router.post("/assessments/{aid:int}/start")
def start(request: Request, aid: int, access_code: str = Form(""), user: User = Depends(require_any),
          db: Session = Depends(get_db)):
    a = _get_assessment(db, aid)
    try:
        attempt = start_attempt(db, a, user, access_code)
    except AttemptError as exc:
        flash(request, str(exc), "danger")
        return RedirectResponse(f"/assessments/{aid}/start", status_code=303)
    return RedirectResponse(f"/attempts/{attempt.id}", status_code=303)


def _own_attempt(db: Session, attempt_id: int, user: User, allow_staff: bool = False) -> Attempt:
    attempt = load_attempt(db, attempt_id)
    if not attempt or (attempt.user_id != user.id and not (allow_staff and user.is_staff)):
        raise HTTPException(404, "Attempt not found")
    return attempt


@router.get("/attempts/{attempt_id:int}", name="take_attempt")
def take(request: Request, attempt_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    attempt = _own_attempt(db, attempt_id, user)
    if attempt.status == "in_progress" and is_expired(attempt):
        submit_attempt(db, attempt, auto=True)
        flash(request, "Time is up. Your attempt was submitted automatically.", "warning")
    if attempt.status == "submitted":
        return RedirectResponse(f"/attempts/{attempt.id}/result", status_code=303)
    now = utcnow()
    remaining = int((attempt.deadline_at - now).total_seconds()) if attempt.deadline_at else None
    return render(request, "exams/take.html", {
        "active": "examinations" if attempt.kind == KIND_MOCK else "quizzes", "attempt": attempt,
        "remaining": remaining, "answered": sum(1 for x in attempt.answers if x.chosen),
    })


@router.post("/api/attempts/{attempt_id:int}/save")
async def autosave(request: Request, attempt_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    attempt = _own_attempt(db, attempt_id, user)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    try:
        save_answers(db, attempt, payload.get("answers") or {}, payload.get("times") or {})
    except AttemptError as exc:
        return JSONResponse({"ok": False, "submitted": attempt.status == "submitted", "message": str(exc),
                             "redirect": f"/attempts/{attempt.id}/result"}, status_code=409)
    remaining = int((attempt.deadline_at - utcnow()).total_seconds()) if attempt.deadline_at else None
    return JSONResponse({"ok": True, "remaining": remaining, "saved_at": fmt_dt(attempt.last_saved_at, "%I:%M:%S %p")})


@router.post("/attempts/{attempt_id:int}/submit")
async def submit(request: Request, attempt_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    attempt = _own_attempt(db, attempt_id, user)
    if attempt.status == "in_progress":
        form = await request.form()
        answers = {k[4:]: v for k, v in form.items() if k.startswith("ans_")}
        times = {k[5:]: v for k, v in form.items() if k.startswith("time_")}
        auto = form.get("auto") == "1"
        try:
            save_answers(db, attempt, answers, times)
        except AttemptError:
            pass  # already auto-submitted because time ran out
        submit_attempt(db, attempt, auto=auto or is_expired(attempt))
    return RedirectResponse(f"/attempts/{attempt.id}/result", status_code=303)


@router.get("/attempts/{attempt_id:int}/result", name="attempt_result")
def result(request: Request, attempt_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    attempt = _own_attempt(db, attempt_id, user, allow_staff=True)
    if attempt.status != "submitted":
        if is_expired(attempt):
            submit_attempt(db, attempt, auto=True)
        else:
            return RedirectResponse(f"/attempts/{attempt.id}", status_code=303)
    a = attempt.assessment
    av = availability(db, a, attempt.user) if a else None
    recs = {"questions": [], "resources": [], "topics": []}
    try:
        from app.services.recommendations import recommendations_for_attempt
    except ImportError:
        pass
    else:
        recs = recommendations_for_attempt(db, attempt)
    badges = []
    try:
        from app.services.gamification import badges_from_attempt
    except ImportError:
        pass
    else:
        badges = badges_from_attempt(db, attempt)
    return render(request, "exams/result.html", {
        "active": "examinations" if attempt.kind == KIND_MOCK else "quizzes", "attempt": attempt, "a": a, "av": av,
        "recs": recs, "is_owner": attempt.user_id == user.id, "new_badges": badges,
    })


# ---------------------------------------------------------------- grades

def _grade_ctx(db: Session, user: User, category: int, course: int) -> dict:
    expire_overdue(db, user.id)
    rows = grade_rows(db, user, category, course)
    done = [r for r in rows if r.best]
    return {
        "rows": rows, "category": category, "course": course,
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "courses": [c for c in db.scalars(select(Course).order_by(Course.category_id, Course.sort_order))
                    if not c.major or c.major == user.major],
        "summary": {
            "total": len(rows), "passed": sum(r.status == "Passed" for r in rows),
            "failed": sum(r.status == "Failed" for r in rows), "missing": sum(r.status == "Missing" for r in rows),
            "average": round(sum(r.best.score_pct for r in done) / len(done), 1) if done else None,
        },
    }


@router.get("/grades", name="grades")
def grades(request: Request, category: int = 0, course: int = 0, user: User = Depends(require_student),
           db: Session = Depends(get_db)):
    return render(request, "exams/grades.html", {"active": "grades", **_grade_ctx(db, user, category, course)})


@router.get("/grades.pdf")
def grades_pdf(category: int = 0, course: int = 0, user: User = Depends(require_student), db: Session = Depends(get_db)):
    ctx = _grade_ctx(db, user, category, course)
    rows = [[r.assessment.title, r.assessment.kind_label,
             r.assessment.course.name if r.assessment.course else (r.assessment.category.name if r.assessment.category else "Mixed"),
             fmt_dt(r.assessment.due_at), r.status, f"{r.best.score_pct:.0f}%" if r.best else "—", r.attempts]
            for r in ctx["rows"]]
    s = ctx["summary"]
    pdf = table_pdf(
        "Grades", f"{user.full_name} · {user.email} · generated {fmt_dt(utcnow())}",
        ["Title", "Type", "Category / Course", "Due", "Status", "Best score", "Attempts"], rows, wide=True,
        summary=[("Assessments", s["total"]), ("Passed", s["passed"]), ("Failed", s["failed"]),
                 ("Missing", s["missing"]), ("Average best score", f"{s['average']}%" if s["average"] is not None else "—")],
    )
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="smartprep_grades.pdf"'})


KINDS_FOR_GAMES = (KIND_GAME, KIND_QUIZ_BEE)
