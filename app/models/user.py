from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow

ROLE_ADMIN = "admin"
ROLE_FACULTY = "faculty"
ROLE_STUDENT = "student"
ROLES = (ROLE_ADMIN, ROLE_FACULTY, ROLE_STUDENT)

# Student majors. "elementary" = BEEd (no specialization); others are BSEd majors.
MAJORS = {
    "elementary": "Elementary (BEEd)",
    "math": "Mathematics",
    "english": "English",
    "filipino": "Filipino",
    "science": "Science/Biology",
    "social_studies": "Social Studies",
    "tle": "TLE",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=ROLE_STUDENT, index=True)
    major: Mapped[str | None] = mapped_column(String(30))
    student_no: Mapped[str | None] = mapped_column(String(40))
    bio: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    # set when an admin creates the account or sets a temporary password; cleared when the user changes it
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_staff(self) -> bool:
        return self.role in (ROLE_ADMIN, ROLE_FACULTY)

    @property
    def track(self) -> str:
        return "elementary" if self.major == "elementary" else "secondary"

    @property
    def major_label(self) -> str:
        return MAJORS.get(self.major or "", "—")

    @property
    def initials(self) -> str:
        parts = [p for p in self.full_name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"


class AuthToken(Base):
    """One-time tokens for email verification and password reset (only the hash is stored)."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # verify | reset
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
