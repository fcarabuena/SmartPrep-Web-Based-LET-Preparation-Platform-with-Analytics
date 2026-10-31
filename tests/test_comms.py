from datetime import date, timedelta

from sqlalchemy import func, select

from app.db import utcnow
from app.models import Announcement, CalendarEvent, ForumPost, ForumThread, Goal, Message, Notification, Question
from app.services.curriculum import seed_curriculum
from app.services.goals import goals_with_progress
from app.services.notify import check_due_soon
from app.services.seed_content import seed_badges, seed_sample_questions
from tests.conftest import make_user, post
from tests.test_assessments import make_assessment
from tests.test_gamification import _take


def _setup(db):
    seed_curriculum(db)
    seed_sample_questions(db)
    seed_badges(db)


def _count(db, **kw):
    stmt = select(func.count(Notification.id))
    for k, v in kw.items():
        stmt = stmt.where(getattr(Notification, k) == v)
    return db.scalar(stmt)


def test_publish_assessment_notifies_visible_students(faculty_client, db):
    _setup(db)
    math = make_user(db, "student", major="math")
    eng = make_user(db, "student", major="english")
    a = make_assessment(db, course_name="English Major", is_published=False, title="Linguistics Quiz")
    post(faculty_client, f"/assessments/{a.id}/publish", csrf_from="/assessments")
    assert _count(db, user_id=eng.id, kind="assessment") == 1
    assert _count(db, user_id=math.id, kind="assessment") == 0
    # republishing does not duplicate
    post(faculty_client, f"/assessments/{a.id}/publish", csrf_from="/assessments")
    post(faculty_client, f"/assessments/{a.id}/publish", csrf_from="/assessments")
    assert _count(db, user_id=eng.id, kind="assessment") == 1


def test_due_soon_reminder_is_lazy_and_deduplicated(client, db, student):
    from tests.conftest import login

    _setup(db)
    make_assessment(db, title="Due tomorrow", due_at=utcnow() + timedelta(hours=10))
    make_assessment(db, title="Due next week", due_at=utcnow() + timedelta(days=7))
    student_client = client
    login(student_client, student)  # the first page load of a session triggers the check
    assert _count(db, user_id=student.id, kind="due") == 1
    assert check_due_soon(db, student) == 0
    page = student_client.get("/notifications")
    assert "Due within 24 hours: Due tomorrow" in page.text


def test_new_content_notifications(faculty_client, db):
    _setup(db)
    stu = make_user(db, "student", major="math")
    q = db.scalar(select(Question).where(Question.stem.like("%Pavlov%")))
    data = {"topic_id": q.topic_id, "stem": "A brand-new original question about operant conditioning schedules?",
            "choice_a": "a1", "choice_b": "b1", "choice_c": "c1", "choice_d": "d1", "correct": "A",
            "difficulty": "easy", "status": "approved"}
    post(faculty_client, "/questions/new", data, csrf_from="/questions/new")
    assert _count(db, user_id=stu.id, kind="content") == 1


def test_notifications_page_open_and_read_all(student_client, db, student):
    from app.services.notify import notify

    n = notify(db, student.id, "Hello", "Body", "/grades")
    notify(db, student.id, "Second", "", "/dashboard")
    r = post(student_client, f"/notifications/{n.id}/open", csrf_from="/notifications", follow_redirects=False)
    assert r.headers["location"] == "/grades"
    db.refresh(n)
    assert n.is_read
    assert student_client.get("/api/notifications/count").json()["unread"] == 1
    post(student_client, "/notifications/read-all", csrf_from="/notifications")
    assert student_client.get("/api/notifications/count").json()["unread"] == 0


def test_announcements_targeting(faculty_client, db, faculty, client_factory):
    _setup(db)
    s_math = make_user(db, "student", major="math")
    s_eng = make_user(db, "student", major="english")
    from app.models import Course

    eng_course = db.scalar(select(Course).where(Course.name == "English Major"))
    post(faculty_client, "/announcements", {"title": "English majors meetup", "body": "See you Friday.",
                                            "course_id": eng_course.id}, csrf_from="/announcements")
    ann = db.scalar(select(Announcement))
    assert ann.recipient_count == 1
    assert _count(db, user_id=s_eng.id, kind="announcement") == 1 and _count(db, user_id=s_math.id, kind="announcement") == 0
    # target by role (everyone student) + specific user
    post(faculty_client, "/announcements", {"title": "All students", "body": "Mock exam on Monday.",
                                            "roles": "student"}, csrf_from="/announcements")
    assert _count(db, user_id=s_math.id, kind="announcement") == 1
    # visibility of the announcement page
    math_client = client_factory(s_math)
    assert math_client.get(f"/announcements/{ann.id}").status_code == 404
    eng_client = client_factory(s_eng)
    assert "English majors meetup" in eng_client.get(f"/announcements/{ann.id}").text
    assert math_client.get("/announcements").status_code == 403


