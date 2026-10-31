"""Notifications (bell page) and announcements."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import require_any, require_staff
from app.models import ROLES, Announcement, Course, Notification, User
from app.services.notify import can_view_announcement, publish_announcement
from app.templating import flash, render

router = APIRouter(tags=["notifications"])
PAGE_SIZE = 30


@router.get("/notifications", name="notifications")
def notifications(request: Request, unread: int = 0, page: int = 1, user: User = Depends(require_any),
                  db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.is_read.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page = max(page, 1)
    items = db.scalars(stmt.order_by(Notification.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    return render(request, "comms/notifications.html", {"active": "notifications", "items": items, "unread": unread,
                                                        "page": page, "pages": max(1, -(-total // PAGE_SIZE))})


@router.post("/notifications/{nid:int}/open")
def open_notification(nid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.is_read = True
    db.commit()
    link = n.link if n.link and n.link.startswith("/") and not n.link.startswith("//") else "/notifications"
    return RedirectResponse(link, status_code=303)


@router.post("/notifications/read-all")
def read_all(request: Request, user: User = Depends(require_any), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))
               .values(is_read=True))
    db.commit()
    flash(request, "All notifications marked as read.")
    return RedirectResponse("/notifications", status_code=303)


@router.get("/api/notifications/count")
def unread_count_api(user: User = Depends(require_any), db: Session = Depends(get_db)):
    n = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id,
                                                            Notification.is_read.is_(False)))
    return JSONResponse({"unread": n or 0})


# ---------------------------------------------------------------- announcements

@router.get("/announcements", name="announcements")
def announcements(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    items = db.scalars(select(Announcement).options(selectinload(Announcement.author))
                       .order_by(Announcement.created_at.desc()).limit(50)).all()
    return render(request, "comms/announcements.html", {
        "active": "announcements", "items": items, "roles": ROLES,
        "courses": db.scalars(select(Course).order_by(Course.category_id, Course.sort_order)).all(),
        "students": db.scalars(select(User).where(User.role == "student", User.is_active.is_(True))
                               .order_by(User.full_name)).all(),
    })


@router.post("/announcements")
async def create_announcement(request: Request, background: BackgroundTasks, user: User = Depends(require_staff),
                              db: Session = Depends(get_db)):
    f = await request.form()
    title, body = str(f.get("title", "")).strip(), str(f.get("body", "")).strip()
    if not (3 <= len(title) <= 255) or not body:
        flash(request, "Announcements need a title (3–255 characters) and a message.", "danger")
        return RedirectResponse("/announcements", status_code=303)
    roles = [r for r in f.getlist("roles") if r in ROLES]
    course_id = int(f.get("course_id") or 0) or None
    user_ids = [int(u) for u in f.getlist("user_ids") if str(u).isdigit()]
    ann = publish_announcement(db, user, title, body[:10000], roles, course_id, user_ids, f.get("send_email") == "true",
                               background)
    flash(request, f"Announcement sent to {ann.recipient_count} user(s).")
    return RedirectResponse("/announcements", status_code=303)


@router.get("/announcements/{aid:int}")
def view_announcement(request: Request, aid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    ann = db.scalar(select(Announcement).where(Announcement.id == aid).options(selectinload(Announcement.author)))
    if not ann or not can_view_announcement(db, user, ann):
        raise HTTPException(404, "Announcement not found")
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.dedupe_key == f"ann:{aid}")
               .values(is_read=True))
    db.commit()
    return render(request, "comms/announcement.html", {"active": "announcements" if user.is_staff else "notifications",
                                                       "ann": ann})


@router.post("/announcements/{aid:int}/delete")
def delete_announcement(request: Request, aid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    ann = db.get(Announcement, aid)
    if not ann:
        raise HTTPException(404, "Announcement not found")
    if user.role != "admin" and ann.author_id != user.id:
        raise HTTPException(403, "You can only delete your own announcements.")
    db.execute(Notification.__table__.delete().where(Notification.dedupe_key == f"ann:{aid}"))
    db.delete(ann)
    db.commit()
    flash(request, "Announcement deleted.")
    return RedirectResponse("/announcements", status_code=303)
