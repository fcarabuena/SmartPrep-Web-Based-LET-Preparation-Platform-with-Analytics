"""Report builder: user activity, performance, content usage and engagement reports with CSV/Excel/PDF export."""
import csv
import io
from datetime import date, datetime, timedelta

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    ActivityLog,
    Assessment,
    Attempt,
    Course,
    ForumPost,
    Resource,
    ResourceView,
    Topic,
    User,
)
from app.services.pdf import table_pdf
from app.services.sqlutil import local_day
from app.templating import LOCAL_OFFSET, fmt_dt

REPORT_TYPES = {
    "user_activity": "User activity",
    "performance": "Student performance",
    "content_usage": "Content usage",
    "engagement": "Engagement (daily)",
}


def _range(start: date, end: date) -> tuple[datetime, datetime]:
    """Local (PH) date range -> naive UTC datetimes [start, end+1day)."""
    s = datetime.combine(start, datetime.min.time()) - LOCAL_OFFSET
    e = datetime.combine(end + timedelta(days=1), datetime.min.time()) - LOCAL_OFFSET
    return s, e


def build_report(db: Session, kind: str, start: date, end: date, role: str = "", category_id: int = 0,
                 course_id: int = 0, assessment_id: int = 0) -> dict:
    s, e = _range(start, end)
    if kind == "user_activity":
        return _user_activity(db, s, e, role)
    if kind == "performance":
        return _performance(db, s, e, category_id, course_id, assessment_id)
    if kind == "content_usage":
        return _content_usage(db, s, e, category_id, course_id)
    return _engagement(db, s, e, start, end)


def _user_activity(db, s, e, role):
    users = select(User)
    if role:
        users = users.where(User.role == role)
    ev = dict(((uid, ev), n) for uid, ev, n in db.execute(
        select(ActivityLog.user_id, ActivityLog.event, func.count(ActivityLog.id))
        .where(ActivityLog.created_at >= s, ActivityLog.created_at < e).group_by(ActivityLog.user_id, ActivityLog.event)).all())
    att = dict(db.execute(select(Attempt.user_id, func.count(Attempt.id)).where(
        Attempt.status == "submitted", Attempt.submitted_at >= s, Attempt.submitted_at < e).group_by(Attempt.user_id)).all())
    rows = []
    for u in db.scalars(users.order_by(User.role, User.full_name)):
        rows.append([u.full_name, u.email, u.role, u.major_label if u.role == "student" else "", ev.get((u.id, "login"), 0),
                     ev.get((u.id, "page_view"), 0), att.get(u.id, 0), fmt_dt(u.last_seen_at), fmt_dt(u.created_at, "%Y-%m-%d"),
                     "Active" if u.is_active else "Inactive"])
    return {"title": "User activity report",
            "headers": ["Name", "Email", "Role", "Major", "Logins", "Page views", "Quizzes submitted", "Last seen",
                        "Registered", "Status"], "rows": rows}


def _performance(db, s, e, category_id, course_id, assessment_id):
    stmt = (select(Attempt.user_id, func.count(Attempt.id), func.avg(Attempt.score_pct), func.max(Attempt.score_pct),
                   func.sum(case((Attempt.passed.is_(True), 1), else_=0)),
                   func.sum(case(((Attempt.attempt_no == 1) & Attempt.passed.is_(True), 1), else_=0)),
                   func.sum(Attempt.time_spent_seconds))
            .join(Assessment, Attempt.assessment_id == Assessment.id, isouter=True)
            .where(Attempt.status == "submitted", Attempt.is_adaptive.is_(False), Attempt.submitted_at >= s,
                   Attempt.submitted_at < e).group_by(Attempt.user_id))
    if assessment_id:
        stmt = stmt.where(Attempt.assessment_id == assessment_id)
    elif course_id:
        stmt = stmt.where(Assessment.course_id == course_id)
    elif category_id:
        stmt = stmt.where(Assessment.category_id == category_id)
    agg = {r[0]: r[1:] for r in db.execute(stmt).all()}
    from app.services.analytics import readiness

    rows = []
    for u in db.scalars(select(User).where(User.role == "student").order_by(User.full_name)):
        n, avg, best, passed, first, secs = agg.get(u.id, (0, None, None, 0, 0, 0))
        r = readiness(db, u)
        rows.append([u.full_name, u.email, u.major_label, n, f"{avg:.1f}" if avg is not None else "—",
                     f"{best:.0f}" if best is not None else "—", f"{100 * (passed or 0) / n:.0f}%" if n else "—",
                     first or 0, round((secs or 0) / 60, 1), f"{r['score']:.0f}% ({r['band']})"])
    rows.sort(key=lambda r: (r[3] == 0, r[0]))
    return {"title": "Student performance report",
            "headers": ["Student", "Email", "Major", "Attempts", "Avg score", "Best", "Pass rate", "1st-try passes",
                        "Minutes", "Readiness"], "rows": rows}


