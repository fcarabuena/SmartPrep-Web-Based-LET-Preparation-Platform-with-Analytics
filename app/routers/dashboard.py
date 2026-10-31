"""Role-specific dashboards."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_any
from app.models import User
from app.templating import render

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", name="dashboard")
def dashboard(request: Request, user: User = Depends(require_any), db: Session = Depends(get_db)):
    if user.role == "admin":
        counts = dict(db.execute(select(User.role, func.count(User.id)).group_by(User.role)).all())
        return render(request, "dashboard/admin.html", {"active": "dashboard", "role_counts": counts})
    if user.role == "faculty":
        return render(request, "dashboard/faculty.html", {"active": "dashboard"})
    return render(request, "dashboard/student.html", {"active": "dashboard"})
