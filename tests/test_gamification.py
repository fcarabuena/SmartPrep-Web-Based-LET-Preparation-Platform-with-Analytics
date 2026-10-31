import random
from collections import Counter

from sqlalchemy import func, select

from app.models import Attempt, Badge, PointsLedger, Question, Resource, Topic, UserBadge
from app.services.assessments import start_attempt, submit_attempt
from app.services.curriculum import seed_curriculum
from app.services.gamification import current_streak, leaderboard, level_info, total_points
from app.services.recommendations import adaptive_question_ids, level_for, recommendations_for_attempt, study_plan
from app.services.seed_content import seed_badges, seed_sample_questions
from tests.conftest import make_user, post
from tests.test_assessments import make_assessment


def _setup(db):
    seed_curriculum(db)
    seed_sample_questions(db)
    seed_badges(db)


def _take(db, user, a, correct_n):
    at = start_attempt(db, a, user)
    for ans in sorted(at.answers, key=lambda x: x.position):
        q = db.get(Question, ans.question_id)
        ans.chosen = q.correct if ans.position < correct_n else next(x for x in "ABCD" if x != q.correct)
    db.commit()
    return submit_attempt(db, at)


def test_level_math(db):
    assert level_info(db, 0).level == 1
    assert level_info(db, 99).level == 1 and level_info(db, 100).level == 2
    assert level_info(db, 300).level == 3 and level_info(db, 299).level == 2
    lv = level_info(db, 150)
    assert lv.floor == 100 and lv.next_floor == 300 and lv.progress_pct == 25


def test_level_bands():
    assert level_for(None) == "foundational" and level_for(74.9) == "foundational"
    assert level_for(75) == "standard" and level_for(84.9) == "standard" and level_for(85) == "advanced"


