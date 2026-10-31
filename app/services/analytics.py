"""Analytics: student progress & readiness, class analytics, at-risk detection, item analysis, admin metrics.

Heavy aggregation happens in grouped SQL queries; small result sets are reshaped in Python.
Expensive views are cached for 60 seconds (single-process in-memory cache).
"""
import time
from collections import defaultdict
from datetime import date as _date
from datetime import timedelta

from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    ActivityLog,
    Assessment,
    Attempt,
    AttemptAnswer,
    Category,
    Course,
    ErrorLog,
    Question,
    Resource,
    ResourceView,
    Topic,
    User,
    UserBadge,
)
from app.models.assessment import KIND_MOCK, KIND_PRACTICE
from app.services.cache import cached
from app.services.mastery import category_mastery_by_user, category_stats, pct
from app.services.settings_store import get_setting
from app.services.sqlutil import database_size_bytes, local_day, local_dow, local_hour
from app.templating import LOCAL_OFFSET

CORRECT = func.sum(case((AttemptAnswer.is_correct.is_(True), 1), else_=0))
CACHE_TTL = 60


def zone(p: float | None) -> str:
    """Hot-zone class: green >= 85, yellow 75-84, red < 75."""
    if p is None:
        return "none"
    return "green" if p >= 85 else ("yellow" if p >= 75 else "red")


def _week_start(dt) -> str:
    local = (dt + LOCAL_OFFSET).date()
    return (local - timedelta(days=local.weekday())).isoformat()


def _last_weeks(n: int = 8) -> list[str]:
    today = (utcnow() + LOCAL_OFFSET).date()
    monday = today - timedelta(days=today.weekday())
    return [(monday - timedelta(weeks=i)).isoformat() for i in range(n - 1, -1, -1)]


# =============================================================== readiness

def readiness_from_stats(db: Session, track: str, stats_by_code: dict[str, tuple[int, int]]) -> dict:
    weights = get_setting(db, "readiness_weights").get(track) or {}
    bands = get_setting(db, "readiness_bands")
    names = {"gen_ed": "General Education", "prof_ed": "Professional Education", "major": "Specialization"}
    parts, score = [], 0.0
    for code, w in weights.items():
        if not w:
            continue
        n, c = stats_by_code.get(code, (0, 0))
        m = 100.0 * c / n if n else 0.0
        score += m * w / 100.0
        parts.append({"code": code, "name": names.get(code, code), "weight": w, "mastery": round(m, 1), "answered": n})
    score = round(score, 1)
    band = "Ready" if score >= bands["ready"] else ("Developing" if score >= bands["developing"] else "Not ready")
    return {"score": score, "band": band, "parts": parts, "bands": bands,
            "color": {"Ready": "success", "Developing": "warning", "Not ready": "danger"}[band]}


def _cat_codes(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Category.id, Category.code)).all())


def readiness(db: Session, user: User) -> dict:
    codes = _cat_codes(db)
    stats = {codes.get(cid, ""): v for cid, v in category_stats(db, user.id).items()}
    return readiness_from_stats(db, user.track, stats)


# =============================================================== student progress

def _answer_rows(db: Session, user_id: int):
    """One grouped query: per (attempt, topic) answered/correct/time with course & category."""
    return db.execute(
        select(Attempt.id, Attempt.submitted_at, Attempt.attempt_no, Attempt.is_adaptive, Topic.course_id,
               Course.category_id, Question.topic_id, func.count(AttemptAnswer.id), CORRECT,
               func.coalesce(func.sum(AttemptAnswer.time_spent_seconds), 0))
        .select_from(AttemptAnswer)
        .join(Attempt, AttemptAnswer.attempt_id == Attempt.id)
        .join(Question, AttemptAnswer.question_id == Question.id)
        .join(Topic, Question.topic_id == Topic.id)
        .join(Course, Topic.course_id == Course.id)
        .where(Attempt.user_id == user_id, Attempt.status == "submitted")
        .group_by(Attempt.id, Attempt.submitted_at, Attempt.attempt_no, Attempt.is_adaptive, Topic.course_id,
                  Course.category_id, Question.topic_id)
    ).all()


