"""In-app notifications (bell), optional email via Brevo, announcement fan-out and lazy deadline reminders."""
import threading
from datetime import timedelta

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import utcnow
from app.models import Announcement, Assessment, Attempt, Course, Notification, Question, Resource, Topic, User
from app.services import email as mail
from app.templating import fmt_dt


def notify(db: Session, user_id: int, title: str, body: str = "", link: str | None = None, kind: str = "info",
           dedupe_key: str | None = None, commit: bool = True) -> Notification | None:
    """Create a notification; with dedupe_key, at most one notification per (user, key)."""
    if dedupe_key and db.scalar(select(Notification.id).where(Notification.user_id == user_id,
                                                             Notification.dedupe_key == dedupe_key)):
        return None
    n = Notification(user_id=user_id, title=title[:255], body=body or None, link=link, kind=kind, dedupe_key=dedupe_key)
    db.add(n)
    if commit:
        db.commit()
    return n


def notify_many(db: Session, user_ids: list[int], title: str, body: str = "", link: str | None = None,
                kind: str = "info", dedupe_key: str | None = None) -> int:
    """Bulk version: skips users who already have the dedupe key."""
    ids = set(user_ids)
    if dedupe_key and ids:
        ids -= set(db.scalars(select(Notification.user_id).where(Notification.dedupe_key == dedupe_key,
                                                                 Notification.user_id.in_(ids))))
    db.add_all([Notification(user_id=uid, title=title[:255], body=body or None, link=link, kind=kind,
                             dedupe_key=dedupe_key) for uid in ids])
    db.commit()
    return len(ids)


def _abs(link: str) -> str:
    base = (settings.BASE_URL or "").rstrip("/")
    return f"{base}{link}" if base else link


def email_user(db: Session, user: User, subject: str, body: str, link: str | None = None,
               background: BackgroundTasks | None = None) -> bool:
    """Queue an email (Brevo) if email delivery is configured; never blocks the request."""
    if not settings.email_enabled or not user.email:
        return False
    html = mail.wrap(subject, "".join(f"<p>{line}</p>" for line in body.splitlines() if line.strip())
                     + (mail.button(_abs(link), "Open Smart Prep") if link else ""))
    if background is not None:
        background.add_task(mail.send_email, user.email, subject, html, user.full_name)
    else:
        threading.Thread(target=mail.send_email, args=(user.email, subject, html, user.full_name), daemon=True).start()
    return True


# ---------------------------------------------------------------- audiences

def students_for_course(db: Session, course: Course | None) -> list[int]:
    stmt = select(User.id).where(User.role == "student", User.is_active.is_(True))
    if course is not None and course.major:
        stmt = stmt.where(User.major == course.major)
    return list(db.scalars(stmt))


def _students_for_assessment(db: Session, a: Assessment) -> list[int]:
    from app.services.assessments import visible_to

    students = db.scalars(select(User).where(User.role == "student", User.is_active.is_(True))).all()
    return [s.id for s in students if visible_to(a, s)]


# ---------------------------------------------------------------- triggers

def notify_new_questions(db: Session, questions: list[Question]) -> None:
    by_topic: dict[int, int] = {}
    for q in questions:
        by_topic[q.topic_id] = by_topic.get(q.topic_id, 0) + 1
    today = (utcnow() + timedelta(hours=8)).date().isoformat()
    for tid, n in by_topic.items():
        topic = db.get(Topic, tid)
        if not topic:
            continue
        notify_many(db, students_for_course(db, topic.course), f"New practice questions: {topic.name}",
                    f"{n} new question(s) were added to {topic.course.name} › {topic.name}.",
                    f"/practice/topic/{tid}", kind="content", dedupe_key=f"newq:{tid}:{today}")


def notify_new_resource(db: Session, r: Resource) -> None:
    course = r.topic.course if r.topic else None
    notify_many(db, students_for_course(db, course), f"New learning material: {r.title}",
                r.description or "", "/materials", kind="content", dedupe_key=f"res:{r.id}")


def notify_assessment_published(db: Session, a: Assessment) -> None:
    due = f" Due {fmt_dt(a.due_at)}." if a.due_at else ""
    notify_many(db, _students_for_assessment(db, a), f"New {a.kind_label}: {a.title}",
                f"{a.question_count} questions.{due}", f"/assessments/{a.id}/start", kind="assessment",
                dedupe_key=f"pub:{a.id}")


def check_due_soon(db: Session, user: User) -> int:
    """Lazy reminder (no cron): notify about visible assessments due within 24 h that are not yet passed."""
    from app.services.assessments import visible_assessments

    now = utcnow()
    soon = [a for a in visible_assessments(db, user) if a.is_published and a.due_at and now < a.due_at <= now + timedelta(hours=24)]
    if not soon:
        return 0
    passed = set(db.scalars(select(Attempt.assessment_id).where(Attempt.user_id == user.id, Attempt.passed.is_(True),
                                                                Attempt.is_adaptive.is_(False))))
    n = 0
    for a in soon:
        if a.id in passed:
            continue
        if notify(db, user.id, f"Due within 24 hours: {a.title}", f"Due {fmt_dt(a.due_at)}.",
                  f"/assessments/{a.id}/start", kind="due", dedupe_key=f"due24:{a.id}"):
            n += 1
    return n


# ---------------------------------------------------------------- announcements

def announcement_recipients(db: Session, roles: list[str], course_id: int | None, user_ids: list[int]) -> list[int]:
    ids: set[int] = set()
    if user_ids:
        ids |= set(db.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))))
    if course_id:
        ids |= set(students_for_course(db, db.get(Course, course_id)))
    if roles:
        ids |= set(db.scalars(select(User.id).where(User.role.in_(roles), User.is_active.is_(True))))
    if not (user_ids or course_id or roles):  # everyone
        ids |= set(db.scalars(select(User.id).where(User.is_active.is_(True))))
    return sorted(ids)


def publish_announcement(db: Session, author: User, title: str, body: str, roles: list[str], course_id: int | None,
                         user_ids: list[int], send_email: bool, background: BackgroundTasks | None = None) -> Announcement:
    ann = Announcement(title=title, body=body, author_id=author.id, target_roles=",".join(roles) or None,
                       target_course_id=course_id, target_user_ids=",".join(map(str, user_ids)) or None,
                       send_email=send_email)
    db.add(ann)
    db.commit()
    recipients = [uid for uid in announcement_recipients(db, roles, course_id, user_ids) if uid != author.id]
    notify_many(db, recipients, f"Announcement: {title}", body[:300], f"/announcements/{ann.id}", kind="announcement",
                dedupe_key=f"ann:{ann.id}")
    ann.recipient_count = len(recipients)
    db.commit()
    if send_email and settings.email_enabled:
        for u in db.scalars(select(User).where(User.id.in_(recipients or [0]))):
            email_user(db, u, f"Announcement: {title}", body, f"/announcements/{ann.id}", background)
    return ann


def can_view_announcement(db: Session, user: User, ann: Announcement) -> bool:
    if user.is_staff or ann.author_id == user.id:
        return True
    return bool(db.scalar(select(Notification.id).where(Notification.user_id == user.id,
                                                       Notification.dedupe_key == f"ann:{ann.id}")))

