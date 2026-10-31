"""Categories -> courses -> topics management (staff; categories are admin-only)."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin, require_staff
from app.models import MAJORS, Category, Course, Question, Topic, User
from app.services.cache import clear_cache
from app.services.content import topic_tree
from app.templating import flash, render

router = APIRouter(prefix="/content", tags=["content"])
BACK = "/content/categories"


def _done(request: Request, msg: str) -> RedirectResponse:
    clear_cache()
    flash(request, msg)
    return RedirectResponse(BACK, status_code=303)


def _clean(name: str, max_len: int = 150) -> str:
    name = (name or "").strip()
    if not (2 <= len(name) <= max_len):
        raise HTTPException(400, f"Name must be 2–{max_len} characters.")
    return name


@router.get("/categories", name="content_structure")
def structure(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Question.topic_id, func.count(Question.id)).group_by(Question.topic_id)).all())
    approved = dict(
        db.execute(
            select(Question.topic_id, func.count(Question.id)).where(Question.status == "approved").group_by(Question.topic_id)
        ).all()
    )
    return render(request, "content/structure.html", {
        "active": "content_structure", "tree": topic_tree(db), "counts": counts, "approved": approved, "majors": MAJORS,
    })


# ---- categories (admin) ----

@router.post("/categories")
def create_category(request: Request, name: str = Form(""), code: str = Form(""), description: str = Form(""),
                    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    code = (code or "").strip().lower().replace(" ", "_")[:30]
    if not code or db.scalar(select(Category.id).where(Category.code == code)):
        flash(request, "Category code is required and must be unique.", "danger")
        return RedirectResponse(BACK, status_code=303)
    order = (db.scalar(select(func.max(Category.sort_order))) or 0) + 1
    db.add(Category(name=_clean(name, 120), code=code, description=description.strip() or None, sort_order=order))
    db.commit()
    return _done(request, "Category created.")


@router.post("/categories/{cat_id:int}/edit")
def edit_category(request: Request, cat_id: int, name: str = Form(""), description: str = Form(""),
                  sort_order: int = Form(0), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id) or _404()
    cat.name, cat.description, cat.sort_order = _clean(name, 120), description.strip() or None, sort_order
    db.commit()
    return _done(request, "Category updated.")


@router.post("/categories/{cat_id:int}/delete")
def delete_category(request: Request, cat_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id) or _404()
    if cat.code in ("gen_ed", "prof_ed", "major"):
        flash(request, "Core LET categories cannot be deleted.", "warning")
        return RedirectResponse(BACK, status_code=303)
    db.delete(cat)
    db.commit()
    return _done(request, "Category deleted.")


# ---- courses (staff) ----

@router.post("/courses")
def create_course(request: Request, category_id: int = Form(...), name: str = Form(""), major: str = Form(""),
                  description: str = Form(""), user: User = Depends(require_staff), db: Session = Depends(get_db)):
    cat = db.get(Category, category_id) or _404()
    order = (db.scalar(select(func.max(Course.sort_order)).where(Course.category_id == cat.id)) or 0) + 1
    db.add(Course(category_id=cat.id, name=_clean(name), major=major if major in MAJORS else None,
                  description=description.strip() or None, sort_order=order))
    db.commit()
    return _done(request, "Course created.")


@router.post("/courses/{course_id:int}/edit")
def edit_course(request: Request, course_id: int, name: str = Form(""), major: str = Form(""),
                description: str = Form(""), sort_order: int = Form(0),
                user: User = Depends(require_staff), db: Session = Depends(get_db)):
    course = db.get(Course, course_id) or _404()
    course.name = _clean(name)
    course.major = major if major in MAJORS else None
    course.description = description.strip() or None
    course.sort_order = sort_order
    db.commit()
    return _done(request, "Course updated.")


@router.post("/courses/{course_id:int}/delete")
def delete_course(request: Request, course_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    course = db.get(Course, course_id) or _404()
    db.delete(course)
    db.commit()
    return _done(request, "Course and its topics deleted.")


# ---- topics (staff) ----

@router.post("/topics")
def create_topic(request: Request, course_id: int = Form(...), name: str = Form(""), description: str = Form(""),
                 user: User = Depends(require_staff), db: Session = Depends(get_db)):
    course = db.get(Course, course_id) or _404()
    if db.scalar(select(Topic.id).where(Topic.course_id == course.id, func.lower(Topic.name) == name.strip().lower())):
        flash(request, "That topic already exists in this course.", "warning")
        return RedirectResponse(BACK, status_code=303)
    order = (db.scalar(select(func.max(Topic.sort_order)).where(Topic.course_id == course.id)) or 0) + 1
    db.add(Topic(course_id=course.id, name=_clean(name), description=description.strip() or None, sort_order=order))
    db.commit()
    return _done(request, "Topic created.")


@router.post("/topics/{topic_id:int}/edit")
def edit_topic(request: Request, topic_id: int, name: str = Form(""), description: str = Form(""),
               sort_order: int = Form(0), user: User = Depends(require_staff), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id) or _404()
    topic.name, topic.description, topic.sort_order = _clean(name), description.strip() or None, sort_order
    db.commit()
    return _done(request, "Topic updated.")


@router.post("/topics/{topic_id:int}/delete")
def delete_topic(request: Request, topic_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id) or _404()
    n = db.scalar(select(func.count(Question.id)).where(Question.topic_id == topic.id))
    if n and user.role != "admin":
        flash(request, f"This topic has {n} question(s). Only an admin can delete it.", "warning")
        return RedirectResponse(BACK, status_code=303)
    db.delete(topic)
    db.commit()
    return _done(request, "Topic deleted.")


def _404():
    raise HTTPException(404, "Not found")