def student_progress(db: Session, user: User, category_id: int = 0, course_id: int = 0) -> dict:
    return cached(("progress", user.id, category_id, course_id), lambda: _student_progress(db, user, category_id, course_id),
                  CACHE_TTL)


def _student_progress(db: Session, user: User, category_id: int, course_id: int) -> dict:
    cats = db.scalars(select(Category).order_by(Category.sort_order)).all()
    courses = [c for c in db.scalars(select(Course).order_by(Course.category_id, Course.sort_order))
               if not c.major or c.major == user.major]
    topics = db.scalars(select(Topic).where(Topic.course_id.in_([c.id for c in courses] or [0]))
                        .order_by(Topic.course_id, Topic.sort_order)).all()
    rows = _answer_rows(db, user.id)

    by_cat = defaultdict(lambda: [0, 0])
    by_course = defaultdict(lambda: [0, 0, 0])  # answered, correct, seconds
    by_topic = defaultdict(lambda: [0, 0])
    per_attempt_course = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # attempt -> course -> [n, c]
    per_attempt_cat = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    attempt_meta = {}
    for aid, sub, no, adaptive, co, ca, tid, n, c, secs in rows:
        c = int(c or 0)
        by_cat[ca][0] += n
        by_cat[ca][1] += c
        by_course[co][0] += n
        by_course[co][1] += c
        by_course[co][2] += int(secs or 0)
        by_topic[tid][0] += n
        by_topic[tid][1] += c
        per_attempt_course[aid][co][0] += n
        per_attempt_course[aid][co][1] += c
        per_attempt_cat[aid][ca][0] += n
        per_attempt_cat[aid][ca][1] += c
        attempt_meta[aid] = (sub, no, adaptive)
    ordered = sorted(attempt_meta, key=lambda a: (attempt_meta[a][0], a))

    def exam_scores(per_attempt) -> dict:
        """{key: {1: avg%, 2: avg%, 3: avg%}} from graded (non-adaptive) attempts by attempt number."""
        acc = defaultdict(lambda: defaultdict(list))
        for aid in ordered:
            _, no, adaptive = attempt_meta[aid]
            if adaptive or no > 3:
                continue
            for key, (n, c) in per_attempt[aid].items():
                if n:
                    acc[key][no].append(100.0 * c / n)
        return {k: {no: round(sum(v) / len(v), 1) for no, v in d.items()} for k, d in acc.items()}

    def improvement(per_attempt, key) -> float | None:
        series = [100.0 * per_attempt[a][key][1] / per_attempt[a][key][0]
                  for a in ordered if per_attempt[a].get(key) and per_attempt[a][key][0]]
        return round(series[-1] - series[0], 1) if len(series) >= 2 else None

    cat_exams = exam_scores(per_attempt_cat)
    course_exams = exam_scores(per_attempt_course)

    category_rows = []
    for cat in cats:
        n, c = by_cat.get(cat.id, (0, 0))
        ex = cat_exams.get(cat.id, {})
        latest = ex.get(3, ex.get(2))
        category_rows.append({"id": cat.id, "name": cat.name, "code": cat.code, "answered": n, "pct": pct(n, c),
                              "exam1": ex.get(1), "exam2": ex.get(2), "exam3": ex.get(3),
                              "improvement": round(latest - ex[1], 1) if latest is not None and 1 in ex else None})

    visible_courses = [c for c in courses if (not category_id or c.category_id == category_id)
                       and (not course_id or c.id == course_id)]
    course_rows = []
    for co in visible_courses:
        n, c, secs = by_course.get(co.id, (0, 0, 0))
        course_rows.append({"id": co.id, "name": co.name, "category_id": co.category_id, "answered": n,
                            "correct_pct": pct(n, c), "incorrect_pct": round(100 - pct(n, c), 1) if n else None,
                            "improvement": improvement(per_attempt_course, co.id), "minutes": round(secs / 60, 1),
                            "exams": course_exams.get(co.id, {})})

    # Study Hot Zones: rows = courses, columns = topics (mastery) or Exam 1/2/3
    topics_by_course = defaultdict(list)
    for t in topics:
        n, c = by_topic.get(t.id, (0, 0))
        p = pct(n, c)
        topics_by_course[t.course_id].append({"id": t.id, "name": t.name, "pct": p, "zone": zone(p), "answered": n})
    heat_topics = [{"course": co.name, "cells": topics_by_course.get(co.id, [])} for co in visible_courses]
    heat_exams = [{"course": r["name"], "cells": [{"name": f"Exam {i}", "pct": r["exams"].get(i), "zone": zone(r["exams"].get(i))}
                                                  for i in (1, 2, 3)]} for r in course_rows]

    # attempted vs correct per category (or per course when filtered)
    if category_id or course_id:
        avc = [(r["name"], by_course.get(r["id"], (0, 0, 0))[0], by_course.get(r["id"], (0, 0, 0))[1]) for r in course_rows]
    else:
        avc = [(r["name"], r["answered"], by_cat.get(r["id"], (0, 0))[1]) for r in category_rows]

    # weekly trend (avg score of submitted attempts per week, last 8 weeks)
    weeks = _last_weeks(8)
    week_scores = defaultdict(list)
    for sub, score in db.execute(select(Attempt.submitted_at, Attempt.score_pct).where(
            Attempt.user_id == user.id, Attempt.status == "submitted",
            Attempt.submitted_at >= utcnow() - timedelta(weeks=9))).all():
        week_scores[_week_start(sub)].append(score or 0)
    trend = [{"week": w, "avg": round(sum(week_scores[w]) / len(week_scores[w]), 1) if week_scores.get(w) else None,
              "attempts": len(week_scores.get(w, []))} for w in weeks]

    # strengths / weaknesses (topics with at least 3 answers)
    names = {t.id: t.name for t in topics}
    scored = [(names.get(tid, "?"), 100.0 * c / n, n) for tid, (n, c) in by_topic.items() if n >= 3 and tid in names]
    scored.sort(key=lambda x: x[1])
    weaknesses = [{"name": s[0], "pct": round(s[1], 1), "answered": s[2]} for s in scored[:3] if s[1] < 85]
    strengths = [{"name": s[0], "pct": round(s[1], 1), "answered": s[2]} for s in reversed(scored[-3:]) if s[1] >= 75]

    # completion donuts
    from app.services.assessments import visible_assessments

    visible = [a for a in visible_assessments(db, user) if a.is_published]
    done_ids = set(db.scalars(select(Attempt.assessment_id).where(Attempt.user_id == user.id,
                                                                  Attempt.status == "submitted",
                                                                  Attempt.is_adaptive.is_(False))))
    quizzes = [a for a in visible if a.kind == KIND_PRACTICE]
    exams = [a for a in visible if a.kind == KIND_MOCK]

    totals = db.execute(select(func.count(Attempt.id), func.coalesce(func.sum(Attempt.time_spent_seconds), 0),
                               func.coalesce(func.sum(Attempt.total_questions), 0))
                        .where(Attempt.user_id == user.id, Attempt.status == "submitted")).one()
    return {
        "categories": category_rows, "courses": course_rows, "heat_topics": heat_topics, "heat_exams": heat_exams,
        "attempted_vs_correct": avc, "trend": trend, "strengths": strengths, "weaknesses": weaknesses,
        "quiz_done": sum(1 for a in quizzes if a.id in done_ids), "quiz_total": len(quizzes),
        "exam_done": sum(1 for a in exams if a.id in done_ids), "exam_total": len(exams),
        "attempts": totals[0], "seconds": int(totals[1]), "questions": int(totals[2]),
        "badges": db.scalar(select(func.count(UserBadge.id)).where(UserBadge.user_id == user.id)) or 0,
    }


