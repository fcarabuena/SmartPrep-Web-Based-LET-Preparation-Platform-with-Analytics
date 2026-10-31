"""User profile, password change and optional 2FA management."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_any
from app.models import MAJORS, User
from app.security import hash_password, password_problems, verify_password, verify_totp
from app.templating import flash, render

router = APIRouter(tags=["profile"])


def _profile_ctx(db: Session, user: User) -> dict:
    ctx = {"active": "profile", "majors": MAJORS, "badges": [], "points": 0, "level": None}
    try:
        from app.services.gamification import level_info, total_points, user_badges

        ctx["badges"] = user_badges(db, user.id)
        ctx["points"] = total_points(db, user.id)
        ctx["level"] = level_info(db, ctx["points"])
    except ImportError:
        pass
    return ctx


@router.get("/profile", name="profile")
def profile_page(request: Request, user: User = Depends(require_any), db: Session = Depends(get_db)):
    return render(request, "profile/profile.html", _profile_ctx(db, user))


@router.post("/profile")
def profile_update(
    request: Request,
    full_name: str = Form(""),
    major: str = Form(""),
    student_no: str = Form(""),
    bio: str = Form(""),
    user: User = Depends(require_any),
    db: Session = Depends(get_db),
):
    errors = []
    full_name = full_name.strip()
    if not (2 <= len(full_name) <= 150):
        errors.append("Full name must be 2–150 characters.")
    if user.role == "student" and major not in MAJORS:
        errors.append("Please choose a valid major.")
    if len(bio) > 1000:
        errors.append("Bio must be at most 1000 characters.")
    if errors:
        return render(request, "profile/profile.html", {**_profile_ctx(db, user), "errors": errors}, status_code=400)
    user.full_name = full_name
    if user.role == "student" or major in MAJORS:
        user.major = major or user.major
    user.student_no = student_no.strip()[:40] or None
    user.bio = bio.strip() or None
    db.commit()
    flash(request, "Profile updated.")
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/password")
def change_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    user: User = Depends(require_any),
    db: Session = Depends(get_db),
):
    errors = []
    if user.password_hash and not verify_password(current_password, user.password_hash):
        errors.append("Current password is incorrect.")
    errors += password_problems(new_password)
    if new_password != confirm_password:
        errors.append("New passwords do not match.")
    if errors:
        return render(request, "profile/profile.html", {**_profile_ctx(db, user), "pw_errors": errors},
                      status_code=400)
    user.password_hash = hash_password(new_password)
    user.session_version += 1  # signs out other devices
    db.commit()
    request.session["sv"] = user.session_version
    flash(request, "Password changed. Other devices have been signed out.")
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/2fa/disable")
def disable_2fa(request: Request, code: str = Form(""), user: User = Depends(require_any),
                db: Session = Depends(get_db)):
    if user.is_staff:
        flash(request, "Two-factor authentication is required for admin and faculty accounts.", "warning")
    elif not verify_totp(user.totp_secret, code):
        flash(request, "Invalid authentication code.", "danger")
    else:
        user.totp_enabled = False
        user.totp_secret = None
        db.commit()
        flash(request, "Two-factor authentication disabled.")
    return RedirectResponse("/profile", status_code=303)
