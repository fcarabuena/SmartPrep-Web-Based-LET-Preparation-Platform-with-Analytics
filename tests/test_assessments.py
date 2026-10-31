import re
from datetime import timedelta

from sqlalchemy import select

from app.db import utcnow
from app.models import Assessment, Attempt, AttemptAnswer, Category, Course, Question
from app.services.assessments import expire_overdue, grade_rows, start_attempt, submit_attempt
from app.services.curriculum import seed_curriculum
from app.services.seed_content import seed_sample_questions
from tests.conftest import get_csrf, make_user, post


def _setup(db):
    seed_curriculum(db)
    seed_sample_questions(db)


def _course(db, name):
    return db.scalar(select(Course).where(Course.name == name))


def make_assessment(db, course_name="Assessment of Learning", **kw) -> Assessment:
    course = _course(db, course_name)
    a = Assessment(title=kw.pop("title", "Quiz on " + course_name), kind=kw.pop("kind", "practice"),
                   category_id=course.category_id, course_id=course.id, question_count=kw.pop("question_count", 5),
                   is_published=kw.pop("is_published", True), **kw)
    db.add(a)
    db.commit()
    return a


def _answer_all(db, attempt: Attempt, correct_n: int) -> dict:
    """Build form answers: first `correct_n` correct, the rest wrong."""
    data = {}
    for i, ans in enumerate(sorted(attempt.answers, key=lambda x: x.position)):
        q = db.get(Question, ans.question_id)
        wrong = next(x for x in "ABCD" if x != q.correct)
        data[f"ans_{ans.id}"] = q.correct if i < correct_n else wrong
    return data


def test_faculty_creates_assessment_via_form(faculty_client, db):
    _setup(db)
    course = _course(db, "Assessment of Learning")
    r = post(faculty_client, "/assessments/new", {
        "title": "Principles Quiz", "kind": "practice", "category_id": course.category_id, "course_id": course.id,
        "question_count": 5, "selection_mode": "auto", "difficulty": "mixed", "randomize_questions": "true",
        "time_limit_minutes": "10", "due_at": "2099-01-01T17:00", "is_published": "true", "points_per_correct": 1,
        "pass_bonus": 10,
    }, csrf_from="/assessments/new")
    assert "Assessment created" in r.text
    a = db.scalar(select(Assessment).where(Assessment.title == "Principles Quiz"))
    assert a.is_published and a.time_limit_minutes == 10
    assert a.due_at.hour == 9  # 17:00 PH time = 09:00 UTC
    # validation: course outside category
    other = db.scalar(select(Category).where(Category.code == "gen_ed"))
    r = post(faculty_client, "/assessments/new", {"title": "Bad", "kind": "practice", "category_id": other.id,
                                                  "course_id": course.id, "question_count": 5},
             csrf_from="/assessments/new")
    assert r.status_code == 400 and "does not belong" in r.text


def test_take_quiz_full_flow(student_client, db, student):
    _setup(db)
    a = make_assessment(db, time_limit_minutes=30)
    page = student_client.get("/quizzes")
    assert a.title in page.text
    r = post(student_client, f"/assessments/{a.id}/start", csrf_from=f"/assessments/{a.id}/start")
    attempt = db.scalar(select(Attempt).where(Attempt.user_id == student.id))
    assert attempt.status == "in_progress" and attempt.total_questions == 5 and attempt.threshold == 75
    assert attempt.deadline_at is not None
    assert "Question 1 of 5" in r.text
    # autosave via JSON API with CSRF header
    first = attempt.answers[0]
    token = get_csrf(student_client, f"/attempts/{attempt.id}")
    q = db.get(Question, first.question_id)
    res = student_client.post(f"/api/attempts/{attempt.id}/save", json={"answers": {str(first.id): q.correct},
                                                                       "times": {str(first.id): 12}},
                              headers={"X-CSRF-Token": token})
    assert res.json()["ok"]
    db.refresh(first)
    assert first.chosen == q.correct and first.time_spent_seconds == 12
    # autosave without CSRF is rejected
    assert student_client.post(f"/api/attempts/{attempt.id}/save", json={}).status_code == 403
    # submit 4/5 correct -> 80% passes the 75% threshold
    data = _answer_all(db, attempt, 4)
    r = post(student_client, f"/attempts/{attempt.id}/submit", data, csrf_from=f"/attempts/{attempt.id}")
    assert "80%" in r.text and "PASSED" in r.text and "Rationalization" in r.text
    db.refresh(attempt)
    assert attempt.status == "submitted" and attempt.correct_count == 4 and attempt.passed
    # grades page
    g = student_client.get("/grades")
    assert "Passed" in g.text and a.title in g.text
    pdf = student_client.get("/grades.pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")