# =============================================================== class analytics (faculty)

def _since(days: int):
    return utcnow() - timedelta(days=days) if days else None


def class_overview(db: Session, days: int = 30) -> dict:
    return cached(("class", days), lambda: _class_overview(db, days), CACHE_TTL)


def _class_overview(db: Session, days: int) -> dict:
    since = _since(days)
    students = db.scalar(select(func.count(User.id)).where(User.role == "student", User.is_active.is_(True))) or 0
    graded = select(Attempt).where(Attempt.status == "submitted", Attempt.is_adaptive.is_(False))
    any_sub = select(Attempt.user_id).where(Attempt.status == "submitted")
    if since:
        graded = graded.where(Attempt.submitted_at >= since)
        any_sub = any_sub.where(Attempt.submitted_at >= since)
    g = graded.subquery()
    n, avg, passed = db.execute(select(func.count(g.c.id), func.avg(g.c.score_pct),
                                       func.sum(case((g.c.passed.is_(True), 1), else_=0)))).one()
    active = db.scalar(select(func.count(distinct(any_sub.subquery().c.user_id)))) or 0

    # category performance (answers in period)
    stmt = (select(Category.id, Category.name, func.count(AttemptAnswer.id), CORRECT)
            .select_from(AttemptAnswer).join(Attempt, AttemptAnswer.attempt_id == Attempt.id)
            .join(Question, AttemptAnswer.question_id == Question.id).join(Topic, Question.topic_id == Topic.id)
            .join(Course, Topic.course_id == Course.id).join(Category, Course.category_id == Category.id)
            .where(Attempt.status == "submitted").group_by(Category.id, Category.name).order_by(Category.id))
    if since:
        stmt = stmt.where(Attempt.submitted_at >= since)
    category_perf = [{"name": nm, "answered": a, "pct": pct(a, int(c or 0))} for _, nm, a, c in db.execute(stmt).all()]

    # weekly trend (8 weeks) - grouped in SQL by local day, folded into weeks
    day = local_day(db, Attempt.submitted_at)
    daily = db.execute(select(day, func.count(Attempt.id), func.avg(Attempt.score_pct))
                       .where(Attempt.status == "submitted", Attempt.submitted_at >= utcnow() - timedelta(weeks=9))
                       .group_by(day)).all()
    wk = defaultdict(lambda: [0, 0.0])
    for d, cnt, a in daily:
        d = d if isinstance(d, _date) else _date.fromisoformat(str(d)[:10])
        key = (d - timedelta(days=d.weekday())).isoformat()
        wk[key][0] += cnt
        wk[key][1] += (a or 0) * cnt
    trend = [{"week": w, "attempts": wk[w][0], "avg": round(wk[w][1] / wk[w][0], 1) if wk[w][0] else None}
             for w in _last_weeks(8)]
    return {
        "students": students, "attempts": n or 0, "avg_score": round(avg, 1) if avg is not None else None,
        "pass_rate": round(100.0 * (passed or 0) / n, 1) if n else None,
        "participation": round(100.0 * active / students, 1) if students else None, "active": active,
        "category_perf": category_perf, "trend": trend, "most_missed": most_missed_topics(db, days),
        "pending_review": db.scalar(select(func.count(Question.id)).where(Question.status == "pending_review")) or 0,
    }


