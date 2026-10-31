import io
import re

from openpyxl import Workbook
from sqlalchemy import select

from app.models import Course, Question, Resource, ResourceView, Topic
from app.services.content import stem_hash, validate_question
from app.services.curriculum import seed_curriculum
from app.services.seed_content import seed_badges, seed_sample_questions
from app.services.seed_data.questions import SAMPLE_QUESTIONS
from tests.conftest import get_csrf, post

STEM = "Which of the following best describes the purpose of a table of specifications in test construction?"


def _topic(db, course="Assessment of Learning", topic="Principles of Assessment") -> Topic:
    return db.scalar(select(Topic).join(Course).where(Course.name == course, Topic.name == topic))


def _qdata(topic_id, stem=STEM, **kw):
    d = {"topic_id": topic_id, "stem": stem, "choice_a": "Ensure balanced coverage", "choice_b": "Speed up scoring",
         "choice_c": "Rank students", "choice_d": "Compute grades", "correct": "A",
         "rationalization": "A is right because...", "difficulty": "medium", "competency": "Test planning",
         "status": "approved"}
    d.update(kw)
    return d


def test_seed_questions_are_valid_and_unique(db):
    seed_curriculum(db)
    hashes = set()
    total = 0
    for (course, topic), items in SAMPLE_QUESTIONS.items():
        assert len(items) == 10, (course, topic)
        for stem, a, b, c, d, correct, rat, diff, comp in items:
            data = {"stem": stem, "choice_a": a, "choice_b": b, "choice_c": c, "choice_d": d, "correct": correct,
                    "difficulty": diff}
            assert validate_question(data) == [], stem
            assert rat and comp
            hashes.add(stem_hash(stem))
            total += 1
    assert len(hashes) == total == 100
    res = seed_sample_questions(db)
    assert res["questions"] == 100 and res["resources"] >= 8
    assert seed_sample_questions(db) == {"questions": 0, "resources": 0}
    assert seed_badges(db) == 6 and seed_badges(db) == 0


def test_students_cannot_manage_content(student_client):
    for url in ("/questions", "/questions/review", "/questions/import", "/resources", "/content/categories"):
        assert student_client.get(url).status_code == 403, url


def test_structure_crud(faculty_client, db):
    seed_curriculum(db)
    course = db.scalar(select(Course).where(Course.name == "English"))
    r = post(faculty_client, "/content/topics", {"course_id": course.id, "name": "Idioms and Expressions"})
    assert "Topic created" in r.text
    t = db.scalar(select(Topic).where(Topic.name == "Idioms and Expressions"))
    post(faculty_client, f"/content/topics/{t.id}/edit", {"name": "Idiomatic Expressions", "sort_order": 9})
    db.refresh(t)
    assert t.name == "Idiomatic Expressions"
    # faculty cannot create categories
    assert post(faculty_client, "/content/categories", {"name": "X", "code": "x"}).status_code == 403
    post(faculty_client, f"/content/topics/{t.id}/delete")
    db.expire_all()
    assert db.scalar(select(Topic).where(Topic.name == "Idiomatic Expressions")) is None


def test_question_create_and_duplicate_block(faculty_client, db):
    seed_curriculum(db)
    t = _topic(db)
    r = post(faculty_client, "/questions/new", _qdata(t.id), csrf_from="/questions/new")
    assert "Question saved" in r.text
    q = db.scalar(select(Question))
    assert q.status == "approved" and q.source_type == "manual" and q.reviewed_by_id
    # exact duplicate (different punctuation/case) is blocked
    r = post(faculty_client, "/questions/new", _qdata(t.id, stem=STEM.upper().replace("?", " ?")),
             csrf_from="/questions/new")
    assert r.status_code == 400 and "identical question already exists" in r.text
    # duplicate API
    r = faculty_client.get("/api/questions/duplicates", params={"stem": STEM})
    assert r.json()["items"][0]["id"] == q.id


