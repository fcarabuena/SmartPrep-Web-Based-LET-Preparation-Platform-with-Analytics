"""Shared FastAPI dependencies: current user, role checks, CSRF."""
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.models import User
from app.models.user import ROLE_ADMIN
from app.security import csrf_matches

IDLE_TIMEOUT_SECONDS = 8 * 3600  # sessions without "keep me signed in"


class LoginRequired(Exception):
    """Raised when a page needs an authenticated user; handled with a redirect to /login."""


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    sess = request.session
    uid = sess.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    now = time.time()
    if (
        user is None
        or not user.is_active
        or sess.get("sv") != user.session_version
        or (not sess.get("remember") and now - sess.get("last", 0) > IDLE_TIMEOUT_SECONDS)
    ):
        sess.clear()
        return None
    if now - sess.get("last", 0) > 60:
        sess["last"] = now
        user.last_seen_at = utcnow()
        db.commit()
    request.state.user = user
    return user


class PasswordChangeRequired(Exception):
    """Raised for users holding a temporary password; handled with a redirect to the change-password page."""


def get_current_user(user: User | None = Depends(get_current_user_optional)) -> User:
    if user is None:
        raise LoginRequired()
    if user.must_change_password:
        raise PasswordChangeRequired()
    return user


def require_role(*roles: str):
    """Dependency factory: the user must have one of ``roles`` (admins always pass)."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role != ROLE_ADMIN and user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have access to this page.")
        return user

    return checker


require_admin = require_role(ROLE_ADMIN)
require_staff = require_role("faculty")
require_student = require_role("student")
require_any = require_role("admin", "faculty", "student")

CSRF_EXEMPT_PREFIXES = ("/auth/google/callback",)


async def csrf_protect(request: Request) -> None:
    """App-wide dependency: every unsafe request must carry the session CSRF token."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.url.path.startswith(CSRF_EXEMPT_PREFIXES):
        return
    supplied = request.headers.get("x-csrf-token")
    if not supplied:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            form = await request.form()
            supplied = form.get("csrf_token")
    if not csrf_matches(request.session, supplied if isinstance(supplied, str) else None):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token. Please reload the page and try again.")