def most_missed_topics(db: Session, days: int = 30, limit: int = 10, min_answers: int = 5) -> list[dict]:
    since = _since(days)
    n_col = func.count(AttemptAnswer.id)
    stmt = (select(Topic.id, Topic.name, Course.name, n_col, CORRECT)
            .select_from(AttemptAnswer).join(Attempt, AttemptAnswer.attempt_id == Attempt.id)
            .join(Question, AttemptAnswer.question_id == Question.id).join(Topic, Question.topic_id == Topic.id)
            .join(Course, Topic.course_id == Course.id).where(Attempt.status == "submitted")
            .group_by(Topic.id, Topic.name, Course.name).having(n_col >= min_answers))
    if since:
        stmt = stmt.where(Attempt.submitted_at >= since)
    rows = [{"id": tid, "topic": t, "course": c, "answered": n, "pct": pct(n, int(k or 0)),
             "missed": n - int(k or 0)} for tid, t, c, n, k in db.execute(stmt).all()]
    rows.sort(key=lambda r: (r["pct"], -r["answered"]))
    return rows[:limit]


def at_risk_students(db: Session) -> list[dict]:
    return cached(("at_risk",), lambda: _at_risk(db), CACHE_TTL)


def _at_risk(db: Session) -> list[dict]:
    inactive_days = int(get_setting(db, "at_risk_inactive_days"))
    min_ready = float(get_setting(db, "at_risk_readiness"))
    students = db.scalars(select(User).where(User.role == "student", User.is_active.is_(True))).all()
    if not students:
        return []
    codes = _cat_codes(db)
    mastery = category_mastery_by_user(db, [s.id for s in students])
    last_attempt = dict(db.execute(select(Attempt.user_id, func.max(Attempt.submitted_at))
                                   .where(Attempt.status == "submitted").group_by(Attempt.user_id)).all())
    now = utcnow()
    out = []
    for s in students:
        stats = {codes.get(cid, ""): v for cid, v in mastery.get(s.id, {}).items()}
        r = readiness_from_stats(db, s.track, stats)
        last = max([d for d in (s.last_seen_at, last_attempt.get(s.id), s.created_at) if d])
        idle = (now - last).days
        reasons = []
        if r["score"] < min_ready:
            reasons.append(f"Readiness {r['score']:.0f}% (< {min_ready:.0f}%)")
        if idle >= inactive_days:
            reasons.append(f"Inactive {idle} days")
        if reasons:
            out.append({"user": s, "readiness": r["score"], "band": r["band"], "idle_days": idle,
                        "last_attempt": last_attempt.get(s.id), "reasons": reasons,
                        "answered": sum(n for n, _ in stats.values())})
    out.sort(key=lambda x: (x["readiness"], -x["idle_days"]))
    return out