def test_question_validation(faculty_client, db):
    seed_curriculum(db)
    t = _topic(db)
    r = post(faculty_client, "/questions/new", _qdata(t.id, choice_b="Ensure balanced coverage", correct="E"),
             csrf_from="/questions/new")
    assert r.status_code == 400
    assert "Choices must be different" in r.text and "Correct answer must be A" in r.text


def test_question_bank_filters_and_edit(faculty_client, db):
    seed_curriculum(db)
    seed_sample_questions(db)
    r = faculty_client.get("/questions", params={"q": "ORGANELLE"})
    assert "cellular respiration" in r.text and "Pavlov" not in r.text
    q = db.scalar(select(Question).where(Question.stem.like("%Pavlov%")))
    r = faculty_client.get("/questions", params={"topic": q.topic_id, "difficulty": "easy"})
    assert "Pavlov" in r.text
    data = _qdata(q.topic_id, stem=q.stem, choice_a=q.choice_a, choice_b=q.choice_b, choice_c=q.choice_c,
                  choice_d=q.choice_d, correct=q.correct, difficulty="hard")
    post(faculty_client, f"/questions/{q.id}/edit", data, csrf_from=f"/questions/{q.id}/edit")
    db.refresh(q)
    assert q.difficulty == "hard"


def test_review_queue(faculty_client, db, faculty):
    seed_curriculum(db)
    t = _topic(db)
    q = Question(topic_id=t.id, stem="A scraped question about validity of tests for review?", choice_a="a",
                 choice_b="b", choice_c="c", choice_d="d", correct="B", source_type="scraped", status="pending_review",
                 stem_hash="x1")
    db.add(q)
    db.commit()
    page = faculty_client.get("/questions/review")
    assert "A scraped question" in page.text
    post(faculty_client, f"/questions/{q.id}/review", {"decision": "approved", "note": "ok"}, csrf_from="/questions/review")
    db.refresh(q)
    assert q.status == "approved" and q.reviewed_by_id == faculty.id and q.review_note == "ok"


def test_bulk_actions(faculty_client, db):
    seed_curriculum(db)
    seed_sample_questions(db)
    ids = list(db.scalars(select(Question.id).limit(3)))
    client_data = {"action": "draft", "ids": ids, "back": "/questions"}
    post(faculty_client, "/questions/bulk", client_data)
    db.expire_all()
    assert all(db.get(Question, i).status == "draft" for i in ids)


def test_csv_import_preview_and_confirm(faculty_client, db):
    seed_curriculum(db)
    t = _topic(db)
    csv_text = (
        "course,topic,stem,choice_a,choice_b,choice_c,choice_d,correct,rationalization,difficulty,competency,source_url,topic_id\n"
        f"Assessment of Learning,Principles of Assessment,{STEM},A1,B1,C1,D1,A,why,easy,c,,\n"
        f",,Second imported question stem about rubrics here?,r1,r2,r3,r4,C,why,medium,c,,{t.id}\n"
        "Unknown,Topic,Bad row with an unknown topic name in it?,x,y,z,w,Z,,weird,,,\n"
    )
    token = get_csrf(faculty_client, "/questions/import")
    r = faculty_client.post("/questions/import", data={"csrf_token": token, "status": "pending_review"},
                            files={"file": ("q.csv", csv_text.encode(), "text/csv")})
    assert r.status_code == 200
    assert "2 valid" in r.text and "Unknown course/topic" in r.text and "Correct answer must be A" in r.text
    payload = re.search(r'name="payload" value="([^"]*)"', r.text).group(1)
    import html

    r = post(faculty_client, "/questions/import/confirm", {"payload": html.unescape(payload), "status": "pending_review"},
             csrf_from="/questions/import")
    assert "Imported 2 question(s)" in r.text
    qs = db.scalars(select(Question)).all()
    assert len(qs) == 2 and all(q.source_type == "csv_import" and q.status == "pending_review" for q in qs)


