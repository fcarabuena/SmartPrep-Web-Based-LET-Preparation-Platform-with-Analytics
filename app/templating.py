"""Jinja2 setup, flash messages and the render() helper."""
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import func, select

from app.config import settings
from app.db import utcnow
from app.security import get_csrf_token

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

LOCAL_OFFSET = timedelta(hours=8)  # Philippine Standard Time (UTC+8)


def to_local(dt: datetime | None) -> datetime | None:
    return dt + LOCAL_OFFSET if dt else None


def from_local(dt: datetime | None) -> datetime | None:
    return dt - LOCAL_OFFSET if dt else None


def fmt_dt(dt: datetime | date | None, fmt: str = "%b %d, %Y %I:%M %p") -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime):
        return to_local(dt).strftime(fmt)
    return dt.strftime("%b %d, %Y")


def fmt_input_dt(dt: datetime | None) -> str:
    """Value for <input type=datetime-local> in local time."""
    return to_local(dt).strftime("%Y-%m-%dT%H:%M") if dt else ""


def time_ago(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    secs = int((utcnow() - dt).total_seconds())
    if secs < 60:
        return "just now"
    for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs >= n:
            v = secs // n
            return f"{v} {unit}{'s' if v != 1 else ''} ago"
    return "just now"


def fmt_duration(seconds: int | float | None) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def nl2br(value: str | None) -> Markup:
    return Markup("<br>".join(escape(value or "").split("\n")))


def score_class(pct: float | None) -> str:
    if pct is None:
        return "secondary"
    if pct >= 85:
        return "success"
    if pct >= 75:
        return "warning"
    return "danger"


templates.env.filters.update(
    dt=fmt_dt, input_dt=fmt_input_dt, ago=time_ago, duration=fmt_duration, nl2br=nl2br, score_class=score_class
)


def has_route(request: Request, name: str) -> bool:
    """Lets templates hide navigation for features that are not mounted."""
    names = getattr(request.app.state, "route_names", None)
    if names is None:
        names = {getattr(r, "name", None) for r in request.app.routes}
        request.app.state.route_names = names
    return name in names


templates.env.globals.update(settings=settings, now=utcnow, has_route=has_route)


def flash(request: Request, message: str, category: str = "success") -> None:
    request.session.setdefault("_flash", []).append([category, message])


def pop_flashes(request: Request) -> list:
    return request.session.pop("_flash", []) if "_flash" in request.session else []


def unread_count(request: Request, user) -> dict:
    db = getattr(request.state, "db", None)
    if db is None or user is None:
        return {"notifications": 0, "messages": 0}
    from app.models import Message, Notification

    n = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.is_read.is_(False)))
    m = db.scalar(
        select(func.count(Message.id)).where(
            Message.recipient_id == user.id,
            Message.read_at.is_(None),
            Message.is_draft.is_(False),
            Message.deleted_by_recipient.is_(False),
        )
    )
    return {"notifications": n or 0, "messages": m or 0}


def render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    ctx = dict(ctx or {})
    user = getattr(request.state, "user", None)
    ctx.setdefault("current_user", user)
    ctx["csrf_token"] = get_csrf_token(request.session)
    ctx["flashes"] = pop_flashes(request)
    ctx["counts"] = unread_count(request, user) if user else {"notifications": 0, "messages": 0}
    ctx.setdefault("active", "")
    if user is not None and user.role == "student" and getattr(request.state, "db", None) is not None:
        from app.services.content import nav_categories

        ctx.setdefault("nav_categories", nav_categories(request.state.db, user.major))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
