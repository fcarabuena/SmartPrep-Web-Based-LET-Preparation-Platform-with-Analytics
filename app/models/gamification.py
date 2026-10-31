from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow

# Points ledger reasons
REASON_COMPLETE = "complete_quiz"
REASON_PASS = "pass"
REASON_PERFECT = "perfect_score"
REASON_IMPROVEMENT = "improvement"
REASON_SERIES = "quiz_series"
REASON_RESOURCE = "resource_view"
REASON_STREAK = "daily_streak"
REASON_CORRECT = "correct_answers"
REASON_MANUAL = "manual"
POINT_REASONS = {
    REASON_CORRECT: "Correct answers",
    REASON_COMPLETE: "Completed a quiz",
    REASON_PASS: "Passed",
    REASON_PERFECT: "Perfect score",
    REASON_IMPROVEMENT: "Improvement",
    REASON_SERIES: "Quiz series",
    REASON_RESOURCE: "Viewed a recommended resource",
    REASON_STREAK: "Daily streak",
    REASON_MANUAL: "Manual adjustment",
}

# Badge rule types (data-driven)
BADGE_RULES = {
    "accuracy": "Score >= threshold % on any quiz",
    "improvement": "Improve by >= threshold points over consecutive attempts",
    "category_mastery": "Score >= threshold % on a quiz in a category",
    "perfect": "Score 100% on a quiz",
    "streak": "Active threshold days in a row",
    "first_attempt": "Complete the first quiz",
    "points": "Earn at least threshold total points",
    "quizzes_completed": "Complete threshold quizzes",
    "manual": "Awarded manually by faculty/admin",
}


class PointsLedger(Base):
    __tablename__ = "points_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(30), index=True)
    ref_type: Mapped[str | None] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(50), default="award")  # Bootstrap icon name
    color: Mapped[str] = mapped_column(String(20), default="primary")
    rule_type: Mapped[str] = mapped_column(String(30), default="manual")
    threshold: Mapped[float] = mapped_column(Float, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserBadge(Base):
    __tablename__ = "user_badges"
    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    badge_id: Mapped[int] = mapped_column(ForeignKey("badges.id", ondelete="CASCADE"), index=True)
    context: Mapped[str | None] = mapped_column(String(255))
    awarded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    badge: Mapped[Badge] = relationship()
