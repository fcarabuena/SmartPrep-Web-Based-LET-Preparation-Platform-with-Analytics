from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db import utcnow
from app.models import ActivityLog, Attempt, Category, Message, Notification, Question, Topic
from app.services.analytics import (
    admin_metrics,
    at_risk_students,
    class_overview,
    item_analysis,
    readiness,
    readiness_from_stats,
    student_progress,
    zone,
)
from app.services.assessments import start_attempt, submit_attempt
from app.services.cache import clear_cache
from app.services.curriculum import seed_curriculum
from app.services.seed_content import seed_badges, seed_sample_questions
from tests.conftest import make_user, post
from tests.test_assessments import make_assessment
from tests.test_gamification import _take


def _setup(db):
    seed_curriculum(db)
    seed_sample_questions(db)
    seed_badges(db)


def test_zone_thresholds():
    assert zone(None) == "none" and zone(74.9) == "red" and zone(75) == "yellow"
    assert zone(84.9) == "yellow" and zone(85) == "green"


def test_readiness_weights_and_bands(db):
    # secondary: gen 20, prof 40, major 40
    r = readiness_from_stats(db, "secondary", {"gen_ed": (10, 10), "prof_ed": (10, 5), "major": (10, 8)})
    assert r["score"] == 20 + 20 + 32 and r["band"] == "Developing"
    r = readiness_from_stats(db, "secondary", {"gen_ed": (10, 8), "prof_ed": (10, 8), "major": (10, 8)})
    assert r["score"] == 80 and r["band"] == "Ready"
    r = readiness_from_stats(db, "elementary", {"gen_ed": (10, 6), "prof_ed": (10, 6)})
    assert r["score"] == 60 and r["band"] == "Developing"
    assert [p["code"] for p in r["parts"]] == ["gen_ed", "prof_ed"]  # major weight 0 is hidden
    assert readiness_from_stats(db, "secondary", {})["band"] == "Not ready"