def _content_usage(db, s, e, category_id, course_id):
    stmt = (select(Resource.id, Resource.title, Resource.kind, Resource.level, Topic.name, Course.name,
                   func.count(ResourceView.id), func.count(distinct(ResourceView.user_id)),
                   func.sum(case((ResourceView.recommended.is_(True), 1), else_=0)))
            .outerjoin(Topic, Resource.topic_id == Topic.id).outerjoin(Course, Topic.course_id == Course.id)
            .outerjoin(ResourceView, (ResourceView.resource_id == Resource.id) & (ResourceView.created_at >= s)
                       & (ResourceView.created_at < e))
            .group_by(Resource.id, Resource.title, Resource.kind, Resource.level, Topic.name, Course.name)
            .order_by(func.count(ResourceView.id).desc()))
    if course_id:
        stmt = stmt.where(Topic.course_id == course_id)
    elif category_id:
        stmt = stmt.where(Course.category_id == category_id)
    rows = [[t, k, lv, co or "General", tp or "—", v, u, rec or 0] for _, t, k, lv, tp, co, v, u, rec in db.execute(stmt).all()]
    return {"title": "Content usage report",
            "headers": ["Resource", "Type", "Level", "Course", "Topic", "Views", "Unique viewers", "From recommendations"],
            "rows": rows}


def _engagement(db, s, e, start, end):
    def per_day(col, *where):
        d = local_day(db, col)
        return {str(k)[:10]: n for k, n in db.execute(select(d, func.count()).where(col >= s, col < e, *where)
                                                       .group_by(d)).all()}

    d = local_day(db, ActivityLog.created_at)
    active = {str(k)[:10]: n for k, n in db.execute(
        select(d, func.count(distinct(ActivityLog.user_id))).where(ActivityLog.created_at >= s, ActivityLog.created_at < e,
                                                                   ActivityLog.user_id.is_not(None)).group_by(d)).all()}
    logins = per_day(ActivityLog.created_at, ActivityLog.event == "login")
    attempts = per_day(Attempt.submitted_at, Attempt.status == "submitted")
    views = per_day(ResourceView.created_at)
    posts = per_day(ForumPost.created_at)
    regs = per_day(User.created_at)
    rows = []
    day = start
    while day <= end:
        k = day.isoformat()
        rows.append([k, active.get(k, 0), logins.get(k, 0), regs.get(k, 0), attempts.get(k, 0), views.get(k, 0),
                     posts.get(k, 0)])
        day += timedelta(days=1)
    return {"title": "Engagement report",
            "headers": ["Date", "Active users", "Logins", "Registrations", "Quizzes submitted", "Resource views",
                        "Forum replies"], "rows": rows}


# ---------------------------------------------------------------- exports

def to_csv(report: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(report["headers"])
    w.writerows(report["rows"])
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(report: dict, subtitle: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = report["title"][:31]
    ws.append([report["title"]])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([subtitle])
    ws.append([])
    ws.append(report["headers"])
    for cell in ws[4]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
    for r in report["rows"]:
        ws.append(list(r))
    for i, h in enumerate(report["headers"], start=1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in report["rows"][:200]]) + 2
        ws.column_dimensions[ws.cell(row=4, column=i).column_letter].width = min(width, 50)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(report: dict, subtitle: str) -> bytes:
    return table_pdf(report["title"], subtitle, report["headers"], report["rows"], wide=len(report["headers"]) > 6)