# =============================================================== item analysis

def item_analysis(db: Session, assessment_id: int) -> dict:
    return cached(("items", assessment_id), lambda: _item_analysis(db, assessment_id), CACHE_TTL)


def _item_analysis(db: Session, assessment_id: int) -> dict:
    """Difficulty index p (proportion correct) and discrimination D (upper 27% − lower 27%) per question.

    Uses each examinee's FIRST submitted graded attempt so retakes do not inflate the groups.
    """
    firsts = db.execute(
        select(Attempt.id, Attempt.user_id, Attempt.score_pct, Attempt.attempt_no)
        .where(Attempt.assessment_id == assessment_id, Attempt.status == "submitted", Attempt.is_adaptive.is_(False))
        .order_by(Attempt.user_id, Attempt.attempt_no)
    ).all()
    seen, attempts = set(), []
    for aid, uid, score, _no in firsts:
        if uid not in seen:
            seen.add(uid)
            attempts.append((aid, score or 0))
    if not attempts:
        return {"items": [], "examinees": 0, "group_size": 0}
    attempts.sort(key=lambda x: -x[1])
    k = max(1, round(0.27 * len(attempts)))
    upper = {a for a, _ in attempts[:k]}
    lower = {a for a, _ in attempts[-k:]}
    ids = [a for a, _ in attempts]
    rows = db.execute(select(AttemptAnswer.attempt_id, AttemptAnswer.question_id, AttemptAnswer.chosen,
                             AttemptAnswer.is_correct).where(AttemptAnswer.attempt_id.in_(ids))).all()
    stats = defaultdict(lambda: {"n": 0, "c": 0, "un": 0, "uc": 0, "ln": 0, "lc": 0,
                                 "choices": {"A": 0, "B": 0, "C": 0, "D": 0, "-": 0}})
    for aid, qid, chosen, ok in rows:
        s = stats[qid]
        s["n"] += 1
        s["c"] += int(bool(ok))
        s["choices"][chosen or "-"] += 1
        if aid in upper:
            s["un"] += 1
            s["uc"] += int(bool(ok))
        if aid in lower:
            s["ln"] += 1
            s["lc"] += int(bool(ok))
    questions = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(list(stats) or [0])))}
    items = []
    for qid, s in stats.items():
        p = s["c"] / s["n"] if s["n"] else 0
        d = (s["uc"] / s["un"] if s["un"] else 0) - (s["lc"] / s["ln"] if s["ln"] else 0) if (s["un"] and s["ln"]) else None
        flags = []
        if p < 0.20:
            flags.append("Very difficult")
        elif p > 0.90:
            flags.append("Very easy")
        if d is not None and d < 0:
            flags.append("Negative discrimination – check the key")
        elif d is not None and d < 0.20:
            flags.append("Poor discrimination")
        diff_label = "Difficult" if p < 0.40 else ("Average" if p <= 0.75 else "Easy")
        disc_label = ("—" if d is None else "Very good" if d >= 0.40 else "Good" if d >= 0.30
                      else "Fair" if d >= 0.20 else "Poor")
        decision = "Retain" if not flags else ("Reject / rewrite" if (d is not None and d < 0) or p < 0.10 else "Revise")
        q = questions.get(qid)
        items.append({"question": q, "n": s["n"], "p": round(p, 2), "d": None if d is None else round(d, 2),
                      "difficulty": diff_label, "discrimination": disc_label, "flags": flags, "decision": decision,
                      "choices": s["choices"], "key": q.correct if q else "?"})
    items.sort(key=lambda x: (x["decision"] == "Retain", x["p"]))
    return {"items": items, "examinees": len(attempts), "group_size": k}