def test_student_progress_numbers(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    a = make_assessment(db, question_count=5)  # Prof Ed / Assessment of Learning
    _take(db, student, a, 2)  # exam 1: 40%
    _take(db, student, a, 5)  # exam 2: 100%
    p = student_progress(db, student)
    prof = next(c for c in p["categories"] if c["code"] == "prof_ed")
    assert prof["answered"] == 10 and prof["pct"] == 70.0
    assert prof["exam1"] == 40.0 and prof["exam2"] == 100.0 and prof["improvement"] == 60.0
    course = next(c for c in p["courses"] if c["name"] == "Assessment of Learning")
    assert course["correct_pct"] == 70.0 and course["incorrect_pct"] == 30.0 and course["improvement"] == 60.0
    heat = next(r for r in p["heat_exams"] if r["course"] == "Assessment of Learning")
    assert [c["zone"] for c in heat["cells"]] == ["red", "green", "none"]
    assert p["attempts"] == 2 and p["questions"] == 10
    assert p["trend"][-1]["attempts"] == 2 and p["trend"][-1]["avg"] == 70.0
    r = readiness(db, student)
    assert r["score"] == 28.0  # prof ed 70% x 40%


def test_progress_page_and_dashboard_render(student_client, db, student):
    _setup(db)
    a = make_assessment(db, question_count=5)
    _take(db, student, a, 3)
    clear_cache()
    page = student_client.get("/progress")
    assert "Study Hot Zones" in page.text and "Mastery by category" in page.text and "chart.umd.min.js" in page.text
    assert student_client.get("/progress?mode=exams&category=0").status_code == 200
    dash = student_client.get("/dashboard")
    assert "LET Readiness Score" in dash.text and "Not ready" in dash.text


def test_item_analysis_indices(db):
    _setup(db)
    a = make_assessment(db, question_count=5, randomize_questions=False)
    # 10 examinees with scores 0..5 correct (first attempts)
    for i in range(10):
        _take(db, make_user(db, "student", major="math"), a, i % 6)
    data = item_analysis(db, a.id)
    assert data["examinees"] == 10 and data["group_size"] == 3
    for it in data["items"]:
        assert 0 <= it["p"] <= 1
        assert it["d"] is None or -1 <= it["d"] <= 1
    assert sum(sum(it["choices"].values()) for it in data["items"]) == 50


def test_item_analysis_flags_bad_key(db):
    _setup(db)
    a = make_assessment(db, question_count=10, randomize_questions=False)  # whole topic pool: same items for all
    students = [make_user(db, "student", major="math") for _ in range(8)]
    # strong students answer everything right except Q0 (wrong); weak ones get only Q0 right
    for idx, s in enumerate(students):
        at = start_attempt(db, a, s)
        ordered = sorted(at.answers, key=lambda x: x.question_id)
        for j, ans in enumerate(ordered):
            q = db.get(Question, ans.question_id)
            strong = idx < 4
            right = (j != 0) if strong else (j == 0)
            ans.chosen = q.correct if right else next(x for x in "ABCD" if x != q.correct)
        db.commit()
        submit_attempt(db, at)
    q0 = min(x.question_id for x in at.answers)
    clear_cache()
    item = next(it for it in item_analysis(db, a.id)["items"] if it["question"].id == q0)
    assert item["d"] < 0 and item["decision"] == "Reject / rewrite"


def test_class_overview_and_at_risk(db):
    _setup(db)
    a = make_assessment(db, question_count=5)
    good = make_user(db, "student", major="math", full_name="Good Student")
    weak = make_user(db, "student", major="math", full_name="Weak Student")
    idle = make_user(db, "student", major="math", full_name="Idle Student")
    idle.created_at = idle.last_seen_at = utcnow() - timedelta(days=20)
    db.commit()
    _take(db, good, a, 5)
    _take(db, weak, a, 1)
    c = class_overview(db, 30)
    assert c["students"] == 3 and c["attempts"] == 2 and c["avg_score"] == 60.0 and c["pass_rate"] == 50.0
    assert c["participation"] == round(200 / 3, 1)
    risk = {r["user"].full_name: r for r in at_risk_students(db)}
    assert "Weak Student" in risk and "Idle Student" in risk
    assert any("Inactive" in x for x in risk["Idle Student"]["reasons"])


def test_faculty_pages_and_feedback(faculty_client, db, student):
    _setup(db)
    a = make_assessment(db, question_count=5)
    _take(db, student, a, 2)
    for url in ("/analytics/class", "/analytics/class?days=0", "/analytics/at-risk", "/analytics/students",
                f"/analytics/students/{student.id}", f"/analytics/items?assessment={a.id}", "/dashboard"):
        assert faculty_client.get(url).status_code == 200, url
    r = post(faculty_client, f"/analytics/students/{student.id}/feedback",
             {"subject": "Keep going", "body": "Review test construction."}, csrf_from=f"/analytics/students/{student.id}")
    assert "Feedback sent" in r.text
    msg = db.scalar(select(Message))
    assert msg.recipient_id == student.id and msg.is_feedback
    assert db.scalar(select(Notification).where(Notification.user_id == student.id, Notification.kind == "feedback"))


def test_admin_metrics_and_pages(admin_client, db, admin):
    _setup(db)
    db.add(ActivityLog(user_id=admin.id, event="login", path="/login"))
    db.commit()
    clear_cache()
    m = admin_metrics(db)
    assert m["dau"] >= 1 and len(m["logins"]) == 30 and sum(sum(r) for r in m["heat"]) >= 1
    assert m["logins"][-1]["n"] >= 1
    assert {s["source"] for s in m["sources"]} == {"manual", "csv_import", "scraped", "ai_generated"}
    for url in ("/admin/analytics", "/admin/health", "/dashboard"):
        assert admin_client.get(url).status_code == 200, url


def test_reports_preview_and_exports(admin_client, db, student):
    _setup(db)
    _take(db, student, make_assessment(db, question_count=5), 4)
    for kind in ("user_activity", "performance", "content_usage", "engagement"):
        r = admin_client.get(f"/reports?kind={kind}&preview=1")
        assert r.status_code == 200 and "rows" in r.text, kind
        csv_r = admin_client.get(f"/reports/export?fmt=csv&kind={kind}")
        assert csv_r.headers["content-type"].startswith("text/csv")
        assert admin_client.get(f"/reports/export?fmt=xlsx&kind={kind}").content[:2] == b"PK"
        assert admin_client.get(f"/reports/export?fmt=pdf&kind={kind}").content[:4] == b"%PDF"
    perf = admin_client.get("/reports/export?fmt=csv&kind=performance").text
    assert "Juan Dela Cruz" in perf and "80.0" in perf


def test_students_cannot_see_staff_analytics(student_client):
    for url in ("/analytics/class", "/analytics/at-risk", "/analytics/items", "/reports", "/admin/analytics",
                "/admin/health"):
        assert student_client.get(url).status_code == 403, url


def test_dialect_sql_compiles_for_postgres(db):
    from sqlalchemy import func

    from app.services import sqlutil

    class FakeBind:
        class dialect:
            name = "postgresql"

    class FakeSession:
        def get_bind(self):
            return FakeBind()

    fs = FakeSession()
    stmt = select(sqlutil.local_day(fs, ActivityLog.created_at), sqlutil.local_hour(fs, ActivityLog.created_at),
                  sqlutil.local_dow(fs, ActivityLog.created_at), func.count()).group_by(
        sqlutil.local_day(fs, ActivityLog.created_at))
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "INTERVAL '8 hours'" in sql and "EXTRACT(hour FROM" in sql and "EXTRACT(dow FROM" in sql


def test_category_ids_exist(db):
    seed_curriculum(db)
    assert db.scalar(select(Category).where(Category.code == "major"))
    assert db.scalar(select(Topic)) and db.scalar(select(Attempt)) is None
