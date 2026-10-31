"""Content helpers: topic pickers, question validation and duplicate detection, uploads."""
import hashlib
import re
import unicodedata

from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import Category, Course, Question, StoredFile, Topic
from app.models.content import DIFFICULTIES, QUESTION_STATUSES, SOURCE_TYPES
from app.services.cache import cached

ALLOWED_UPLOADS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# leading bytes for a basic content sniff
MAGIC = {
    ".pdf": [b"%PDF"],
    ".docx": [b"PK\x03\x04"],
    ".pptx": [b"PK\x03\x04"],
    ".png": [b"\x89PNG"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".webp": [b"RIFF"],
}


def normalize_stem(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stem_hash(text: str) -> str:
    return hashlib.sha256(normalize_stem(text).encode()).hexdigest()


def find_duplicates(db: Session, stem: str, exclude_id: int | None = None, limit: int = 5) -> list[Question]:
    """Exact (normalized) duplicates first, then near matches sharing the stem's opening words."""
    h = stem_hash(stem)
    stmt = select(Question).where(Question.stem_hash == h)
    if exclude_id:
        stmt = stmt.where(Question.id != exclude_id)
    exact = list(db.scalars(stmt.limit(limit)))
    if exact:
        return exact
    words = normalize_stem(stem).split()
    if len(words) < 5:
        return []
    probe = "%" + " ".join(words[:6]) + "%"
    stmt = select(Question).where(func.lower(Question.stem).like(probe))
    if exclude_id:
        stmt = stmt.where(Question.id != exclude_id)
    return list(db.scalars(stmt.limit(limit)))


def validate_question(data: dict) -> list[str]:
    errors = []
    stem = (data.get("stem") or "").strip()
    if len(stem) < 10:
        errors.append("Question stem must be at least 10 characters.")
    if len(stem) > 5000:
        errors.append("Question stem is too long (max 5000 characters).")
    choices = [(data.get(f"choice_{k}") or "").strip() for k in "abcd"]
    if any(not c for c in choices):
        errors.append("All four choices (A–D) are required.")
    elif len({c.lower() for c in choices}) < 4:
        errors.append("Choices must be different from each other.")
    if (data.get("correct") or "").upper() not in ("A", "B", "C", "D"):
        errors.append("Correct answer must be A, B, C or D.")
    if (data.get("difficulty") or "medium") not in DIFFICULTIES:
        errors.append("Difficulty must be easy, medium or hard.")
    if data.get("status") and data["status"] not in QUESTION_STATUSES:
        errors.append("Invalid status.")
    if data.get("source_type") and data["source_type"] not in SOURCE_TYPES:
        errors.append("Invalid source type.")
    url = (data.get("source_url") or "").strip()
    if url and not re.match(r"^https?://", url):
        errors.append("Source URL must start with http:// or https://")
    return errors


def apply_question(q: Question, data: dict) -> Question:
    q.stem = data["stem"].strip()
    for k in "abcd":
        setattr(q, f"choice_{k}", data[f"choice_{k}"].strip())
    q.correct = data["correct"].upper()
    q.rationalization = (data.get("rationalization") or "").strip()
    q.difficulty = data.get("difficulty") or "medium"
    q.competency = (data.get("competency") or "").strip() or None
    q.source_url = (data.get("source_url") or "").strip() or None
    q.stem_hash = stem_hash(q.stem)
    return q


def topic_tree(db: Session) -> list[Category]:
    return list(
        db.scalars(
            select(Category)
            .options(selectinload(Category.courses).selectinload(Course.topics))
            .order_by(Category.sort_order, Category.name)
        )
    )


def topic_options(db: Session) -> list[dict]:
    """Grouped options for <select>: [{"label": "Gen Ed › English", "topics": [(id, name)]}]."""

    def build():
        groups = []
        for cat in topic_tree(db):
            for course in cat.courses:
                groups.append({
                    "label": f"{cat.name} › {course.name}",
                    "topics": [(t.id, t.name) for t in course.topics],
                })
        return groups

    return cached(("topic_options",), build, ttl=30)


def nav_categories(db: Session, major: str | None) -> list[dict]:
    """Categories with courses visible to a student (major courses filtered by major)."""

    def build():
        out = []
        short = {"gen_ed": "Gen Ed", "prof_ed": "Prof Ed", "major": "Major Core"}
        for cat in topic_tree(db):
            courses = [c for c in cat.courses if not c.major or c.major == major]
            if courses:
                out.append({"id": cat.id, "name": cat.name, "code": cat.code, "short": short.get(cat.code, cat.name),
                            "courses": [{"id": c.id, "name": c.name} for c in courses]})
        return out

    return cached(("nav_categories", major), build, ttl=60)


def visible_course_filter(major: str | None):
    """SQL filter: courses without a major, or the student's major."""
    return or_(Course.major.is_(None), Course.major == (major or "__none__"))


async def read_upload(upload: UploadFile) -> tuple[bytes | None, str | None]:
    """Read an uploaded file with type and size checks. Returns (data, error)."""
    name = (upload.filename or "").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ALLOWED_UPLOADS:
        return None, "File type not allowed. Use PDF, DOCX, PPTX or an image (PNG, JPG, GIF, WEBP)."
    data = await upload.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        return None, "File is too large (max 5 MB)."
    if not data:
        return None, "The file is empty."
    if not any(data.startswith(m) for m in MAGIC[ext]):
        return None, "The file content does not match its extension."
    return data, None


def store_file(db: Session, filename: str, data: bytes, user_id: int | None) -> StoredFile:
    name = (filename or "file").replace("\\", "/").rsplit("/", 1)[-1][:200]
    ext = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""
    f = StoredFile(filename=name, content_type=ALLOWED_UPLOADS.get(ext, "application/octet-stream"), size=len(data),
                   sha256=hashlib.sha256(data).hexdigest(), data=data, uploaded_by_id=user_id)
    db.add(f)
    db.flush()
    return f


def topic_path(topic: Topic | None) -> str:
    if topic is None:
        return "—"
    return f"{topic.course.category.name} › {topic.course.name} › {topic.name}"