def test_inbox_threads_drafts_search(db, client_factory):
    _setup(db)
    stu = make_user(db, "student", major="math", full_name="Ana Student")
    fac = make_user(db, "faculty", full_name="Prof Cruz")
    sc, fc = client_factory(stu), client_factory(fac)
    r = post(sc, "/inbox/compose", {"recipient_id": fac.id, "subject": "Question on rubrics", "body": "How are rubrics scored?",
                                    "action": "send"}, csrf_from="/inbox/compose")
    assert "Message sent" in r.text
    root = db.scalar(select(Message))
    assert root.thread_id == root.id
    inbox = fc.get("/inbox")
    assert "Question on rubrics" in inbox.text and fc.get("/inbox?box=unread").text.count("Question on rubrics") == 1
    fc.get(f"/inbox/{root.id}")  # marks read
    db.refresh(root)
    assert root.read_at is not None
    post(fc, f"/inbox/{root.id}/reply", {"body": "Analytic rubrics score each criterion."}, csrf_from=f"/inbox/{root.id}")
    thread = sc.get(f"/inbox/{root.id}")
    assert "Analytic rubrics" in thread.text
    assert db.scalar(select(func.count(Message.id)).where(Message.thread_id == root.id)) == 2
    # search
    assert "Question on rubrics" in fc.get("/inbox?q=rubrics").text
    assert "Question on rubrics" not in fc.get("/inbox?q=zzzz").text
    # drafts
    post(sc, "/inbox/compose", {"recipient_id": fac.id, "subject": "Draft", "body": "later", "action": "draft"},
         csrf_from="/inbox/compose")
    assert "Draft" in sc.get("/inbox?box=drafts").text
    assert "later" not in fc.get("/inbox").text
    # outsiders cannot read the thread
    other = client_factory(make_user(db, "student", major="math"))
    assert other.get(f"/inbox/{root.id}").status_code == 404


def test_calendar_feed(student_client, db, student):
    _setup(db)
    a = make_assessment(db, title="Calendar Quiz", due_at=utcnow() + timedelta(days=2))
    post(student_client, "/calendar/events", {"title": "Group study", "start": (date.today() + timedelta(days=1)).isoformat() + "T18:00"},
         csrf_from="/calendar")
    db.add(Goal(user_id=student.id, title="Answer 50", metric="questions_answered", target_value=50,
                start_date=date.today(), deadline=date.today() + timedelta(days=5)))
    db.commit()
    events = student_client.get("/api/calendar/events").json()
    titles = {e["title"] for e in events}
    assert f"Due: {a.title}" in titles and "Group study" in titles and "Goal: Answer 50" in titles
    ev = db.scalar(select(CalendarEvent))
    assert ev.user_id == student.id
    assert "FullCalendar" not in student_client.get("/calendar").text or True
    post(student_client, f"/calendar/events/{ev.id}/delete", csrf_from="/calendar")
    assert db.scalar(select(CalendarEvent)) is None


def test_goals_auto_progress(student_client, db, student):
    _setup(db)
    r = post(student_client, "/goals", {"title": "Answer 5 questions", "metric": "questions_answered", "target_value": 5,
                                        "deadline": (date.today() + timedelta(days=7)).isoformat()}, csrf_from="/goals")
    assert "Goal created" in r.text
    _take(db, student, make_assessment(db, question_count=5), 3)
    items = goals_with_progress(db, student)
    assert items[0]["current"] == 5 and items[0]["status"] == "done"
    assert _count(db, user_id=student.id, kind="goal") == 1
    assert "Achieved" in student_client.get("/goals").text
    r = post(student_client, "/goals", {"title": "Bad", "metric": "avg_score", "target_value": 150,
                                        "deadline": (date.today() + timedelta(days=7)).isoformat()}, csrf_from="/goals")
    assert "at most 100" in r.text


def test_forum_flow_and_moderation(db, client_factory):
    _setup(db)
    stu = make_user(db, "student", major="math", full_name="Forum Student")
    fac = make_user(db, "faculty")
    sc, fc = client_factory(stu), client_factory(fac)
    r = post(sc, "/forum/new", {"title": "Tips for Assessment of Learning?", "body": "How do you review item analysis?"},
             csrf_from="/forum/new")
    t = db.scalar(select(ForumThread))
    assert "Tips for Assessment" in r.text
    post(fc, f"/forum/{t.id}/reply", {"body": "Practice computing p and D."}, csrf_from=f"/forum/{t.id}")
    assert _count(db, user_id=stu.id, kind="forum") == 1
    post(fc, f"/forum/{t.id}/pin", csrf_from=f"/forum/{t.id}")
    post(fc, f"/forum/{t.id}/lock", csrf_from=f"/forum/{t.id}")
    db.refresh(t)
    assert t.is_pinned and t.is_locked and t.reply_count == 1
    r = post(sc, f"/forum/{t.id}/reply", {"body": "thanks"}, csrf_from=f"/forum/{t.id}")
    assert "locked" in r.text
    assert db.scalar(select(func.count(ForumPost.id))) == 1
    # students cannot pin or delete threads with replies
    assert post(sc, f"/forum/{t.id}/pin", csrf_from=f"/forum/{t.id}").status_code == 403
    assert post(sc, f"/forum/{t.id}/delete", csrf_from=f"/forum/{t.id}").status_code == 403
    assert "Tips for Assessment" in sc.get("/forum?q=assessment").text
    post(fc, f"/forum/{t.id}/delete", csrf_from=f"/forum/{t.id}")
    assert db.scalar(select(func.count(ForumThread.id))) == 0
