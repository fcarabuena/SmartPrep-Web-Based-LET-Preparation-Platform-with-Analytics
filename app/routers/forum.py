"""Discussion forum: threads per category/course, replies, faculty pin/lock/delete."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db, utcnow
from app.deps import require_any, require_staff
from app.models import Category, Course, ForumPost, ForumThread, User
from app.services.notify import notify
from app.templating import flash, render

router = APIRouter(prefix="/forum", tags=["forum"])
PAGE_SIZE = 20


def _courses_for(db: Session, user: User) -> list[Course]:
    return [c for c in db.scalars(select(Course).order_by(Course.category_id, Course.sort_order))
            if user.is_staff or not c.major or c.major == user.major]


@router.get("", name="forum")
def forum(request: Request, category: int = 0, course: int = 0, q: str = "", page: int = 1,
          user: User = Depends(require_any), db: Session = Depends(get_db)):
    stmt = select(ForumThread)
    if category:
        stmt = stmt.where(ForumThread.category_id == category)
    if course:
        stmt = stmt.where(ForumThread.course_id == course)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(ForumThread.title).like(like), func.lower(ForumThread.body).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page = max(page, 1)
    threads = db.scalars(stmt.options(selectinload(ForumThread.author), selectinload(ForumThread.course),
                                      selectinload(ForumThread.category))
                         .order_by(ForumThread.is_pinned.desc(), ForumThread.last_activity_at.desc())
                         .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    filters = {"category": category, "course": course, "q": q}
    return render(request, "forum/list.html", {
        "active": "forum", "threads": threads, "filters": filters, "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)), "qs": "&".join(f"{k}={v}" for k, v in filters.items() if v),
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "courses": _courses_for(db, user),
    })


@router.get("/new")
def new_thread(request: Request, category: int = 0, course: int = 0, user: User = Depends(require_any),
               db: Session = Depends(get_db)):
    return render(request, "forum/new.html", {
        "active": "forum", "category": category, "course": course,
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "courses": _courses_for(db, user),
    })


@router.post("/new")
def create_thread(request: Request, title: str = Form(""), body: str = Form(""), category_id: int = Form(0),
                  course_id: int = Form(0), user: User = Depends(require_any), db: Session = Depends(get_db)):
    title, body = title.strip()[:255], body.strip()[:20000]
    if len(title) < 5 or len(body) < 5:
        flash(request, "Please write a title (5+ characters) and a message.", "danger")
        return RedirectResponse("/forum/new", status_code=303)
    course = db.get(Course, course_id) if course_id else None
    if course is not None:
        category_id = course.category_id
    t = ForumThread(title=title, body=body, author_id=user.id, category_id=category_id or None,
                    course_id=course.id if course else None)
    db.add(t)
    db.commit()
    flash(request, "Discussion started.")
    return RedirectResponse(f"/forum/{t.id}", status_code=303)


def _get(db: Session, tid: int) -> ForumThread:
    t = db.scalar(select(ForumThread).where(ForumThread.id == tid).options(
        selectinload(ForumThread.author), selectinload(ForumThread.posts).selectinload(ForumPost.author),
        selectinload(ForumThread.course), selectinload(ForumThread.category)))
    if not t:
        raise HTTPException(404, "Thread not found")
    return t


@router.get("/{tid:int}")
def view_thread(request: Request, tid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    return render(request, "forum/thread.html", {"active": "forum", "t": _get(db, tid)})


@router.post("/{tid:int}/reply")
def reply(request: Request, tid: int, body: str = Form(""), user: User = Depends(require_any),
          db: Session = Depends(get_db)):
    t = _get(db, tid)
    if t.is_locked and not user.is_staff:
        flash(request, "This thread is locked.", "warning")
        return RedirectResponse(f"/forum/{tid}", status_code=303)
    body = body.strip()[:20000]
    if not body:
        flash(request, "Reply cannot be empty.", "danger")
        return RedirectResponse(f"/forum/{tid}", status_code=303)
    db.add(ForumPost(thread_id=t.id, author_id=user.id, body=body))
    t.reply_count = (t.reply_count or 0) + 1
    t.last_activity_at = utcnow()
    db.commit()
    if t.author_id and t.author_id != user.id:
        notify(db, t.author_id, f"New reply in “{t.title[:80]}”", f"{user.full_name} replied.", f"/forum/{t.id}",
               kind="forum")
    return RedirectResponse(f"/forum/{tid}#bottom", status_code=303)


@router.post("/{tid:int}/pin")
def pin(request: Request, tid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    t = _get(db, tid)
    t.is_pinned = not t.is_pinned
    db.commit()
    flash(request, "Thread pinned." if t.is_pinned else "Thread unpinned.")
    return RedirectResponse(f"/forum/{tid}", status_code=303)


@router.post("/{tid:int}/lock")
def lock(request: Request, tid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    t = _get(db, tid)
    t.is_locked = not t.is_locked
    db.commit()
    flash(request, "Thread locked." if t.is_locked else "Thread unlocked.")
    return RedirectResponse(f"/forum/{tid}", status_code=303)


@router.post("/{tid:int}/delete")
def delete_thread(request: Request, tid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    t = _get(db, tid)
    if not user.is_staff and not (t.author_id == user.id and not t.posts):
        raise HTTPException(403, "Only faculty can delete threads with replies.")
    db.delete(t)
    db.commit()
    flash(request, "Thread deleted.")
    return RedirectResponse("/forum", status_code=303)


@router.post("/posts/{pid:int}/delete")
def delete_post(request: Request, pid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    p = db.get(ForumPost, pid)
    if not p or not (user.is_staff or p.author_id == user.id):
        raise HTTPException(404, "Post not found")
    t = db.get(ForumThread, p.thread_id)
    db.delete(p)
    t.reply_count = max(0, (t.reply_count or 1) - 1)
    db.commit()
    flash(request, "Reply deleted.")
    return RedirectResponse(f"/forum/{t.id}", status_code=303)
