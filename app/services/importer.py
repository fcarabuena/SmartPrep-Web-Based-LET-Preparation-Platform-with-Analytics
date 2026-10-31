"""CSV / Excel question import: template, parsing, row-level validation."""
import csv
import io

from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Course, Question, Topic
from app.services.content import stem_hash, validate_question

COLUMNS = ["course", "topic", "stem", "choice_a", "choice_b", "choice_c", "choice_d", "correct",
           "rationalization", "difficulty", "competency", "source_url", "topic_id"]
REQUIRED = ["stem", "choice_a", "choice_b", "choice_c", "choice_d", "correct"]
MAX_ROWS = 1000

EXAMPLE = {
    "course": "Assessment of Learning",
    "topic": "Principles of Assessment",
    "stem": "A teacher gives a short quiz at the start of a unit to find out what students already know. "
            "What type of assessment is this?",
    "choice_a": "Diagnostic assessment",
    "choice_b": "Summative assessment",
    "choice_c": "Placement by ranking",
    "choice_d": "Norm-referenced grading",
    "correct": "A",
    "rationalization": "A is correct: diagnostic assessment identifies prior knowledge before instruction. "
                       "B is given at the end of instruction; C and D describe uses of scores, not the purpose here.",
    "difficulty": "easy",
    "competency": "Identify purposes of assessment",
    "source_url": "",
    "topic_id": "",
}


def template_csv() -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    w.writerow(EXAMPLE)
    return buf.getvalue().encode("utf-8-sig")


def template_xlsx(db: Session) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Questions"
    ws.append(COLUMNS)
    ws.append([EXAMPLE[c] for c in COLUMNS])
    for col, width in zip("ABCDEFGHIJKLM", (24, 26, 60, 26, 26, 26, 26, 8, 60, 10, 30, 30, 9)):
        ws.column_dimensions[col].width = width
    ref = wb.create_sheet("Topics (reference)")
    ref.append(["topic_id", "category", "course", "topic"])
    rows = db.execute(
        select(Topic.id, Course.name, Topic.name, Course.category_id).join(Course).order_by(Course.category_id, Course.sort_order, Topic.sort_order)
    ).all()
    from app.models import Category

    cats = dict(db.execute(select(Category.id, Category.name)).all())
    for tid, course, topic, cat_id in rows:
        ref.append([tid, cats.get(cat_id, ""), course, topic])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parse_file(filename: str, data: bytes) -> tuple[list[dict], str | None]:
    """Return (rows, error). Header names are normalized to lowercase snake_case."""
    name = (filename or "").lower()
    try:
        if name.endswith(".xlsx"):
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            it = ws.iter_rows(values_only=True)
            header = next(it, None)
            if not header:
                return [], "The spreadsheet is empty."
            keys = [str(h or "").strip().lower().replace(" ", "_") for h in header]
            rows = []
            for values in it:
                if values is None or all(v in (None, "") for v in values):
                    continue
                rows.append({k: ("" if v is None else str(v)).strip() for k, v in zip(keys, values)})
        elif name.endswith(".csv"):
            text = data.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = []
            for r in reader:
                row = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in r.items()}
                if any(row.values()):
                    rows.append(row)
        else:
            return [], "Upload a .csv or .xlsx file."
    except UnicodeDecodeError:
        return [], "CSV must be UTF-8 encoded."
    except Exception:
        return [], "Could not read the file. Make sure it matches the template."
    if not rows:
        return [], "No data rows found."
    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        return [], "Missing required column(s): " + ", ".join(missing)
    if len(rows) > MAX_ROWS:
        return [], f"Too many rows (max {MAX_ROWS} per import)."
    return rows, None


def validate_rows(db: Session, rows: list[dict], default_topic_id: int | None = None) -> list[dict]:
    """Annotate each row with topic_id resolution, errors and duplicate status."""
    topic_lookup = {
        (c.lower(), t.lower()): tid
        for tid, c, t in db.execute(select(Topic.id, Course.name, Topic.name).join(Course)).all()
    }
    topic_ids = set(db.scalars(select(Topic.id)))
    seen: set[str] = set()
    out = []
    for i, row in enumerate(rows, start=2):  # row 1 is the header
        data = {k: (row.get(k) or "").strip() for k in COLUMNS}
        data["correct"] = data["correct"].upper()[:1]
        data["difficulty"] = (data["difficulty"] or "medium").lower()
        errors = validate_question(data)
        tid = None
        if data["topic_id"]:
            try:
                tid = int(float(data["topic_id"]))
            except ValueError:
                errors.append("topic_id must be a number.")
            if tid is not None and tid not in topic_ids:
                errors.append(f"topic_id {tid} does not exist.")
                tid = None
        elif data["course"] and data["topic"]:
            tid = topic_lookup.get((data["course"].lower(), data["topic"].lower()))
            if tid is None:
                errors.append(f"Unknown course/topic: {data['course']} › {data['topic']}.")
        elif default_topic_id:
            tid = default_topic_id
        else:
            errors.append("Provide topic_id, or course and topic, or choose a default topic.")
        h = stem_hash(data["stem"]) if data["stem"] else ""
        duplicate = False
        if h:
            if h in seen:
                errors.append("Duplicate of another row in this file.")
            elif db.scalar(select(func.count(Question.id)).where(Question.stem_hash == h)):
                duplicate = True
                errors.append("A question with the same stem already exists in the bank.")
            seen.add(h)
        out.append({"row": i, "data": data, "topic_id": tid, "errors": errors, "duplicate": duplicate})
    return out
