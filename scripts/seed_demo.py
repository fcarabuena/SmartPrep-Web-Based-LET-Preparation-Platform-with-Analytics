"""Seed a realistic demo dataset for presentations and UAT.

Creates 1 admin, 3 faculty, 60 students, 300+ original questions, resources, assessments, 8 weeks of
gradually improving attempts (with Exam 1/2/3 mock-exam attempts), points, badges, activity logs,
messages, forum posts, goals, events and announcements.

Usage (Windows):
    .venv\\Scripts\\python scripts\\seed_demo.py                 # add demo data (idempotent for users/content)
    .venv\\Scripts\\python scripts\\seed_demo.py --wipe --yes    # DELETE ALL DATA first, then seed

Point DATABASE_URL at Neon to seed production. Staff accounts must set up 2FA on first sign-in.
"""
import argparse
import random
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

import app.models  # noqa: E402,F401
from app.db import Base, SessionLocal, utcnow  # noqa: E402
from app.models import (  # noqa: E402
    ActivityLog,
    Assessment,
    Attempt,
    AttemptAnswer,
    Badge,
    CalendarEvent,
    Category,
    Course,
    ForumPost,
    ForumThread,
    Goal,
    Message,
    PointsLedger,
    Question,
    Resource,
    ResourceView,
    Topic,
    User,
    UserBadge,
)
from app.security import hash_password  # noqa: E402
from app.services.curriculum import seed_curriculum  # noqa: E402
from app.services.notify import publish_announcement  # noqa: E402
from app.services.seed_content import seed_badges, seed_extra_questions, seed_sample_questions  # noqa: E402
from app.services.settings_store import DEFAULTS  # noqa: E402

DOMAIN = "smartprep.demo"
PASSWORDS = {"admin": "Admin12345", "faculty": "Faculty123", "student": "Student123"}
FIRST = ["Maria", "Jose", "Ana", "Juan", "Kristine", "Mark", "Angelica", "John Paul", "Princess", "Christian",
         "Jasmine", "Carlo", "Rhea", "Jerome", "Kimberly", "Ralph", "Nicole", "Bryan", "Shiela", "Ivan", "Joy",
         "Arnel", "Mylene", "Rodel", "Lovely", "Jayson", "Hazel", "Dennis", "Camille", "Noel"]
LAST = ["Dela Cruz", "Santos", "Reyes", "Garcia", "Mendoza", "Fabella", "Faderon", "Rubio", "Mortel", "Fetalino",
        "Ramos", "Villanueva", "Castillo", "Morales", "Bautista", "Aquino", "Navarro", "Salazar", "Fajardo", "Gallardo"]
MAJOR_MIX = (["elementary"] * 10 + ["math"] * 10 + ["english"] * 10 + ["filipino"] * 8 + ["science"] * 8
             + ["social_studies"] * 7 + ["tle"] * 7)
LOCAL = timedelta(hours=8)


def local_dt(day: date, rng: random.Random) -> datetime:
    """A plausible study time (6:00–22:59 PH) on a given local date, returned as naive UTC."""
    hour = rng.choices(range(6, 23), weights=[1, 2, 3, 3, 2, 2, 2, 3, 4, 4, 3, 3, 4, 6, 7, 6, 3])[0]
    return datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), rng.randint(0, 59)) - LOCAL


def wipe(db) -> None:
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()


