from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.db import Base, utcnow

CATEGORY_GEN_ED = "gen_ed"
CATEGORY_PROF_ED = "prof_ed"
CATEGORY_MAJOR = "major"

DIFFICULTIES = ("easy", "medium", "hard")
SOURCE_TYPES = ("manual", "csv_import", "scraped", "ai_generated")
QUESTION_STATUSES = ("draft", "pending_review", "approved", "rejected")
RESOURCE_KINDS = ("video", "article", "file", "link")
RESOURCE_LEVELS = ("foundational", "standard", "advanced")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # gen_ed | prof_ed | major
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    courses: Mapped[list["Course"]] = relationship(
        back_populates="category", order_by="Course.sort_order, Course.name", cascade="all, delete-orphan"
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    major: Mapped[str | None] = mapped_column(String(30), index=True)  # set for specialization courses
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped[Category] = relationship(back_populates="courses")
    topics: Mapped[list["Topic"]] = relationship(
        back_populates="course", order_by="Topic.sort_order, Topic.name", cascade="all, delete-orphan"
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    course: Mapped[Course] = relationship(back_populates="topics")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_topic_status", "topic_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    stem: Mapped[str] = mapped_column(Text)
    choice_a: Mapped[str] = mapped_column(Text)
    choice_b: Mapped[str] = mapped_column(Text)
    choice_c: Mapped[str] = mapped_column(Text)
    choice_d: Mapped[str] = mapped_column(Text)
    correct: Mapped[str] = mapped_column(String(1))  # A-D
    rationalization: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(10), default="medium", index=True)
    competency: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    stem_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    topic: Mapped[Topic] = relationship()
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])  # noqa: F821
    reviewed_by: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by_id])  # noqa: F821

    def choice(self, letter: str) -> str:
        return getattr(self, f"choice_{letter.lower()}", "")

    @property
    def choices(self) -> dict[str, str]:
        return {k: self.choice(k) for k in "ABCD"}


class StoredFile(Base):
    """Small uploads kept in the database (no local disk in production)."""

    __tablename__ = "stored_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary))
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20), default="link")  # video|article|file|link
    url: Mapped[str | None] = mapped_column(String(1000))
    file_id: Mapped[int | None] = mapped_column(ForeignKey("stored_files.id", ondelete="SET NULL"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), index=True)
    level: Mapped[str] = mapped_column(String(20), default="standard", index=True)
    description: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="manual")
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    topic: Mapped[Topic | None] = relationship()
    file: Mapped[StoredFile | None] = relationship()


class ResourceView(Base):
    __tablename__ = "resource_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