# =============================================================== admin metrics

def admin_metrics(db: Session) -> dict:
    return cached(("admin",), lambda: _admin_metrics(db), CACHE_TTL)


def _active_users(db: Session, days: int) -> int:
    return db.scalar(select(func.count(distinct(ActivityLog.user_id))).where(
        ActivityLog.user_id.is_not(None), ActivityLog.created_at >= utcnow() - timedelta(days=days))) or 0


def _per_day(db: Session, col, where, days: int = 30) -> list[dict]:
    day = local_day(db, col)
    rows = dict((str(d)[:10], n) for d, n in db.execute(select(day, func.count()).where(
        col >= utcnow() - timedelta(days=days), *where).group_by(day)).all())
    today = (utcnow() + LOCAL_OFFSET).date()
    return [{"day": (today - timedelta(days=i)).isoformat(), "n": rows.get((today - timedelta(days=i)).isoformat(), 0)}
            for i in range(days - 1, -1, -1)]


def _admin_metrics(db: Session) -> dict:
    since30 = utcnow() - timedelta(days=30)
    # peak activity heatmap: weekday x hour (PH time)
    hour, dow = local_hour(db, ActivityLog.created_at), local_dow(db, ActivityLog.created_at)
    grid = [[0] * 24 for _ in range(7)]
    for d, h, n in db.execute(select(dow, hour, func.count()).where(ActivityLog.created_at >= since30)
                              .group_by(dow, hour)).all():
        if d is not None and h is not None:
            grid[int(d)][int(h)] = n
    peak = max((v for row in grid for v in row), default=0)

    popular_resources = db.execute(
        select(Resource.id, Resource.title, Resource.kind, func.count(ResourceView.id).label("v"))
        .join(ResourceView, ResourceView.resource_id == Resource.id).where(ResourceView.created_at >= since30)
        .group_by(Resource.id, Resource.title, Resource.kind).order_by(func.count(ResourceView.id).desc()).limit(8)
    ).all()
    popular_assessments = db.execute(
        select(Assessment.id, Assessment.title, Assessment.kind, func.count(Attempt.id))
        .join(Attempt, Attempt.assessment_id == Assessment.id).where(Attempt.started_at >= since30)
        .group_by(Assessment.id, Assessment.title, Assessment.kind).order_by(func.count(Attempt.id).desc()).limit(8)
    ).all()
    access = dict(db.execute(select(Resource.kind, func.count(ResourceView.id))
                             .join(ResourceView, ResourceView.resource_id == Resource.id)
                             .group_by(Resource.kind)).all())
    content_access = [(k.capitalize(), access.get(k, 0)) for k in ("video", "article", "file", "link")]

    by_source = defaultdict(lambda: {"total": 0, "approved": 0, "rejected": 0, "pending_review": 0, "draft": 0})
    for src, st, n in db.execute(select(Question.source_type, Question.status, func.count(Question.id))
                                 .group_by(Question.source_type, Question.status)).all():
        by_source[src]["total"] += n
        by_source[src][st] = n
    sources = []
    for src in ("manual", "csv_import", "scraped", "ai_generated"):
        s = by_source[src]
        decided = s["approved"] + s["rejected"]
        sources.append({"source": src, **s, "approval_rate": round(100.0 * s["approved"] / decided, 1) if decided else None})

    return {
        "dau": _active_users(db, 1), "wau": _active_users(db, 7), "mau": _active_users(db, 30),
        "users": dict(db.execute(select(User.role, func.count(User.id)).group_by(User.role)).all()),
        "registrations": _per_day(db, User.created_at, [User.role == "student"]),
        "logins": _per_day(db, ActivityLog.created_at, [ActivityLog.event == "login"]),
        "attempts": _per_day(db, Attempt.submitted_at, [Attempt.status == "submitted"]),
        "heat": grid, "heat_peak": peak, "session_minutes": avg_session_minutes(db),
        "popular_resources": popular_resources, "popular_assessments": popular_assessments,
        "content_access": content_access, "sources": sources,
        "totals": {
            "questions": db.scalar(select(func.count(Question.id))) or 0,
            "approved": db.scalar(select(func.count(Question.id)).where(Question.status == "approved")) or 0,
            "resources": db.scalar(select(func.count(Resource.id))) or 0,
            "assessments": db.scalar(select(func.count(Assessment.id))) or 0,
            "attempts": db.scalar(select(func.count(Attempt.id)).where(Attempt.status == "submitted")) or 0,
        },
    }


