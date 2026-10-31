"""Admin: user management."""
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin
from app.models import MAJORS, ROLES, User
from app.routers.auth import find_user, normalize_email
from app.security import hash_password, password_problems
from app.templating import flash, render

router = APIRouter(prefix="/admin/users", tags=["admin"])
PAGE_SIZE = 25


@router.get("", name="admin_users")
def list_users(
    request: Request,
    q: str = "",
    role: str = "",
    status: str = "",
    page: int = 1,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(User)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.full_name).like(like)))
    if role in ROLES:
        stmt = stmt.where(User.role == role)
    if status == "active":
        stmt = stmt.where(User.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(User.is_active.is_(False))
    elif status == "unverified":
        stmt = stmt.where(User.email_verified.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page = max(page, 1)
    users = db.scalars(stmt.order_by(User.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    return render(request, "admin/users.html", {
        "active": "admin_users", "users": users, "q": q, "role": role, "status": status, "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)), "total": total, "roles": ROLES, "majors": MAJORS,
    })


def _form_ctx(user: User | None, form: dict | None = None, errors: list | None = None) -> dict:
    return {"active": "admin_users", "edit_user": user, "form": form or {}, "errors": errors or [],
            "roles": ROLES, "majors": MAJORS}


@router.get("/new")
def new_user_page(request: Request, admin: User = Depends(require_admin)):
    return render(request, "admin/user_form.html", _form_ctx(None))


@router.post("/new")
def create_user(
    request: Request,
    full_name: str = Form(""),
    email: str = Form(""),
    role: str = Form("student"),
    major: str = Form(""),
    password: str = Form(""),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    form = {"full_name": full_name.strip(), "email": email.strip(), "role": role, "major": major}
    errors = []
    norm = normalize_email(email)
    if len(form["full_name"]) < 2:
        errors.append("Full name is required.")
    if not norm:
        errors.append("A valid email is required.")
    elif find_user(db, norm):
        errors.append("That email is already registered.")
    if role not in ROLES:
        errors.append("Invalid role.")
    if major and major not in MAJORS:
        errors.append("Invalid major.")
    if role == "student" and not major:
        errors.append("Choose a major for this student.")
    temp_password = None
    if password:
        errors += password_problems(password)
    else:
        temp_password = secrets.token_urlsafe(9) + "7a"
    if errors:
        return render(request, "admin/user_form.html", _form_ctx(None, form, errors), status_code=400)
    # The password set here is temporary: the user must replace it at first sign-in.
    # Admin/faculty also set up TOTP 2FA at first sign-in (enforced by the login flow).
    user = User(full_name=form["full_name"], email=norm, role=role, major=major or None,
                password_hash=hash_password(password or temp_password), email_verified=True,
                must_change_password=True)
    db.add(user)
    db.commit()
    msg = f"User {user.email} created as {role}."
    if temp_password:
        msg += f" Temporary password: {temp_password} (share it securely; it will not be shown again)."
    msg += " They must change the password" + (" and set up 2FA" if role != "student" else "") + " on first sign-in."
    flash(request, msg)
    return RedirectResponse("/admin/users", status_code=303)


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user


@router.get("/{user_id}/edit")
def edit_user_page(request: Request, user_id: int, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    form = {"full_name": user.full_name, "email": user.email, "role": user.role, "major": user.major or "",
            "is_active": user.is_active, "email_verified": user.email_verified}
    return render(request, "admin/user_form.html", _form_ctx(user, form))


@router.post("/{user_id}/edit")
def update_user(
    request: Request,
    user_id: int,
    full_name: str = Form(""),
    email: str = Form(""),
    role: str = Form("student"),
    major: str = Form(""),
    is_active: bool = Form(False),
    email_verified: bool = Form(False),
    new_password: str = Form(""),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)
    form = {"full_name": full_name.strip(), "email": email.strip(), "role": role, "major": major,
            "is_active": is_active, "email_verified": email_verified}
    errors = []
    norm = normalize_email(email)
    if len(form["full_name"]) < 2:
        errors.append("Full name is required.")
    if not norm:
        errors.append("A valid email is required.")
    else:
        other = find_user(db, norm)
        if other and other.id != user.id:
            errors.append("That email belongs to another user.")
    if role not in ROLES:
        errors.append("Invalid role.")
    if major and major not in MAJORS:
        errors.append("Invalid major.")
    if user.id == admin.id and (role != "admin" or not is_active):
        errors.append("You cannot remove your own admin role or deactivate yourself.")
    if new_password:
        errors += password_problems(new_password)
    if errors:
        return render(request, "admin/user_form.html", _form_ctx(user, form, errors), status_code=400)
    role_changed = user.role != role
    user.full_name, user.email, user.role, user.major = form["full_name"], norm, role, major or None
    user.is_active, user.email_verified = is_active, email_verified
    if new_password:
        user.password_hash = hash_password(new_password)
        user.must_change_password = user.id != admin.id  # an admin-set password is temporary for others
    if new_password or role_changed or not is_active:
        user.session_version += 1
    db.commit()
    flash(request, f"User {user.email} updated.")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/{user_id}/toggle")
def toggle_active(request: Request, user_id: int, admin: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    if user.id == admin.id:
        flash(request, "You cannot deactivate your own account.", "warning")
    else:
        user.is_active = not user.is_active
        user.session_version += 1
        db.commit()
        flash(request, f"{user.email} is now {'active' if user.is_active else 'deactivated'}.")
    return RedirectResponse(request.headers.get("referer") or "/admin/users", status_code=303)


@router.post("/{user_id}/reset-2fa")
def reset_2fa(request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    user.totp_enabled = False
    user.totp_secret = None
    user.session_version += 1
    db.commit()
    flash(request, f"2FA reset for {user.email}. They will set it up again on next sign-in.")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/{user_id}/unlock")
def unlock_user(request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    user.locked_until = None
    user.failed_logins = 0
    db.commit()
    flash(request, f"{user.email} unlocked.")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/{user_id}/delete")
def delete_user(request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    if user.id == admin.id:
        flash(request, "You cannot delete your own account.", "warning")
        return RedirectResponse("/admin/users", status_code=303)
    email = user.email
    db.delete(user)
    db.commit()
    flash(request, f"User {email} deleted.")
    return RedirectResponse("/admin/users", status_code=303)
