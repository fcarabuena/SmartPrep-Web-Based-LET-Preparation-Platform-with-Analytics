"""Dialect-aware SQL helpers so analytics aggregate in the database on both PostgreSQL and SQLite.

Times are stored as naive UTC; grouping happens in Philippine time (UTC+8).
"""
from sqlalchemy import Interval, Integer, cast, extract, func, literal_column, text
from sqlalchemy.orm import Session


def _dialect(db: Session) -> str:
    return db.get_bind().dialect.name


def local_ts(db: Session, col):
    if _dialect(db) == "sqlite":
        return func.datetime(col, "+8 hours")
    return col + literal_column("INTERVAL '8 hours'", type_=Interval)


def local_day(db: Session, col):
    """Calendar date (as 'YYYY-MM-DD' text on SQLite, date on PostgreSQL)."""
    return func.date(local_ts(db, col))


def local_hour(db: Session, col):
    return cast(extract("hour", local_ts(db, col)), Integer)


def local_dow(db: Session, col):
    """Day of week, 0 = Sunday … 6 = Saturday, on both dialects."""
    return cast(extract("dow", local_ts(db, col)), Integer)


def database_size_bytes(db: Session) -> int | None:
    try:
        if _dialect(db) == "sqlite":
            pages = db.execute(text("PRAGMA page_count")).scalar() or 0
            size = db.execute(text("PRAGMA page_size")).scalar() or 0
            return int(pages * size)
        return int(db.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
    except Exception:
        return None
