from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow

KIND_PRACTICE = "practice"
KIND_MOCK = "mock_exam"
KIND_GAME = "game"
KIND_QUIZ_BEE = "quiz_bee"
ASSESSMENT_KINDS = {
    KIND_PRACTICE: "Practice Quiz",
    KIND_MOCK: "Mock Exam (LET Simulation)",
    KIND_GAME: "Timed Quiz Game",
    KIND_QUIZ_BEE: "Quiz Bee",
}

assessment_topics = Table(
    "assessment_topics",
    Base.metadata,
    Column("assessment_id", ForeignKey("assessments.id", ondelete="CASCADE"), primary_key=True),
    Column("topic_id", ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default=KIND_PRACTICE, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), index=True)
    question_count: Mapped[int] = mapped_column(Integer, default=10)
    selection_mode: Mapped[str] = mapped_column(String(10), default="auto")  # auto | manual
    difficulty: Mapped[str] = mapped_column(String(10), default="mixed")  # easy|medium|hard|mixed
    randomize_questions: Mapped[bool] = mapped_column(Boolean, default=True)
    randomize_choices: Mapped[bool] = mapped_column(Boolean, default=False)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer)
    access_code: Mapped[str | None] = mapped_column(String(40))
    open_at: Mapped[datetime | None] = mapped_column(DateTime)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    max_attempts: Mapped[int | None] = mapped_column(Integer)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    points_per_correct: Mapped[int] = mapped_column(Integer, default=1)
    pass_bonus: Mapped[int] = mapped_column(Integer, default=10)
    leaderboard_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    category: Mapped["Category | None"] = relationship()  # noqa: F821
    course: Mapped["Course | None"] = relationship()  # noqa: F821
    topics: Mapped[list["Topic"]] = relationship(secondary=assessment_topics)  # noqa: F821
    items: Mapped[list["AssessmentQuestion"]] = relationship(
        back_populates="assessment", order_by="AssessmentQuestion.position", cascade="all, delete-orphan"
    )

    @property
    def kind_label(self) -> str:
        return ASSESSMENT_KINDS.get(self.kind, self.kind)

    @property
    def is_exam(self) -> bool:
        return self.kind == KIND_MOCK


class AssessmentQuestion(Base):
    """Manually picked questions for an assessment."""

    __tablename__ = "assessment_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    assessment: Mapped[Assessment] = relationship(back_populates="items")
    question: Mapped["Question"] = relationship()  # noqa: F821


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        Index("ix_attempts_user_assessment", "user_id", "assessment_id"),
        Index("ix_attempts_status_submitted", "status", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assessment_id: Mapped[int | None] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(20), default=KIND_PRACTICE)
    is_adaptive: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str | None] = mapped_column(String(200))  # for adaptive sets without an assessment
    status: Mapped[str] = mapped_column(String(15), default="in_progress", index=True)  # in_progress|submitted
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime)
    auto_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    score_pct: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float, default=75.0)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship()  # noqa: F821
    assessment: Mapped[Assessment | None] = relationship()
    answers: Mapped[list["AttemptAnswer"]] = relationship(
        back_populates="attempt", order_by="AttemptAnswer.position", cascade="all, delete-orphan"
    )

    @property
    def display_title(self) -> str:
        if self.assessment is not None:
            return self.assessment.title + (" (Adaptive)" if self.is_adaptive else "")
        return self.title or "Adaptive Practice"


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    choice_order: Mapped[str] = mapped_column(String(4), default="ABCD")  # display order of original letters
    chosen: Mapped[str | None] = mapped_column(String(1))  # original letter A-D
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)

    attempt: Mapped[Attempt] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship()  # noqa: F821
