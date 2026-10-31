"""Analytics pages: student progress, class analytics, at-risk, item analysis, admin analytics/health, reports."""
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import require_admin, require_staff, require_student
from app.models import ROLES, Assessment, Attempt, Category, Course, Message, User
from app.services.analytics import (
    admin_metrics,
    at_risk_students,
    class_overview,
    item_analysis,
    readiness,
    student_progress,
    system_health,
)
from app.services.gamification import my_rank, total_points
from app.services.notify import email_user, notify
from app.services.recommendations import study_plan
from app.services.reports import REPORT_TYPES, build_report, to_csv, to_pdf, to_xlsx
from app.services.settings_store import get_setting
from app.templating import LOCAL_OFFSET, flash, fmt_dt, render

router = APIRouter(tags=["analytics"])


def _progress_ctx(db: Session, user: User, category: int, course: int, mode: str) -> dict:
    rank, of = my_rank(db, user.id)
    plan = study_plan(db, user, limit=3)
    return {
        "student": user, "p": student_progress(db, user, category, course), "ready": readiness(db, user),
        "rank": rank, "of": of, "points": total_points(db, user.id), "category": category, "course": course,
        "mode": mode if mode in ("topics", "exams") else "topics", "plan": plan,
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "courses": [c for c in db.scalars(select(Course).order_by(Course.category_id, Course.sort_order))
                    if not c.major or c.major == user.major],
    }


@router.get("/progress", name="progress")
def progress(request: Request, category: int = 0, course: int = 0, mode: str = "topics",
             user: User = Depends(require_student), db: Session = Depends(get_db)):
    return render(request, "analytics/progress.html", {"active": "progress",
                                                       **_progress_ctx(db, user, category, course, mode)})


# ---------------------------------------------------------------- faculty

@router.get("/analytics/class", name="faculty_analytics")
def class_analytics(request: Request, days: int = 30, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    days = days if days in (7, 30, 90, 0) else 30
    return render(request, "analytics/class.html", {"active": "faculty_analytics", "c": class_overview(db, days),
                                                    "days": days, "risk": at_risk_students(db)[:5],
                                                    "risk_count": len(at_risk_students(db))})


@router.get("/analytics/at-risk", name="at_risk")
def at_risk(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return render(request, "analytics/at_risk.html", {
        "active": "at_risk", "rows": at_risk_students(db), "inactive_days": get_setting(db, "at_risk_inactive_days"),
        "min_ready": get_setting(db, "at_risk_readiness"),
    })


@router.get("/analytics/students", name="student_directory")
def student_directory(request: Request, q: str = "", user: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = select(User).where(User.role == "student")
    if q:
        stmt = stmt.where(func.lower(User.full_name).like(f"%{q.lower()}%") | func.lower(User.email).like(f"%{q.lower()}%"))
    students = db.scalars(stmt.order_by(User.full_name).limit(200)).all()
    stats = {uid: (n, avg) for uid, n, avg in db.execute(
        select(Attempt.user_id, func.count(Attempt.id), func.avg(Attempt.score_pct))
        .where(Attempt.status == "submitted").group_by(Attempt.user_id)).all()}
    return render(request, "analytics/students.html", {"active": "faculty_analytics", "students": students,
                                                       "stats": stats, "q": q})


@router.get("/analytics/students/{student_id:int}")
def student_drilldown(request: Request, student_id: int, category: int = 0, course: int = 0, mode: str = "topics",
                      user: User = Depends(require_staff), db: Session = Depends(get_db)):
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404, "Student not found")
    recent = db.scalars(select(Attempt).where(Attempt.user_id == student.id, Attempt.status == "submitted")
                        .order_by(Attempt.submitted_at.desc()).limit(10)).all()
    return render(request, "analytics/student_detail.html", {
        "active": "faculty_analytics", "recent": recent, **_progress_ctx(db, student, category, course, mode),
    })


@router.post("/analytics/students/{student_id:int}/feedback")
def send_feedback(request: Request, student_id: int, background: BackgroundTasks, subject: str = Form(""),
                  body: str = Form(""),
                  user: User = Depends(require_staff), db: Session = Depends(get_db)):
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404, "Student not found")
    body = body.strip()
    if not body:
        flash(request, "Feedback message cannot be empty.", "danger")
        return RedirectResponse(f"/analytics/students/{student_id}", status_code=303)
    msg = Message(sender_id=user.id, recipient_id=student.id, subject=(subject.strip() or "Feedback from your faculty")[:255],
                  body=body[:10000], is_feedback=True)
    db.add(msg)
    db.commit()
    msg.thread_id = msg.id
    db.commit()
    notify(db, student.id, f"New feedback from {user.full_name}", msg.subject, f"/inbox/{msg.id}", kind="feedback")
    email_user(db, student, f"Feedback: {msg.subject}", body, f"/inbox/{msg.id}", background)
    flash(request, f"Feedback sent to {student.full_name}.")
    return RedirectResponse(f"/analytics/students/{student_id}", status_code=303)


@router.get("/analytics/items", name="item_analysis")
def items(request: Request, assessment: int = 0, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Attempt.assessment_id, func.count(Attempt.id))
                             .where(Attempt.status == "submitted", Attempt.is_adaptive.is_(False))
                             .group_by(Attempt.assessment_id)).all())
    options = [a for a in db.scalars(select(Assessment).order_by(Assessment.title)) if counts.get(a.id)]
    if not assessment and options:
        assessment = max(options, key=lambda a: counts[a.id]).id
    data = item_analysis(db, assessment) if assessment else {"items": [], "examinees": 0, "group_size": 0}
    return render(request, "analytics/items.html", {"active": "item_analysis", "options": options, "counts": counts,
                                                    "assessment": assessment, "data": data})


