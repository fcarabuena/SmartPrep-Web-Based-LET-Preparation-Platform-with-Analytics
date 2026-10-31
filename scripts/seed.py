"""Seed the LET content structure (categories, courses, topics) and default badges/questions.

Idempotent: safe to run more than once.
    .venv\\Scripts\\python scripts\\seed.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.services.curriculum import seed_curriculum  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        created = seed_curriculum(db)
        print(f"Curriculum: {created}")
        try:
            from app.services.seed_content import seed_badges, seed_sample_questions
        except ImportError:
            return
        print(f"Badges: {seed_badges(db)} created")
        print(f"Sample questions/resources: {seed_sample_questions(db)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
