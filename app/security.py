"""Password hashing, one-time tokens, TOTP helpers, CSRF tokens."""
import base64
import hashlib
import hmac
import io
import secrets
from datetime import timedelta

import pyotp
import qrcode
import qrcode.image.svg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import utcnow
from app.models import AuthToken, User

_ph = PasswordHasher()

PASSWORD_MIN_LENGTH = 8


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        problems.append("Password must contain both letters and numbers.")
    return problems


# ---- one-time tokens (verify email / reset password) ----

def _hash_token(token: str) -> str:
    return hashlib.sha256((settings.SECRET_KEY + token).encode()).hexdigest()


def create_token(db: Session, user: User, purpose: str, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash_token(token),
            expires_at=utcnow() + timedelta(hours=hours),
        )
    )
    db.commit()
    return token


def consume_token(db: Session, token: str, purpose: str) -> User | None:
    """Return the user for a valid unused token and mark it used; None if invalid/expired."""
    if not token:
        return None
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash_token(token)))
    if not row or row.purpose != purpose or row.used_at is not None or row.expires_at < utcnow():
        return None
    row.used_at = utcnow()
    user = db.get(User, row.user_id)
    db.commit()
    return user


def peek_token(db: Session, token: str, purpose: str) -> bool:
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash_token(token or "")))
    return bool(row and row.purpose == purpose and row.used_at is None and row.expires_at >= utcnow())


# ---- TOTP ----

def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str | None, code: str) -> bool:
    if not secret:
        return False
    code = (code or "").replace(" ", "")
    return code.isdigit() and pyotp.TOTP(secret).verify(code, valid_window=1)


def totp_qr_data_uri(secret: str, email: str) -> str:
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.APP_NAME)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


# ---- CSRF ----

def get_csrf_token(session: dict) -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def csrf_matches(session: dict, supplied: str | None) -> bool:
    expected = session.get("csrf")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))
