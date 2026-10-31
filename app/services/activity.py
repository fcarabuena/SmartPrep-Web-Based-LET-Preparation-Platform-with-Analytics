"""Record lightweight activity events (never let logging break a request)."""
import logging

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ActivityLog, ErrorLog

log = logging.getLogger("smartprep.activity")


def log_event(db: Session, event: str, user_id: int | None = None, path: str | None = None) -> None:
    try:
        db.add(ActivityLog(event=event, user_id=user_id, path=(path or "")[:255]))
        db.commit()
    except Exception:  # pragma: no cover - defensive
        db.rollback()


def log_page_view(user_id: int | None, path: str, status_code: int, duration_ms: int) -> None:
    db = SessionLocal()
    try:
        db.add(
            ActivityLog(
                event="page_view", user_id=user_id, path=path[:255], status_code=status_code, duration_ms=duration_ms
            )
        )
        db.commit()
    except Exception:  # pragma: no cover
        log.debug("page view log failed", exc_info=True)
    finally:
        db.close()


def log_error(method: str, path: str, error: str, user_id: int | None) -> None:
    db = SessionLocal()
    try:
        db.add(ErrorLog(method=method, path=path[:255], error=error[:4000], user_id=user_id))
        db.commit()
    except Exception:  # pragma: no cover
        log.debug("error log failed", exc_info=True)
    finally:
        db.close()
