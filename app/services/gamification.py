"""Points ledger, levels, streaks, data-driven badges and leaderboards."""
import math
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.db import utcnow
from app.models import Assessment, Attempt, Badge, Course, PointsLedger, User, UserBadge
from app.models.gamification import (
    REASON_COMPLETE,
    REASON_CORRECT,
    REASON_IMPROVEMENT,
    REASON_PASS,
    REASON_PERFECT,
    REASON_RESOURCE,
    REASON_SERIES,
    REASON_STREAK,
)
from app.services.settings_store import get_setting
from app.templating import LOCAL_OFFSET

# ---------------------------------------------------------------- points & levels


def award(db: Session, user_id: int, points: int, reason: str, ref_type: str | None = None, ref_id: int | None = None,
          note: str | None = None) -> int:
    if points <= 0:
        return 0
    db.add(PointsLedger(user_id=user_id, points=points, reason=reason, ref_type=ref_type, ref_id=ref_id, note=note))
    return points


def total_points(db: Session, user_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(PointsLedger.points), 0)).where(PointsLedger.user_id == user_id)))


@dataclass
class LevelInfo:
    level: int
    floor: int
    next_floor: int
    progress_pct: int
    to_next: int


def level_info(db: Session, points: int) -> LevelInfo:
    step = int(get_setting(db, "level_step") or 100)
    # level n starts at step * n(n-1)/2  ->  n = floor((1 + sqrt(1 + 8p/step)) / 2)
    n = max(1, int((1 + math.sqrt(1 + 8 * max(points, 0) / step)) // 2))
    floor = step * n * (n - 1) // 2
    nxt = step * (n + 1) * n // 2
    pct = int(100 * (points - floor) / (nxt - floor)) if nxt > floor else 100
    return LevelInfo(n, floor, nxt, max(0, min(pct, 100)), max(0, nxt - points))


def local_date(dt) -> date:
    return (dt + LOCAL_OFFSET).date()


def activity_days(db: Session, user_id: int, days: int = 90) -> set[date]:
    since = utcnow() - timedelta(days=days)
    stamps = db.scalars(select(Attempt.submitted_at).where(Attempt.user_id == user_id, Attempt.status == "submitted",
                                                           Attempt.submitted_at >= since))
    return {local_date(s) for s in stamps if s}


def current_streak(db: Session, user_id: int) -> int:
    days = activity_days(db, user_id)
    today = local_date(utcnow())
    d = today if today in days else today - timedelta(days=1)
    streak = 0
    while d in days:
        streak += 1
        d -= timedelta(days=1)
    return streak


# ---------------------------------------------------------------- events

def on_attempt_submitted(db: Session, attempt: Attempt) -> None:
    """Award points and badges after an attempt is graded (students only)."""
    user = db.get(User, attempt.user_id)
    if user is None or user.role != "student":
        return
    cfg = get_setting(db, "points")
    a = db.get(Assessment, attempt.assessment_id) if attempt.assessment_id else None
    per_correct = a.points_per_correct if a else 1
    pass_bonus = a.pass_bonus if a else 0
    ref = ("attempt", attempt.id)
    earned = 0
    earned += award(db, user.id, attempt.correct_count * per_correct, REASON_CORRECT, *ref)
    earned += award(db, user.id, cfg["complete_quiz"], REASON_COMPLETE, *ref)
    if attempt.passed:
        earned += award(db, user.id, cfg["pass"] + pass_bonus, REASON_PASS, *ref)
    if attempt.score_pct == 100:
        earned += award(db, user.id, cfg["perfect_score"], REASON_PERFECT, *ref)
    prev = _previous_attempt(db, attempt)
    if prev is not None and (attempt.score_pct or 0) > (prev.score_pct or 0):
        earned += award(db, user.id, cfg["improvement"], REASON_IMPROVEMENT, *ref,
                        note=f"+{(attempt.score_pct or 0) - (prev.score_pct or 0):.0f} pts vs attempt #{prev.attempt_no}")
    # series: N quizzes inside the time window, at most one series bonus per window
    window_start = utcnow() - timedelta(hours=cfg["series_window_hours"])
    recent = db.scalar(select(func.count(Attempt.id)).where(Attempt.user_id == user.id, Attempt.status == "submitted",
                                                            Attempt.submitted_at >= window_start)) or 0
    already = db.scalar(select(func.count(PointsLedger.id)).where(PointsLedger.user_id == user.id,
                                                                  PointsLedger.reason == REASON_SERIES,
                                                                  PointsLedger.created_at >= window_start)) or 0
    if recent >= cfg["series_count"] and not already:
        earned += award(db, user.id, cfg["quiz_series"], REASON_SERIES, *ref,
                        note=f"{recent} quizzes within {cfg['series_window_hours']}h")
    # daily streak: once per local day when the streak is 2+ days
    streak = current_streak(db, user.id)
    today_start = _local_day_start_utc()
    got_today = db.scalar(select(func.count(PointsLedger.id)).where(PointsLedger.user_id == user.id,
                                                                    PointsLedger.reason == REASON_STREAK,
                                                                    PointsLedger.created_at >= today_start)) or 0
    if streak >= 2 and not got_today:
        earned += award(db, user.id, cfg["daily_streak"] * min(streak, 7), REASON_STREAK, *ref,
                        note=f"{streak}-day streak")
    attempt.points_awarded = earned
    db.commit()
    evaluate_badges(db, user, attempt, streak=streak)


def _local_day_start_utc():
    now_local = utcnow() + LOCAL_OFFSET
    return now_local.replace(hour=0, minute=0, second=0, microsecond=0) - LOCAL_OFFSET


def _previous_attempt(db: Session, attempt: Attempt) -> Attempt | None:
    if not attempt.assessment_id:
        return None
    return db.scalar(select(Attempt).where(
        Attempt.user_id == attempt.user_id, Attempt.assessment_id == attempt.assessment_id,
        Attempt.status == "submitted", Attempt.id != attempt.id, Attempt.is_adaptive == attempt.is_adaptive,
        Attempt.submitted_at <= attempt.submitted_at,
    ).order_by(Attempt.submitted_at.desc(), Attempt.id.desc()))


def on_resource_view(db: Session, user: User, resource, recommended: bool = False) -> int:
    """Award points for viewing a recommended resource (once per resource per day, daily cap)."""
    from app.services.recommendations import recommended_resource_ids

    if not recommended and resource.id not in recommended_resource_ids(db, user):
        return 0
    cfg = get_setting(db, "points")
    start = _local_day_start_utc()
    today = db.execute(select(func.coalesce(func.sum(PointsLedger.points), 0),
                              func.sum(case((PointsLedger.ref_id == resource.id, 1), else_=0)))
                       .where(PointsLedger.user_id == user.id, PointsLedger.reason == REASON_RESOURCE,
                              PointsLedger.created_at >= start)).one()
    if (today[1] or 0) or (today[0] or 0) + cfg["resource_view"] > cfg["resource_daily_cap"]:
        return 0
    pts = award(db, user.id, cfg["resource_view"], REASON_RESOURCE, "resource", resource.id, note=resource.title[:200])
    db.commit()
    return pts


# ---------------------------------------------------------------- badges

def evaluate_badges(db: Session, user: User, attempt: Attempt | None = None, streak: int | None = None) -> list[Badge]:
    earned_ids = set(db.scalars(select(UserBadge.badge_id).where(UserBadge.user_id == user.id)))
    badges = [b for b in db.scalars(select(Badge).where(Badge.is_active.is_(True))) if b.id not in earned_ids]
    if not badges:
        return []
    new: list[Badge] = []
    completed = None
    points = None
    for b in badges:
        ok = False
        ctx = f"attempt:{attempt.id}" if attempt else None
        score = (attempt.score_pct or 0) if attempt else None
        if b.rule_type == "accuracy" and attempt:
            ok = score >= b.threshold
        elif b.rule_type == "perfect" and attempt:
            ok = score >= 100
        elif b.rule_type == "improvement" and attempt:
            prev = _previous_attempt(db, attempt)
            ok = prev is not None and score - (prev.score_pct or 0) >= b.threshold
        elif b.rule_type == "category_mastery" and attempt and attempt.assessment_id:
            a = db.get(Assessment, attempt.assessment_id)
            ok = bool(a and (a.category_id or a.course_id)) and score >= b.threshold
        elif b.rule_type == "streak":
            ok = (streak if streak is not None else current_streak(db, user.id)) >= b.threshold
        elif b.rule_type in ("first_attempt", "quizzes_completed"):
            if completed is None:
                completed = db.scalar(select(func.count(Attempt.id)).where(Attempt.user_id == user.id,
                                                                           Attempt.status == "submitted")) or 0
            ok = completed >= max(b.threshold, 1)
        elif b.rule_type == "points":
            if points is None:
                points = total_points(db, user.id)
            ok = points >= b.threshold
        if ok:
            db.add(UserBadge(user_id=user.id, badge_id=b.id, context=ctx))
            new.append(b)
    if new:
        db.commit()
        from app.services.notify import notify

        for b in new:
            notify(db, user.id, f"New badge: {b.name}", b.description, "/gamification", kind="badge",
                   dedupe_key=f"badge:{b.id}")
    return new


def award_badge_manually(db: Session, user: User, badge: Badge, by: User) -> bool:
    if db.scalar(select(UserBadge.id).where(UserBadge.user_id == user.id, UserBadge.badge_id == badge.id)):
        return False
    db.add(UserBadge(user_id=user.id, badge_id=badge.id, context=f"manual:{by.id}"))
    db.commit()
    from app.services.notify import notify

    notify(db, user.id, f"New badge: {badge.name}", f"Awarded by {by.full_name}. {badge.description}",
           "/gamification", kind="badge", dedupe_key=f"badge:{badge.id}")
    return True


def user_badges(db: Session, user_id: int) -> list[UserBadge]:
    return list(db.scalars(select(UserBadge).where(UserBadge.user_id == user_id)
                           .options(selectinload(UserBadge.badge)).order_by(UserBadge.awarded_at.desc())))


def badges_from_attempt(db: Session, attempt: Attempt) -> list[Badge]:
    return list(db.scalars(select(Badge).join(UserBadge, UserBadge.badge_id == Badge.id)
                           .where(UserBadge.user_id == attempt.user_id, UserBadge.context == f"attempt:{attempt.id}")))


# ---------------------------------------------------------------- leaderboards

@dataclass
class LeaderRow:
    rank: int
    user_id: int
    name: str
    major: str
    value: float
    first_passes: int
    attempts: int
    time_spent: int
    label: str


def _first_pass_counts(db: Session, user_ids: list[int], assessment_ids: list[int] | None = None) -> dict[int, int]:
    stmt = (select(Attempt.user_id, func.count(Attempt.id))
            .where(Attempt.status == "submitted", Attempt.attempt_no == 1, Attempt.passed.is_(True),
                   Attempt.is_adaptive.is_(False), Attempt.user_id.in_(user_ids or [0])).group_by(Attempt.user_id))
    if assessment_ids is not None:
        stmt = stmt.where(Attempt.assessment_id.in_(assessment_ids or [0]))
    return dict(db.execute(stmt).all())


def _rank(rows: list[LeaderRow]) -> list[LeaderRow]:
    # value desc; ties -> more first-attempt passes first; then less time; then name
    rows.sort(key=lambda r: (-r.value, -r.first_passes, r.time_spent, r.name))
    for i, r in enumerate(rows, start=1):
        r.rank = i
    return rows


def leaderboard(db: Session, scope: str = "overall", ref_id: int = 0, limit: int = 50) -> list[LeaderRow]:
    students = {u.id: u for u in db.scalars(select(User).where(User.role == "student", User.is_active.is_(True)))}
    if not students:
        return []
    if scope == "overall":
        pts = dict(db.execute(select(PointsLedger.user_id, func.sum(PointsLedger.points))
                              .group_by(PointsLedger.user_id)).all())
        fp = _first_pass_counts(db, list(students))
        rows = [LeaderRow(0, uid, u.full_name, u.major_label, float(pts.get(uid, 0) or 0), fp.get(uid, 0), 0, 0,
                          f"{int(pts.get(uid, 0) or 0)} pts") for uid, u in students.items() if pts.get(uid)]
        return _rank(rows)[:limit]

    stmt = select(Attempt.user_id, Attempt.assessment_id, func.max(Attempt.score_pct), func.count(Attempt.id),
                  func.sum(Attempt.time_spent_seconds)).where(Attempt.status == "submitted",
                                                             Attempt.is_adaptive.is_(False))
    if scope == "category":
        ids = list(db.scalars(select(Assessment.id).outerjoin(Course, Assessment.course_id == Course.id)
                              .where((Assessment.category_id == ref_id) | (Course.category_id == ref_id))
                              .where(Assessment.leaderboard_public.is_(True))))
    elif scope == "course":
        ids = list(db.scalars(select(Assessment.id).where(Assessment.course_id == ref_id,
                                                          Assessment.leaderboard_public.is_(True))))
    else:  # game / single assessment
        ids = list(db.scalars(select(Assessment.id).where(Assessment.id == ref_id,
                                                          Assessment.leaderboard_public.is_(True))))
    if not ids:
        return []
    per = db.execute(stmt.where(Attempt.assessment_id.in_(ids)).group_by(Attempt.user_id, Attempt.assessment_id)).all()
    agg: dict[int, list] = {}
    for uid, _aid, best, n, secs in per:
        if uid not in students:
            continue
        a = agg.setdefault(uid, [0.0, 0, 0, 0])
        a[0] += best or 0
        a[1] += 1
        a[2] += n
        a[3] += secs or 0
    fp = _first_pass_counts(db, list(agg), ids)
    rows = [LeaderRow(0, uid, students[uid].full_name, students[uid].major_label, round(v[0] / v[1], 1), fp.get(uid, 0),
                      v[2], v[3], f"{v[0] / v[1]:.1f}%") for uid, v in agg.items()]
    return _rank(rows)[:limit]


def my_rank(db: Session, user_id: int) -> tuple[int | None, int]:
    rows = leaderboard(db, "overall", limit=10_000)
    for r in rows:
        if r.user_id == user_id:
            return r.rank, len(rows)
    return None, len(rows)