def test_points_and_badges_on_submit(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    a = make_assessment(db, question_count=5, points_per_correct=2, pass_bonus=10)
    at = _take(db, student, a, 5)  # perfect score
    reasons = Counter(r.reason for r in db.scalars(select(PointsLedger).where(PointsLedger.user_id == student.id)))
    assert reasons == {"correct_answers": 1, "complete_quiz": 1, "pass": 1, "perfect_score": 1}
    # 5*2 + 5 + (10+10) + 20
    assert at.points_awarded == 55 == total_points(db, student.id)
    codes = {b.code for b in db.scalars(select(Badge).join(UserBadge).where(UserBadge.user_id == student.id))}
    assert {"first_steps", "accuracy_ace", "perfect_score", "master_of_categories"} <= codes
    assert "persistence_pro" not in codes


def test_improvement_badge_and_points(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    a = make_assessment(db, question_count=5)
    _take(db, student, a, 1)  # 20%
    at2 = _take(db, student, a, 3)  # 60% -> +40
    reasons = [r.reason for r in db.scalars(select(PointsLedger).where(PointsLedger.ref_id == at2.id))]
    assert "improvement" in reasons
    codes = {b.code for b in db.scalars(select(Badge).join(UserBadge).where(UserBadge.user_id == student.id))}
    assert "persistence_pro" in codes and "accuracy_ace" not in codes


def test_series_bonus_once_per_window(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    a = make_assessment(db, question_count=3)
    for _ in range(5):
        _take(db, student, a, 0)
    n = db.scalar(select(func.count(PointsLedger.id)).where(PointsLedger.reason == "quiz_series"))
    assert n == 1


def test_streak(db):
    from datetime import timedelta

    from app.db import utcnow

    _setup(db)
    student = make_user(db, "student", major="math")
    a = make_assessment(db, question_count=3)
    for days_ago in (2, 1, 0):
        at = _take(db, student, a, 1)
        at.submitted_at = utcnow() - timedelta(days=days_ago)
        db.commit()
    assert current_streak(db, student.id) == 3


def test_recommendations_proportional_to_wrong(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    t = db.scalar(select(Topic).where(Topic.name == "Principles of Assessment"))
    for i in range(4):
        db.add(Resource(title=f"Foundational {i}", kind="video", url=f"https://e.com/{i}", topic_id=t.id,
                        level="foundational", approved=True))
    db.add(Resource(title="Advanced read", kind="article", url="https://e.com/adv", topic_id=t.id, level="advanced",
                    approved=True))
    db.commit()
    a = make_assessment(db, question_count=5, topics=[t])
    at = _take(db, student, a, 2)  # 3 wrong in one topic
    recs = recommendations_for_attempt(db, at)
    assert recs["topics"][0]["wrong"] == 3 and recs["topics"][0]["level"] == "foundational"
    assert len(recs["resources"]) == 3
    assert all(r.level == "foundational" for r in recs["resources"])
    assert recs["topics"][0]["practice_url"] == f"/practice/topic/{t.id}"


def test_adaptive_weights_weak_topics_and_avoids_recent(db):
    _setup(db)
    student = make_user(db, "student", major="math")
    strong = db.scalar(select(Topic).where(Topic.name == "Behaviorism"))
    weak = db.scalar(select(Topic).where(Topic.name == "Principles of Assessment"))
    _take(db, student, make_assessment(db, course_name="Theories of Learning", topics=[strong], question_count=10), 10)
    _take(db, student, make_assessment(db, topics=[weak], question_count=10), 1)
    picks = Counter()
    rng = random.Random(7)
    for _ in range(40):
        ids = adaptive_question_ids(db, student, 4, topic_ids=[strong.id, weak.id], rng=rng)
        picks.update(db.get(Question, q).topic_id for q in ids)
    assert picks[weak.id] > picks[strong.id] * 3


def test_regenerate_and_study_plan_pages(student_client, db, student):
    _setup(db)
    a = make_assessment(db, question_count=5)
    at = _take(db, student, a, 1)
    r = post(student_client, f"/attempts/{at.id}/regenerate", csrf_from=f"/attempts/{at.id}/result")
    new = db.scalars(select(Attempt).where(Attempt.is_adaptive.is_(True))).one()
    assert new.title.startswith("Adaptive:") and new.total_questions == 5 and "Question 1 of 5" in r.text
    plan = study_plan(db, student)
    assert plan[0]["topic"].name == "Principles of Assessment" and plan[0]["mastery"] == 20
    page = student_client.get("/study-plan")
    assert "Principles of Assessment" in page.text and "Start practice" in page.text
    t = db.scalar(select(Topic).where(Topic.name == "Behaviorism"))
    r = post(student_client, f"/practice/topic/{t.id}", csrf_from="/study-plan")
    assert "Question 1 of 10" in r.text
    # adaptive attempts do not use up max attempts / do not appear as graded attempts
    r = post(student_client, "/practice/adaptive", csrf_from="/study-plan")
    assert r.status_code == 200


def test_resource_view_points_capped(student_client, db, student):
    _setup(db)
    t = db.scalar(select(Topic).where(Topic.name == "Principles of Assessment"))
    rs = []
    for i in range(8):
        r = Resource(title=f"R{i}", kind="link", url=f"https://e.com/r{i}", topic_id=t.id, level="foundational",
                     approved=True)
        db.add(r)
        rs.append(r)
    db.commit()
    for r in rs:
        student_client.get(f"/r/{r.id}?rec=1", follow_redirects=False)
    student_client.get(f"/r/{rs[0].id}?rec=1", follow_redirects=False)
    pts = [p.points for p in db.scalars(select(PointsLedger).where(PointsLedger.reason == "resource_view"))]
    assert sum(pts) == 10  # daily cap (2 pts each, cap 10)


def test_leaderboard_tie_break_first_attempt(db):
    _setup(db)
    a = make_assessment(db, question_count=5)
    first_try = make_user(db, "student", major="math", full_name="Zed First")
    retaker = make_user(db, "student", major="math", full_name="Amy Retake")
    _take(db, first_try, a, 5)
    _take(db, retaker, a, 0)
    _take(db, retaker, a, 5)
    rows = leaderboard(db, "game", a.id)
    assert [r.name for r in rows] == ["Zed First", "Amy Retake"]
    assert rows[0].value == rows[1].value == 100


def test_gamification_pages(student_client, db, student, client_factory):
    _setup(db)
    a = make_assessment(db, question_count=3)
    _take(db, student, a, 3)
    page = student_client.get("/gamification")
    assert "Perfect Score" in page.text and "Quick Quiz Bee" in page.text
    assert "Juan Dela Cruz" in student_client.get("/leaderboards").text
    fac = client_factory(role="faculty")
    post(fac, "/leaderboards/visibility", {"public": "false"}, csrf_from="/leaderboards")
    assert "hidden by your faculty" in student_client.get("/leaderboards").text
    # quick quiz bee
    r = post(student_client, "/games/quick-quiz-bee", csrf_from="/gamification")
    assert "Question 1 of 15" in r.text


def test_staff_badge_management(faculty_client, db):
    _setup(db)
    stu = make_user(db, "student", major="math")
    post(faculty_client, "/badges", {"name": "Early Bird", "description": "Studied early", "rule_type": "manual",
                                     "threshold": 0, "icon": "sunrise", "color": "warning"}, csrf_from="/badges")
    b = db.scalar(select(Badge).where(Badge.code == "early_bird"))
    assert b is not None
    r = post(faculty_client, f"/badges/{b.id}/award", {"student_id": stu.id}, csrf_from="/badges")
    assert "Awarded" in r.text
    assert db.scalar(select(UserBadge).where(UserBadge.user_id == stu.id, UserBadge.badge_id == b.id))
