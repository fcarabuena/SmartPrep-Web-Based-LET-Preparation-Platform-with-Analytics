"""In-app notifications (bell). Email delivery and announcement fan-out are added on top of notify()."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification


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
