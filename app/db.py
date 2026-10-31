"""Database engine/session setup. Works with PostgreSQL (Neon) and SQLite."""
from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC timestamp (all DB datetimes are naive UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_engine(url: str):
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        eng = create_engine(url, **kwargs)

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    # Neon closes idle connections; keep the pool small and recycle often.
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=280)


engine = make_engine(settings.sqlalchemy_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


def get_db(request: Request) -> Iterator[Session]:
    db = SessionLocal()
    request.state.db = db
    try:
        yield db
    finally:
        db.close()