def test_xlsx_import_and_templates(faculty_client, db):
    seed_curriculum(db)
    assert faculty_client.get("/questions/import/template.csv").text.startswith("﻿course,topic,stem")
    tpl = faculty_client.get("/questions/import/template.xlsx")
    assert tpl.status_code == 200 and tpl.content[:2] == b"PK"
    wb = Workbook()
    ws = wb.active
    ws.append(["Course", "Topic", "Stem", "Choice A", "Choice B", "Choice C", "Choice D", "Correct"])
    ws.append(["Assessment of Learning", "Principles of Assessment", STEM, "a", "b", "c", "d", "b"])
    buf = io.BytesIO()
    wb.save(buf)
    token = get_csrf(faculty_client, "/questions/import")
    r = faculty_client.post("/questions/import", data={"csrf_token": token},
                            files={"file": ("q.xlsx", buf.getvalue(), "application/octet-stream")})
    assert "1 valid" in r.text


def test_resources_link_and_upload(faculty_client, student_client_factory, db):
    seed_curriculum(db)
    t = _topic(db)
    r = post(faculty_client, "/resources/new", {"title": "Validity explained", "kind": "video",
                                                "url": "https://example.com/v", "topic_id": t.id,
                                                "level": "foundational", "approved": "true"}, csrf_from="/resources/new")
    assert "Resource added" in r.text
    token = get_csrf(faculty_client, "/resources/new")
    pdf = b"%PDF-1.4\n%test\n"
    r = faculty_client.post("/resources/new", data={"csrf_token": token, "title": "Handout", "kind": "file",
                                                    "topic_id": t.id, "level": "standard", "approved": "true"},
                            files={"file": ("handout.pdf", pdf, "application/pdf")})
    assert "Resource added" in r.text
    res = db.scalar(select(Resource).where(Resource.title == "Handout"))
    assert res.file_id
    # bad upload: wrong magic bytes / disallowed type
    token = get_csrf(faculty_client, "/resources/new")
    r = faculty_client.post("/resources/new", data={"csrf_token": token, "title": "Bad", "kind": "file",
                                                    "level": "standard"},
                            files={"file": ("evil.exe", b"MZ...", "application/octet-stream")})
    assert r.status_code == 400 and "File type not allowed" in r.text
    token = get_csrf(faculty_client, "/resources/new")
    r = faculty_client.post("/resources/new", data={"csrf_token": token, "title": "Fake pdf", "kind": "file",
                                                    "level": "standard"},
                            files={"file": ("fake.pdf", b"<html>", "application/pdf")})
    assert "does not match" in r.text
    token = get_csrf(faculty_client, "/resources/new")
    r = faculty_client.post("/resources/new", data={"csrf_token": token, "title": "Big", "kind": "file",
                                                    "level": "standard"},
                            files={"file": ("big.pdf", b"%PDF" + b"0" * (5 * 1024 * 1024), "application/pdf")})
    assert "too large" in r.text

    student = student_client_factory()
    page = student.get("/materials", params={"q": "validity"})
    assert "Validity explained" in page.text and "Handout" not in page.text
    r = student.get(f"/r/{res.id}", follow_redirects=False)
    assert r.headers["location"] == f"/files/{res.file_id}"
    f = student.get(f"/files/{res.file_id}")
    assert f.content == pdf and f.headers["content-type"] == "application/pdf"
    assert db.scalar(select(ResourceView).where(ResourceView.resource_id == res.id)) is not None
    # hidden resources are not reachable by students
    res.approved = False
    db.commit()
    assert student.get(f"/files/{res.file_id}").status_code == 404
    assert student.get(f"/r/{res.id}").status_code == 404


def test_materials_respect_major(db, student_client, student):
    seed_curriculum(db)
    seed_sample_questions(db)
    page = student_client.get("/materials")  # student major = math
    assert "Khan Academy: Arithmetic" in page.text
    assert "introduction to linguistics" not in page.text.lower()  # English-major resource hidden