def get_or_create_user(db, email, name, role, major=None, created_at=None, student_no=None) -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u:
        return u
    u = User(email=email, full_name=name, role=role, major=major, student_no=student_no, email_verified=True,
             password_hash=hash_password(PASSWORDS[role]), created_at=created_at or utcnow())
    db.add(u)
    db.flush()
    return u


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wipe", action="store_true", help="delete ALL existing data before seeding")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation with --wipe")
    ap.add_argument("--students", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    t0 = time.time()
    db = SessionLocal()

    if args.wipe:
        if not args.yes and input("This deletes ALL data in the database. Type 'yes' to continue: ").strip() != "yes":
            print("Aborted.")
            return
        wipe(db)
        print("Database wiped.")

    seed_curriculum(db)
    seed_badges(db)
    seed_sample_questions(db)

    now = utcnow()
    start = now - timedelta(weeks=8)
    admin = get_or_create_user(db, f"admin@{DOMAIN}", "Dr. Elena Fadri", "admin", created_at=start - timedelta(days=14))
    faculty = [get_or_create_user(db, f"faculty{i}@{DOMAIN}", name, "faculty", created_at=start - timedelta(days=10))
               for i, name in enumerate(["Prof. Ramon Fabito", "Prof. Liza Marquez", "Prof. Victor Ferrer"], 1)]
    db.commit()
    if db.scalar(select(Attempt.id).limit(1)):
        print("Attempts already exist — skipping activity simulation (use --wipe to rebuild).")
        print(f"Questions: {db.query(Question).count()}  Students: {db.query(User).filter(User.role == 'student').count()}")
        return

    print("Questions added:", seed_extra_questions(db, faculty[0].id))

    students = []
    for i in range(args.students):
        major = MAJOR_MIX[i % len(MAJOR_MIX)]
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        created = start - timedelta(days=rng.randint(0, 7))
        students.append(get_or_create_user(db, f"student{i + 1:02d}@{DOMAIN}", name, "student", major, created,
                                           f"2026-{1000 + i}"))
    db.commit()

    # ---------------- content: leveled resources per topic (search links to free platforms)
    topics = db.scalars(select(Topic).join(Course)).all()
    for t in topics:
        q = t.name.replace(" ", "+")
        for title, kind, url, level in (
            (f"Khan Academy search: {t.name}", "video", f"https://www.khanacademy.org/search?page_search_query={q}",
             "foundational"),
            (f"LET review videos: {t.name}", "video", f"https://www.youtube.com/results?search_query=LET+review+{q}",
             "standard"),
            (f"OpenStax search: {t.name}", "article", f"https://openstax.org/search?q={q}", "advanced"),
        ):
            if not db.scalar(select(Resource.id).where(Resource.url == url)):
                db.add(Resource(title=title, kind=kind, url=url, topic_id=t.id, level=level, approved=True,
                                created_by_id=rng.choice(faculty).id, description=f"Curated search for {t.name}."))
    db.commit()

    # ---------------- assessments
    cats = {c.code: c for c in db.scalars(select(Category))}
    courses = db.scalars(select(Course).order_by(Course.category_id, Course.sort_order)).all()
    approved = defaultdict(list)  # course_id -> [(qid, topic_id, difficulty, correct)]
    for q in db.scalars(select(Question).where(Question.status == "approved")):
        approved[q.topic_id].append((q.id, q.difficulty, q.correct))
    topic_course = {t.id: t.course_id for t in topics}
    course_pool = defaultdict(list)
    for tid, items in approved.items():
        for qid, diff, key in items:
            course_pool[topic_course[tid]].append((qid, tid, diff, key))

    def mk(title, kind, cat, course=None, n=10, minutes=None, due_week=None, max_attempts=None, ppc=1, bonus=10):
        a = Assessment(title=title, kind=kind, category_id=cat.id if cat else None, course_id=course.id if course else None,
                       question_count=n, time_limit_minutes=minutes, max_attempts=max_attempts, is_published=True,
                       randomize_questions=True, randomize_choices=kind != "practice", points_per_correct=ppc,
                       pass_bonus=bonus, created_by_id=rng.choice(faculty).id, created_at=start - timedelta(days=3),
                       due_at=(start + timedelta(weeks=due_week, days=5)) if due_week is not None else None,
                       instructions="Choose the best answer. Your answers are saved automatically.")
        db.add(a)
        return a

    assessments = []
    for co in courses:
        if course_pool.get(co.id):
            wk = rng.randint(1, 9)  # some due dates are still upcoming
            assessments.append(mk(f"{co.name} Practice Quiz", "practice", co.category, co, n=10, due_week=wk))
    mocks = {
        "prof_ed": mk("Professional Education Mock Exam", "mock_exam", cats["prof_ed"], n=30, minutes=45, max_attempts=3,
                      due_week=9, bonus=20),
        "gen_ed": mk("General Education Mock Exam", "mock_exam", cats["gen_ed"], n=30, minutes=45, max_attempts=3,
                     due_week=9, bonus=20),
    }
    major_mocks = {}
    for co in courses:
        if co.major and course_pool.get(co.id):
            major_mocks[co.major] = mk(f"Major Core Mock Exam – {co.name}", "mock_exam", co.category, co, n=20,
                                       minutes=30, max_attempts=3, due_week=9, bonus=20)
    game = mk("Speed Round: Teaching Methods", "game", cats["prof_ed"],
              next(c for c in courses if c.name == "Teaching Methods"), n=10, minutes=3, ppc=2)
    bee = mk("Friday Quiz Bee", "quiz_bee", None, None, n=15, minutes=5, ppc=2)
    db.commit()

    def pool_for(a: Assessment, major: str | None):
        if a.course_id:
            return course_pool[a.course_id]
        items = []
        for co in courses:
            if (a.category_id and co.category_id != a.category_id) or (co.major and co.major != major):
                continue
            items += course_pool[co.id]
        return items

    thresholds = DEFAULTS["pass_thresholds"]
    pts = DEFAULTS["points"]
    badges = {b.code: b for b in db.scalars(select(Badge))}
    diff_adj = {"easy": 0.12, "medium": 0.0, "hard": -0.13}

    # ---------------- simulate 8 weeks per student
    total_attempts = 0
    risk_students = set(rng.sample(range(len(students)), min(7, len(students) // 5 or 1)))
    for si, stu in enumerate(students):
        ability = rng.uniform(0.42, 0.78)
        growth = rng.uniform(0.006, 0.03)
        bias = defaultdict(lambda: rng.uniform(-0.12, 0.10))
        stops_after = rng.randint(3, 5) if si in risk_students else 9
        practice = [a for a in assessments if not a.course or not a.course.major or a.course.major == stu.major]
        my_mocks = [mocks["prof_ed"], mocks["gen_ed"]] + ([major_mocks[stu.major]] if stu.major in major_mocks else [])
        plan = []  # (week, assessment)
        for w in range(8):
            if w >= stops_after:
                break
            for _ in range(rng.randint(1, 4)):
                plan.append((w, rng.choice(practice)))
            if rng.random() < 0.35:
                plan.append((w, rng.choice([game, bee])))
        for w in (1, 4, 7):  # Exam 1 / 2 / 3
            if w < stops_after:
                for m in my_mocks:
                    plan.append((w, m))
        plan.sort(key=lambda x: x[0])

        attempt_no = defaultdict(int)
        last_score: dict[int, float] = {}
        earned_badges: dict[str, datetime] = {}
        active_days: set[date] = set()
        ledger, logs, views = [], [], []
        last_seen = stu.created_at
        for w, a in plan:
            pool = pool_for(a, stu.major)
            if not pool:
                continue
            day = (start + timedelta(weeks=w, days=rng.randint(0, 6)) + LOCAL).date()
            if day > (now + LOCAL).date():
                day = (now + LOCAL).date()
            started = local_dt(day, rng)
            if started > now:
                started = now - timedelta(minutes=rng.randint(30, 600))
            picks = rng.sample(pool, min(a.question_count, len(pool)))
            attempt_no[a.id] += 1
            no = attempt_no[a.id]
            answers, correct, secs = [], 0, 0
            for pos, (qid, tid, diff, key) in enumerate(picks):
                p = min(0.97, max(0.05, ability + growth * w + diff_adj.get(diff, 0) + bias[tid]
                                  + (0.04 * (no - 1))))
                ok = rng.random() < p
                chosen = key if ok else rng.choice([x for x in "ABCD" if x != key])
                t = rng.randint(15, 95)
                secs += t
                correct += ok
                answers.append(AttemptAnswer(question_id=qid, position=pos, choice_order="ABCD", chosen=chosen,
                                             is_correct=ok, time_spent_seconds=t,
                                             answered_at=started + timedelta(seconds=secs)))
            if a.time_limit_minutes:
                secs = min(secs, a.time_limit_minutes * 60)
            score = round(100.0 * correct / len(answers), 2)
            threshold = float(thresholds[min(no, len(thresholds)) - 1])
            submitted = started + timedelta(seconds=secs)
            at = Attempt(user_id=stu.id, assessment_id=a.id, attempt_no=no, kind=a.kind, status="submitted",
                         started_at=started, submitted_at=submitted, last_saved_at=submitted,
                         deadline_at=started + timedelta(minutes=a.time_limit_minutes) if a.time_limit_minutes else None,
                         total_questions=len(answers), correct_count=correct, score_pct=score, threshold=threshold,
                         passed=score >= threshold, time_spent_seconds=secs, answers=answers)
            db.add(at)
            total_attempts += 1
            # points (same rules as the live engine)
            earned = [(correct * a.points_per_correct, "correct_answers"), (pts["complete_quiz"], "complete_quiz")]
            if at.passed:
                earned.append((pts["pass"] + a.pass_bonus, "pass"))
            if score == 100:
                earned.append((pts["perfect_score"], "perfect_score"))
            prev = last_score.get(a.id)
            if prev is not None and score > prev:
                earned.append((pts["improvement"], "improvement"))
            ledger.append((at, earned, submitted))
            at.points_awarded = sum(p for p, _ in earned if p > 0)
            # badges
            for code, cond in (("first_steps", True), ("accuracy_ace", score >= 75), ("perfect_score", score == 100),
                               ("master_of_categories", score >= 90),
                               ("persistence_pro", prev is not None and score - prev >= 20)):
                if cond and code in badges and code not in earned_badges:
                    earned_badges[code] = submitted
            last_score[a.id] = score
            active_days.add(day)
            # activity: login + page views around the attempt
            logs.append(ActivityLog(user_id=stu.id, event="login", path="/login", created_at=started - timedelta(minutes=3)))
            for k, path in enumerate(["/dashboard", "/quizzes", f"/assessments/{a.id}/start", "/progress"]):
                logs.append(ActivityLog(user_id=stu.id, event="page_view", path=path, status_code=200,
                                        duration_ms=rng.randint(40, 400), created_at=started - timedelta(minutes=2 - k * 0.3)))
            logs.append(ActivityLog(user_id=stu.id, event="page_view", path=f"/attempts/{a.id}/result", status_code=200,
                                    duration_ms=rng.randint(40, 300), created_at=submitted + timedelta(seconds=20)))
            last_seen = max(last_seen, submitted + timedelta(minutes=rng.randint(2, 15)))
        # streak badge from consecutive active days
        days = sorted(active_days)
        run = best = 1 if days else 0
        for d1, d2 in zip(days, days[1:]):
            run = run + 1 if (d2 - d1).days == 1 else 1
            best = max(best, run)
        if best >= 7 and "streak_7" in badges:
            earned_badges["streak_7"] = local_dt(days[-1], rng)
        db.flush()
        for at, earned, when in ledger:
            for p, reason in earned:
                if p > 0:
                    db.add(PointsLedger(user_id=stu.id, points=p, reason=reason, ref_type="attempt", ref_id=at.id,
                                        created_at=when))
        for code, when in earned_badges.items():
            db.add(UserBadge(user_id=stu.id, badge_id=badges[code].id, awarded_at=when,
                             context="demo"))
        # resource views on weak/random topics
        topic_ids = list(approved)
        for _ in range(rng.randint(3, 14)):
            res = db.scalar(select(Resource).where(Resource.topic_id == rng.choice(topic_ids)).limit(1))
            if res:
                when = min(now, start + timedelta(days=rng.randint(0, 55), hours=rng.randint(0, 23)))
                views.append(ResourceView(resource_id=res.id, user_id=stu.id, recommended=rng.random() < 0.6,
                                          created_at=when))
                res.view_count = (res.view_count or 0) + 1
                if rng.random() < 0.5:
                    db.add(PointsLedger(user_id=stu.id, points=pts["resource_view"], reason="resource_view",
                                        ref_type="resource", ref_id=res.id, created_at=when))
        db.add_all(logs + views)
        stu.last_seen_at = stu.last_login_at = min(last_seen, now)
        db.commit()
        print(f"  student {si + 1:2d}/{len(students)} · {len(plan)} attempts", end="\r")
    print()

    # ---------------- communication & planning
    by_major = defaultdict(list)
    for s in students:
        by_major[s.major].append(s)
    feedback_lines = [
        "Great improvement on your Professional Education mock exam! Keep reviewing Assessment of Learning.",
        "I noticed you have not logged in for a while. Try 20 minutes of adaptive practice a day.",
        "Your General Education scores are rising. Focus next on Statistics and Probability.",
        "Please review the rationalizations for the items you missed in Theories of Learning.",
    ]
    for s in rng.sample(students, min(12, len(students))):
        f = rng.choice(faculty)
        when = now - timedelta(days=rng.randint(1, 30))
        m = Message(sender_id=f.id, recipient_id=s.id, subject="Feedback on your LET review", is_feedback=True,
                    body=rng.choice(feedback_lines), created_at=when, read_at=when + timedelta(hours=5) if rng.random() < .6 else None)
        db.add(m)
        db.flush()
        m.thread_id = m.id
        if rng.random() < 0.5:
            db.add(Message(sender_id=s.id, recipient_id=f.id, subject="Re: Feedback on your LET review",
                           body="Thank you po, Sir/Ma'am! I will follow your advice.", thread_id=m.id,
                           created_at=when + timedelta(hours=8)))
    questions_to_faculty = ["Is the mock exam open-notes?", "Can I retake the Gen Ed mock exam this week?",
                            "What does discrimination index mean in item analysis?", "May I ask for more Filipino reviewers?"]
    for s in rng.sample(students, min(8, len(students))):
        f = rng.choice(faculty)
        when = now - timedelta(days=rng.randint(1, 20))
        m = Message(sender_id=s.id, recipient_id=f.id, subject="Question about the review", body=rng.choice(questions_to_faculty),
                    created_at=when)
        db.add(m)
        db.flush()
        m.thread_id = m.id
    threads = [
        ("How do you study for Assessment of Learning?", "Any tips on remembering test types and item analysis formulas?"),
        ("Free Gen Ed resources", "Sharing links that helped me in Math and Science. Add yours!"),
        ("Pomodoro study group tonight", "Anyone want to join a 9 PM online review session?"),
        ("Theories of Learning mnemonics", "Pavlov = bell, Skinner = box, Bandura = Bobo doll. What else?"),
        ("Filipino Major: Panitikan reviewers", "Ano ang magandang paraan para matandaan ang mga may-akda?"),
        ("Mock exam timing strategy", "Do you answer the easy items first?"),
    ]
    replies = ["Thanks for sharing!", "Practice the item analysis computations — they come up often.",
               "I do 2 adaptive reviews every night, it helps a lot.", "Count me in!", "Salamat po!",
               "Skip hard items first, then come back. The timer is strict."]
    for i, (title, body) in enumerate(threads):
        author = rng.choice(students)
        when = now - timedelta(days=rng.randint(5, 40))
        t = ForumThread(title=title, body=body, author_id=author.id, category_id=rng.choice(list(cats.values())).id,
                        created_at=when, last_activity_at=when, is_pinned=i == 0)
        db.add(t)
        db.flush()
        for k in range(rng.randint(2, 5)):
            who = rng.choice(students + faculty)
            pt = when + timedelta(hours=6 * (k + 1))
            db.add(ForumPost(thread_id=t.id, author_id=who.id, body=rng.choice(replies), created_at=pt))
            t.reply_count += 1
            t.last_activity_at = pt
    today = (now + LOCAL).date()
    metrics = [("Answer 150 questions", "questions_answered", 150), ("Pass 5 quizzes", "quizzes_passed", 5),
               ("Reach 80% average", "avg_score", 80), ("Reach Ready status", "readiness", 75)]
    for s in rng.sample(students, min(20, len(students))):
        title, metric, target = rng.choice(metrics)
        db.add(Goal(user_id=s.id, title=title, metric=metric, target_value=target,
                    start_date=today - timedelta(days=rng.randint(7, 40)), deadline=today + timedelta(days=rng.randint(5, 40))))
    for title, days in (("LET Mock Board (face-to-face)", 12), ("Faculty consultation hours", 3), ("Review orientation", -20)):
        d = now + timedelta(days=days)
        db.add(CalendarEvent(user_id=None, title=title, start_at=d.replace(hour=1, minute=0), end_at=d.replace(hour=5, minute=0),
                             created_by_id=admin.id, description="Romblon State University – Cajidiocan Campus"))
    db.commit()
    publish_announcement(db, admin, "Welcome to Smart Prep!",
                         "Use the Study Plan every day and take the mock exams before the deadline. Good luck, future LPTs!",
                         ["student"], None, [], False)
    publish_announcement(db, faculty[0], "Professional Education Mock Exam is open",
                         "Three attempts are allowed. Passing: 75% / 80% / 85%.", ["student"], None, [], False)
    db.close()

    print(f"Done in {time.time() - t0:.0f}s: {len(students)} students, {total_attempts} attempts.")
    print("\nDemo accounts (change these passwords for real use):")
    print(f"  admin    admin@{DOMAIN} / {PASSWORDS['admin']}   (set up 2FA at first sign-in)")
    print(f"  faculty  faculty1@{DOMAIN} … faculty3@{DOMAIN} / {PASSWORDS['faculty']}   (2FA at first sign-in)")
    print(f"  students student01@{DOMAIN} … student{len(students):02d}@{DOMAIN} / {PASSWORDS['student']}")


if __name__ == "__main__":
    main()