# ---------------------------------------------------------------- admin

@router.get("/admin/analytics", name="admin_analytics")
def admin_analytics(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return render(request, "analytics/admin.html", {"active": "admin_analytics", "m": admin_metrics(db)})


@router.get("/admin/health", name="admin_health")
def admin_health(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return render(request, "analytics/health.html", {"active": "admin_health", "h": system_health(db)})


# ---------------------------------------------------------------- reports

def _report_params(kind: str, start: str, end: str) -> tuple[str, date, date]:
    today = (utcnow() + LOCAL_OFFSET).date()
    try:
        s = date.fromisoformat(start) if start else today - timedelta(days=29)
        e = date.fromisoformat(end) if end else today
    except ValueError:
        raise HTTPException(400, "Invalid date")
    if e < s:
        s, e = e, s
    if (e - s).days > 366:
        raise HTTPException(400, "Date range is limited to one year.")
    return (kind if kind in REPORT_TYPES else "performance"), s, e


@router.get("/reports", name="reports")
def reports(request: Request, kind: str = "performance", start: str = "", end: str = "", role: str = "",
            category: int = 0, course: int = 0, assessment: int = 0, preview: int = 0,
            user: User = Depends(require_staff), db: Session = Depends(get_db)):
    kind, s, e = _report_params(kind, start, end)
    report = build_report(db, kind, s, e, role, category, course, assessment) if preview else None
    params = {"kind": kind, "start": s.isoformat(), "end": e.isoformat(), "role": role, "category": category,
              "course": course, "assessment": assessment}
    return render(request, "analytics/reports.html", {
        "active": "reports", "types": REPORT_TYPES, "report": report, "params": params, "roles": ROLES,
        "qs": "&".join(f"{k}={v}" for k, v in params.items()),
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "courses": db.scalars(select(Course).order_by(Course.category_id, Course.sort_order)).all(),
        "assessments": db.scalars(select(Assessment).order_by(Assessment.title)).all(),
    })


@router.get("/reports/export")
def export_report(fmt: str = "csv", kind: str = "performance", start: str = "", end: str = "", role: str = "",
                  category: int = 0, course: int = 0, assessment: int = 0,
                  user: User = Depends(require_staff), db: Session = Depends(get_db)):
    kind, s, e = _report_params(kind, start, end)
    report = build_report(db, kind, s, e, role, category, course, assessment)
    subtitle = f"{s.isoformat()} to {e.isoformat()} · generated {fmt_dt(utcnow())} by {user.full_name}"
    name = f"smartprep_{kind}_{s.isoformat()}_{e.isoformat()}"
    if fmt == "xlsx":
        return Response(to_xlsx(report, subtitle),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    if fmt == "pdf":
        return Response(to_pdf(report, subtitle), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return Response(to_csv(report), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
