"""Inbox: direct messages with threads, folders (Inbox/Sent/Unread/Drafts), course filter and search."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.db import get_db, utcnow
from app.deps import require_any
from app.models import Course, Message, User
from app.templating import flash, render

router = APIRouter(tags=["inbox"])
PAGE_SIZE = 25
BOXES = {"inbox": "Inbox", "unread": "Unread", "sent": "Sent", "drafts": "Drafts"}


def _box_query(user: User, box: str):
    if box == "sent":
        return select(Message).where(Message.sender_id == user.id, Message.is_draft.is_(False),
                                     Message.deleted_by_sender.is_(False))
    if box == "drafts":
        return select(Message).where(Message.sender_id == user.id, Message.is_draft.is_(True))
    stmt = select(Message).where(Message.recipient_id == user.id, Message.is_draft.is_(False),
                                 Message.deleted_by_recipient.is_(False))
    if box == "unread":
        stmt = stmt.where(Message.read_at.is_(None))
    return stmt


@router.get("/inbox", name="inbox")
def inbox(request: Request, box: str = "inbox", course: int = 0, q: str = "", page: int = 1,
          user: User = Depends(require_any), db: Session = Depends(get_db)):
    box = box if box in BOXES else "inbox"
    stmt = _box_query(user, box)
    if course:
        stmt = stmt.where(Message.course_id == course)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.outerjoin(User, Message.sender_id == User.id).where(or_(
            func.lower(Message.subject).like(like), func.lower(Message.body).like(like),
            func.lower(User.full_name).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page = max(page, 1)
    items = db.scalars(stmt.options(selectinload(Message.sender), selectinload(Message.recipient),
                                    selectinload(Message.course))
                       .order_by(Message.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    counts = {b: db.scalar(select(func.count()).select_from(_box_query(user, b).subquery())) for b in ("unread", "drafts")}
    return render(request, "comms/inbox.html", {
        "active": "inbox", "items": items, "box": box, "boxes": BOXES, "course": course, "q": q, "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)), "box_counts": counts,
        "courses": db.scalars(select(Course).order_by(Course.category_id, Course.sort_order)).all(),
    })


def _recipients(db: Session, user: User) -> list[User]:
    stmt = select(User).where(User.is_active.is_(True), User.id != user.id)
    return list(db.scalars(stmt.order_by(User.role, User.full_name)))


@router.get("/inbox/compose")
def compose(request: Request, to: int = 0, reply: int = 0, draft: int = 0, user: User = Depends(require_any),
            db: Session = Depends(get_db)):
    form = {"recipient_id": to, "subject": "", "body": "", "course_id": 0, "thread_id": 0, "draft_id": 0}
    if reply:
        orig = _visible(db, reply, user)
        form.update(recipient_id=orig.sender_id if orig.sender_id != user.id else (orig.recipient_id or 0),
                    subject=orig.subject if orig.subject.lower().startswith("re:") else f"Re: {orig.subject}",
                    course_id=orig.course_id or 0, thread_id=orig.thread_id or orig.id)
    if draft:
        d = db.get(Message, draft)
        if not d or d.sender_id != user.id or not d.is_draft:
            raise HTTPException(404, "Draft not found")
        form.update(recipient_id=d.recipient_id or 0, subject=d.subject, body=d.body, course_id=d.course_id or 0,
                    thread_id=d.thread_id or 0, draft_id=d.id)
    return render(request, "comms/compose.html", {
        "active": "inbox", "form": form, "recipients": _recipients(db, user),
        "courses": db.scalars(select(Course).order_by(Course.category_id, Course.sort_order)).all(),
    })


@router.post("/inbox/compose")
async def send(request: Request, user: User = Depends(require_any), db: Session = Depends(get_db)):
    f = await request.form()
    action = f.get("action", "send")
    recipient_id = int(f.get("recipient_id") or 0)
    subject = str(f.get("subject", "")).strip()[:255]
    body = str(f.get("body", "")).strip()[:20000]
    course_id = int(f.get("course_id") or 0) or None
    thread_id = int(f.get("thread_id") or 0) or None
    draft_id = int(f.get("draft_id") or 0)
    recipient = db.get(User, recipient_id) if recipient_id else None
    if action == "send" and (not recipient or not recipient.is_active or recipient.id == user.id or not body):
        flash(request, "Choose a recipient and write a message.", "danger")
        return RedirectResponse("/inbox/compose", status_code=303)
    if thread_id:
        root = db.get(Message, thread_id)
        if not root or user.id not in (root.sender_id, root.recipient_id):
            thread_id = None
    msg = db.get(Message, draft_id) if draft_id else None
    if msg is None or msg.sender_id != user.id or not msg.is_draft:
        msg = Message(sender_id=user.id)
        db.add(msg)
    msg.recipient_id = recipient.id if recipient else None
    msg.subject, msg.body, msg.course_id, msg.thread_id = subject or "(no subject)", body, course_id, thread_id
    msg.is_draft = action == "draft"
    msg.created_at = utcnow()
    db.commit()
    if msg.thread_id is None:
        msg.thread_id = msg.id
        db.commit()
    if msg.is_draft:
        flash(request, "Draft saved.")
        return RedirectResponse("/inbox?box=drafts", status_code=303)
    flash(request, f"Message sent to {recipient.full_name}.")
    return RedirectResponse(f"/inbox/{msg.thread_id}", status_code=303)


def _visible(db: Session, mid: int, user: User) -> Message:
    m = db.get(Message, mid)
    if not m or m.is_draft or user.id not in (m.sender_id, m.recipient_id):
        raise HTTPException(404, "Message not found")
    return m


@router.get("/inbox/{mid:int}")
def thread(request: Request, mid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    m = _visible(db, mid, user)
    root_id = m.thread_id or m.id
    msgs = db.scalars(select(Message).where(Message.thread_id == root_id, Message.is_draft.is_(False),
                                            or_(Message.sender_id == user.id, Message.recipient_id == user.id))
                      .options(selectinload(Message.sender), selectinload(Message.recipient))
                      .order_by(Message.created_at)).all()
    db.execute(update(Message).where(Message.thread_id == root_id, Message.recipient_id == user.id,
                                     Message.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    other = next((x.sender if x.sender_id != user.id else x.recipient for x in msgs), None)
    return render(request, "comms/thread.html", {"active": "inbox", "msgs": msgs, "root": msgs[0] if msgs else m,
                                                 "other": other})


@router.post("/inbox/{mid:int}/reply")
async def reply(request: Request, mid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    m = _visible(db, mid, user)
    f = await request.form()
    body = str(f.get("body", "")).strip()[:20000]
    if not body:
        flash(request, "Reply cannot be empty.", "danger")
        return RedirectResponse(f"/inbox/{mid}", status_code=303)
    root_id = m.thread_id or m.id
    root = db.get(Message, root_id)
    to = root.recipient_id if root.sender_id == user.id else root.sender_id
    subject = root.subject if root.subject.lower().startswith("re:") else f"Re: {root.subject}"
    db.add(Message(sender_id=user.id, recipient_id=to, subject=subject[:255], body=body, course_id=root.course_id,
                   thread_id=root_id))
    db.commit()
    flash(request, "Reply sent.")
    return RedirectResponse(f"/inbox/{root_id}", status_code=303)


@router.post("/inbox/{mid:int}/delete")
def delete(request: Request, mid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    m = db.get(Message, mid)
    if not m or user.id not in (m.sender_id, m.recipient_id):
        raise HTTPException(404, "Message not found")
    if m.is_draft:
        db.delete(m)
    else:
        if m.sender_id == user.id:
            m.deleted_by_sender = True
        if m.recipient_id == user.id:
            m.deleted_by_recipient = True
    db.commit()
    flash(request, "Message deleted.")
    return RedirectResponse("/inbox", status_code=303)
