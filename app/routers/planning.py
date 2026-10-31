"""Calendar (FullCalendar feed + personal/global events) and student goals."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import require_any, require_student
from app.models import CalendarEvent, Category, Goal, User
from app.models.comms import GOAL_METRICS
from app.services.assessments import visible_assessments
from app.services.goals import goals_with_progress
from app.templating import LOCAL_OFFSET, flash, from_local, render

router = APIRouter(tags=["planning"])


def _iso_local(dt: datetime) -> str:
    return (dt + LOCAL_OFFSET).strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"


@router.get("/calendar", name="calendar")
def calendar_page(request: Request, user: User = Depends(require_any)):
    return render(request, "comms/calendar.html", {"active": "calendar"})


@router.get("/api/calendar/events")
def calendar_events(start: str = "", end: str = "", user: User = Depends(require_any), db: Session = Depends(get_db)):
    def parse(v: str, default: datetime) -> datetime:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt.replace(tzinfo=None) - (dt.utcoffset() or timedelta(0)) if dt.tzinfo else dt
        except ValueError:
            return default

    now = utcnow()
    s, e = parse(start, now - timedelta(days=45)), parse(end, now + timedelta(days=45))
    events = []
    for a in visible_assessments(db, user):
        if a.is_published and a.due_at and s <= a.due_at <= e:
            events.append({"id": f"a{a.id}", "title": f"Due: {a.title}", "start": _iso_local(a.due_at),
                           "url": f"/assessments/{a.id}/start", "color": "#e34948" if a.kind == "mock_exam" else "#2a78d6",
                           "extendedProps": {"kind": "due"}})
    for ev in db.scalars(select(CalendarEvent).where(or_(CalendarEvent.user_id == user.id, CalendarEvent.user_id.is_(None)),
                                                     CalendarEvent.start_at <= e,
                                                     or_(CalendarEvent.end_at >= s, CalendarEvent.start_at >= s))):
        item = {"id": f"e{ev.id}", "title": ev.title, "allDay": ev.all_day,
                "start": (ev.start_at + LOCAL_OFFSET).date().isoformat() if ev.all_day else _iso_local(ev.start_at),
                "color": "#1baf7a" if ev.user_id else "#6250d6",
                "extendedProps": {"kind": "event", "description": ev.description or "", "eid": ev.id,
                                  "mine": ev.user_id == user.id or (ev.user_id is None and user.is_staff)}}
        if ev.end_at:
            item["end"] = (ev.end_at + LOCAL_OFFSET).date().isoformat() if ev.all_day else _iso_local(ev.end_at)
        events.append(item)
    if user.role == "student":
        for g in db.scalars(select(Goal).where(Goal.user_id == user.id, Goal.completed_at.is_(None))):
            events.append({"id": f"g{g.id}", "title": f"Goal: {g.title}", "start": g.deadline.isoformat(),
                           "allDay": True, "url": "/goals", "color": "#eda100", "textColor": "#0b0b0b",
                           "extendedProps": {"kind": "goal"}})
    return JSONResponse(events)


@router.post("/calendar/events")
def create_event(request: Request, title: str = Form(""), start: str = Form(""), end: str = Form(""),
                 all_day: bool = Form(False), description: str = Form(""), everyone: bool = Form(False),
                 user: User = Depends(require_any), db: Session = Depends(get_db)):
    title = title.strip()[:255]
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end) if end else None
    except ValueError:
        start_dt = end_dt = None
    if not title or start_dt is None:
        flash(request, "An event needs a title and a start date.", "danger")
        return RedirectResponse("/calendar", status_code=303)
    if end_dt and end_dt < start_dt:
        end_dt = None
    db.add(CalendarEvent(user_id=None if (everyone and user.is_staff) else user.id, title=title,
                         description=description.strip() or None, start_at=from_local(start_dt),
                         end_at=from_local(end_dt) if end_dt else None, all_day=all_day, created_by_id=user.id))
    db.commit()
    flash(request, "Event added to the calendar.")
    return RedirectResponse("/calendar", status_code=303)


@router.post("/calendar/events/{eid:int}/delete")
def delete_event(request: Request, eid: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    ev = db.get(CalendarEvent, eid)
    if not ev or not (ev.user_id == user.id or (ev.user_id is None and user.is_staff)):
        raise HTTPException(404, "Event not found")
    db.delete(ev)
    db.commit()
    flash(request, "Event deleted.")
    return RedirectResponse("/calendar", status_code=303)


# ---------------------------------------------------------------- goals

@router.get("/goals", name="goals")
def goals_page(request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
    today = (utcnow() + LOCAL_OFFSET).date()
    return render(request, "comms/goals.html", {
        "active": "goals", "items": goals_with_progress(db, user), "metrics": GOAL_METRICS,
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "default_deadline": (today + timedelta(days=30)).isoformat(), "today": today.isoformat(),
    })


@router.post("/goals")
def create_goal(request: Request, title: str = Form(""), metric: str = Form("questions_answered"),
                target_value: float = Form(0), deadline: str = Form(""), category_id: int = Form(0),
                user: User = Depends(require_student), db: Session = Depends(get_db)):
    errors = []
    title = title.strip()[:255]
    if len(title) < 3:
        errors.append("Give your goal a short title.")
    if metric not in GOAL_METRICS:
        errors.append("Unknown goal type.")
    if target_value <= 0 or (metric in ("avg_score", "readiness", "category_mastery") and target_value > 100):
        errors.append("Target must be positive (and at most 100 for percentages).")
    try:
        due = date.fromisoformat(deadline)
    except ValueError:
        due = None
        errors.append("Choose a deadline.")
    today = (utcnow() + LOCAL_OFFSET).date()
    if due and due < today:
        errors.append("Deadline must be today or later.")
    if metric == "category_mastery" and not db.get(Category, category_id):
        errors.append("Choose a category for a category-mastery goal.")
    if errors:
        for e in errors:
            flash(request, e, "danger")
        return RedirectResponse("/goals", status_code=303)
    db.add(Goal(user_id=user.id, title=title, metric=metric, target_value=target_value, start_date=today,
                deadline=due, category_id=category_id if metric == "category_mastery" else None))
    db.commit()
    flash(request, "Goal created. Progress updates automatically as you study.")
    return RedirectResponse("/goals", status_code=303)


@router.post("/goals/{gid:int}/delete")
def delete_goal(request: Request, gid: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
    g = db.get(Goal, gid)
    if not g or g.user_id != user.id:
        raise HTTPException(404, "Goal not found")
    db.delete(g)
    db.commit()
    flash(request, "Goal deleted.")
    return RedirectResponse("/goals", status_code=303)