def avg_session_minutes(db: Session, days: int = 14, gap_minutes: int = 30) -> float | None:
    """Sessionize page views/logins per user: a new session starts after a 30-minute gap."""
    rows = db.execute(select(ActivityLog.user_id, ActivityLog.created_at, ActivityLog.duration_ms)
                      .where(ActivityLog.user_id.is_not(None), ActivityLog.created_at >= utcnow() - timedelta(days=days))
                      .order_by(ActivityLog.user_id, ActivityLog.created_at)).all()
    sessions, last_user, start, last = [], None, None, None
    gap = timedelta(minutes=gap_minutes)
    for uid, ts, _ in rows:
        if uid != last_user or ts - last > gap:
            if start is not None:
                sessions.append((last - start).total_seconds() + 60)  # count the last page as ~1 minute
            last_user, start = uid, ts
        last = ts
    if start is not None:
        sessions.append((last - start).total_seconds() + 60)
    return round(sum(sessions) / len(sessions) / 60, 1) if sessions else None


def system_health(db: Session) -> dict:
    from app.middleware import REQUEST_STATS, STARTED_AT

    tables = {}
    for name, model in (("users", User), ("questions", Question), ("attempts", Attempt),
                        ("attempt_answers", AttemptAnswer), ("resources", Resource), ("activity_log", ActivityLog)):
        tables[name] = db.scalar(select(func.count()).select_from(model)) or 0
    return {
        "errors": db.scalars(select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(20)).all(),
        "errors_24h": db.scalar(select(func.count(ErrorLog.id)).where(ErrorLog.created_at >= utcnow() - timedelta(days=1))) or 0,
        "requests": dict(REQUEST_STATS), "uptime_seconds": int(time.time() - STARTED_AT),
        "db_size": database_size_bytes(db), "dialect": db.get_bind().dialect.name, "tables": tables,
        "requests_per_day": _per_day(db, ActivityLog.created_at, [ActivityLog.event == "page_view"], 14),
    }


def upcoming_deadlines(db: Session, user: User, days: int = 14) -> list[dict]:
    from app.services.assessments import visible_assessments

    now = utcnow()
    soon = [a for a in visible_assessments(db, user) if a.is_published and a.due_at and now <= a.due_at <= now + timedelta(days=days)]
    passed = set(db.scalars(select(Attempt.assessment_id).where(Attempt.user_id == user.id, Attempt.passed.is_(True),
                                                                Attempt.is_adaptive.is_(False))))
    return [{"a": a, "done": a.id in passed} for a in sorted(soon, key=lambda a: a.due_at)]