def test_thresholds_increase_per_attempt(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    a = make_assessment(db)
    expected = [75, 80, 85, 85]
    for i, threshold in enumerate(expected, start=1):
        at = start_attempt(db, a, student)
        assert at.attempt_no == i and at.threshold == threshold
        for ans in at.answers:
            ans.chosen = db.get(Question, ans.question_id).correct if ans.position < 4 else None
        submit_attempt(db, at)  # 4/5 = 80%
        assert at.passed == (80 >= threshold)


def test_max_attempts_and_access_code(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    a = make_assessment(db, max_attempts=1, access_code="LET2026")
    from app.services.assessments import AttemptError

    try:
        start_attempt(db, a, student, "wrong")
        raise AssertionError("expected AttemptError")
    except AttemptError as exc:
        assert "access code" in str(exc)
    at = start_attempt(db, a, student, "LET2026")
    submit_attempt(db, at)
    try:
        start_attempt(db, a, student, "LET2026")
        raise AssertionError("expected AttemptError")
    except AttemptError as exc:
        assert "all 1 attempt" in str(exc)


def test_timer_enforced_server_side(student_client, db, student):
    _setup(db)
    a = make_assessment(db, time_limit_minutes=1)
    at = start_attempt(db, a, student)
    at.started_at = utcnow() - timedelta(minutes=5)
    at.deadline_at = utcnow() - timedelta(minutes=4)
    db.commit()
    # saving after the deadline auto-submits
    token = get_csrf(student_client, "/dashboard")
    r = student_client.post(f"/api/attempts/{at.id}/save", json={"answers": {}}, headers={"X-CSRF-Token": token})
    assert r.status_code == 409
    db.refresh(at)
    assert at.status == "submitted" and at.auto_submitted
    assert at.time_spent_seconds == 60  # counted only until the deadline


def test_lazy_expiry_on_page_load(student_client, db, student):
    _setup(db)
    a = make_assessment(db, time_limit_minutes=1)
    at = start_attempt(db, a, student)
    at.deadline_at = utcnow() - timedelta(minutes=2)
    db.commit()
    student_client.get("/quizzes")
    db.refresh(at)
    assert at.status == "submitted"
    assert expire_overdue(db) == 0


def test_grade_statuses(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    missing = make_assessment(db, title="Missed", due_at=utcnow() - timedelta(days=1))
    pending = make_assessment(db, title="Upcoming", due_at=utcnow() + timedelta(days=3))
    failed = make_assessment(db, title="Failed one")
    at = start_attempt(db, failed, student)
    submit_attempt(db, at)  # no answers -> 0%
    rows = {r.assessment.title: r.status for r in grade_rows(db, student)}
    assert rows == {"Missed": "Missing", "Upcoming": "Not attempted", "Failed one": "Failed"}
    assert pending  # silence linters


def test_past_due_cannot_start(student_client, db):
    _setup(db)
    a = make_assessment(db, due_at=utcnow() - timedelta(hours=1))
    page = student_client.get(f"/assessments/{a.id}/start")
    assert "Past Due" in page.text
    r = post(student_client, f"/assessments/{a.id}/start", csrf_from=f"/assessments/{a.id}/start")
    assert "Past due" in r.text


def test_major_visibility(db, client_factory):
    _setup(db)
    eng = make_assessment(db, course_name="English Major", title="English major exam", kind="mock_exam")
    math_student = client_factory(make_user(db, "student", major="math"))
    eng_student = client_factory(make_user(db, "student", major="english"))
    assert eng.title not in math_student.get("/examinations?tab=major").text
    assert eng.title in eng_student.get("/examinations?tab=major").text
    assert math_student.get(f"/assessments/{eng.id}/start").status_code == 404


def test_mock_exam_tabs_and_unpublished_hidden(student_client, db):
    _setup(db)
    make_assessment(db, course_name="Theories of Learning", title="Prof Ed Mock 1", kind="mock_exam",
                    time_limit_minutes=60)
    make_assessment(db, title="Hidden draft", kind="mock_exam", is_published=False)
    page = student_client.get("/examinations")
    assert "Prof Ed Mock 1" in page.text and "60 minutes" in page.text and "Hidden draft" not in page.text


def test_attempts_are_private(db, client_factory, student):
    _setup(db)
    a = make_assessment(db)
    at = start_attempt(db, a, student)
    submit_attempt(db, at)
    other = client_factory()
    assert other.get(f"/attempts/{at.id}/result").status_code == 404
    fac = client_factory(role="faculty")
    assert fac.get(f"/attempts/{at.id}/result").status_code == 200
    page = fac.get(f"/submissions?assessment={a.id}")
    assert student.full_name in page.text


def test_manual_pick(faculty_client, db):
    _setup(db)
    a = make_assessment(db)
    ids = list(db.scalars(select(Question.id).join(Question.topic).where(Question.status == "approved")
                          .where(Question.topic.has(course_id=a.course_id)).limit(3)))
    post(faculty_client, f"/assessments/{a.id}/questions", {"add": ids}, csrf_from=f"/assessments/{a.id}/questions")
    db.refresh(a)
    assert a.selection_mode == "manual" and a.question_count == 3
    student = make_user(db, "student", major="math")
    at = start_attempt(db, a, student)
    assert sorted(x.question_id for x in at.answers) == sorted(ids)


def test_choice_randomization_keeps_scoring_correct(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    a = make_assessment(db, randomize_choices=True, question_count=10)
    at = start_attempt(db, a, student)
    assert all(sorted(x.choice_order) == list("ABCD") for x in at.answers)
    for ans in at.answers:
        ans.chosen = db.get(Question, ans.question_id).correct
    submit_attempt(db, at)
    assert at.score_pct == 100


def test_admin_settings_change_thresholds(admin_client, db):
    data = {"threshold_1": 70, "threshold_2": 75, "threshold_3": 80,
            "w_secondary_gen_ed": 20, "w_secondary_prof_ed": 40, "w_secondary_major": 40,
            "w_elementary_gen_ed": 40, "w_elementary_prof_ed": 60, "w_elementary_major": 0,
            "band_developing": 60, "band_ready": 75, "level_step": 100, "at_risk_inactive_days": 7,
            "at_risk_readiness": 60, "recommendation_cap": 5, "allow_registration": "true"}
    from app.services.settings_store import DEFAULTS, threshold_for_attempt

    for k, v in DEFAULTS["points"].items():
        data[f"pt_{k}"] = v
    r = post(admin_client, "/admin/settings", data, csrf_from="/admin/settings")
    assert "Settings saved" in r.text
    assert threshold_for_attempt(db, 1) == 70 and threshold_for_attempt(db, 5) == 80
    data["w_secondary_major"] = 10
    r = post(admin_client, "/admin/settings", data, csrf_from="/admin/settings")
    assert r.status_code == 400 and "must add up to 100" in r.text


def test_take_page_does_not_leak_answer_key(student_client, db, student):
    _setup(db)
    a = make_assessment(db)
    at = start_attempt(db, a, student)
    html = student_client.get(f"/attempts/{at.id}").text
    assert "Rationalization" not in html and "correct answer" not in html.lower()
    assert not re.search(r'data-correct', html)
    assert db.scalar(select(AttemptAnswer).where(AttemptAnswer.attempt_id == at.id)) is not None
