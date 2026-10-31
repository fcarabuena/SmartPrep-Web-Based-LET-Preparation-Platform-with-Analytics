"""Authentication: register, verify email, login (+lockout, rate limit, 2FA), logout, password reset, Google."""
import time
from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db, utcnow
from app.deps import get_current_user_optional
from app.models import MAJORS, User
from app.models.user import ROLE_STUDENT
from app.security import (
    consume_token,
    create_token,
    hash_password,
    new_totp_secret,
    password_problems,
    peek_token,
    totp_qr_data_uri,
    verify_password,
    verify_totp,
)
from app.services import email as mail
from app.services.activity import log_event
from app.services.ratelimit import email_limiter, login_limiter
from app.services.settings_store import get_setting
from app.templating import flash, render

router = APIRouter(tags=["auth"])

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
VERIFY_HOURS = 48
RESET_HOURS = 1

oauth = None
if settings.google_enabled:
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def base_url(request: Request) -> str:
    return (settings.BASE_URL or str(request.base_url)).rstrip("/")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def safe_next(nxt: str | None) -> str:
    if nxt and nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return "/dashboard"


def normalize_email(raw: str) -> str | None:
    try:
        return validate_email((raw or "").strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == (email or "").strip().lower()))


def complete_login(request: Request, db: Session, user: User, remember: bool) -> None:
    request.session.clear()  # prevent session fixation
    request.session.update(
        uid=user.id, sv=user.session_version, remember=bool(remember), last=time.time()
    )
    user.last_login_at = utcnow()
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    log_event(db, "login", user.id, "/login")


def start_second_factor(request: Request, user: User, remember: bool, nxt: str) -> RedirectResponse:
    request.session.clear()
    request.session.update(pending_uid=user.id, pending_remember=bool(remember), pending_next=nxt, pending_tries=0)
    return RedirectResponse("/2fa/verify" if user.totp_enabled else "/2fa/setup", status_code=303)


def needs_second_factor(user: User) -> bool:
    return user.is_staff or user.totp_enabled


def send_verification(request: Request, db: Session, user: User, background: BackgroundTasks) -> None:
    token = create_token(db, user, "verify", VERIFY_HOURS)
    link = f"{base_url(request)}/verify?token={token}"
    html = mail.wrap("Verify your email", f"<p>Hi {user.full_name},</p><p>Confirm your email to start reviewing.</p>"
                     + mail.button(link, "Verify email"))
    background.add_task(mail.send_email, user.email, "Verify your Smart Prep account", html, user.full_name)


# ------------------------------------------------------------------ pages

@router.get("/", include_in_schema=False)
def home(user: User | None = Depends(get_current_user_optional)):
    return RedirectResponse("/dashboard" if user else "/login", status_code=303)


@router.get("/login", name="login")
def login_page(request: Request, next: str = "", user: User | None = Depends(get_current_user_optional)):
    if user:
        return RedirectResponse(safe_next(next), status_code=303)
    return render(request, "auth/login.html", {"next": next, "email": ""})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    remember: bool = Form(False),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    ctx = {"next": next, "email": email}

    def fail(msg: str, status: int = 400):
        return render(request, "auth/login.html", {**ctx, "error": msg}, status_code=status)

    if not login_limiter.hit(client_ip(request)):
        return fail("Too many login attempts. Please wait a few minutes and try again.", 429)

    user = find_user(db, email)
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        mins = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        return fail(f"This account is temporarily locked after repeated failed logins. Try again in {mins} minute(s).", 423)
    if not user or not verify_password(password, user.password_hash):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_logins = 0
            db.commit()
        log_event(db, "login_failed", user.id if user else None, "/login")
        return fail("Invalid email or password.")
    if not user.is_active:
        return fail("Your account has been deactivated. Please contact the administrator.", 403)
    if not user.email_verified:
        return render(request, "auth/login.html", {**ctx, "error": "Please verify your email address first.",
                                                   "show_resend": True}, status_code=403)

    nxt = safe_next(next)
    if needs_second_factor(user):
        user.failed_logins = 0
        db.commit()
        return start_second_factor(request, user, remember, nxt)
    complete_login(request, db, user, remember)
    return RedirectResponse(nxt, status_code=303)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("uid")
    request.session.clear()
    if uid:
        log_event(db, "logout", uid, "/logout")
    flash(request, "You have been signed out.", "info")
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------ registration

@router.get("/register", name="register")
def register_page(request: Request, db: Session = Depends(get_db)):
    if not get_setting(db, "allow_registration"):
        flash(request, "Self-registration is currently closed. Please contact the administrator.", "warning")
        return RedirectResponse("/login", status_code=303)
    return render(request, "auth/register.html", {"majors": MAJORS, "form": {}})


@router.post("/register")
def register_submit(
    request: Request,
    background: BackgroundTasks,
    full_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    major: str = Form(""),
    student_no: str = Form(""),
    db: Session = Depends(get_db),
):
    if not get_setting(db, "allow_registration"):
        return RedirectResponse("/login", status_code=303)
    form = {"full_name": full_name.strip(), "email": email.strip(), "major": major, "student_no": student_no.strip()}
    errors: list[str] = []
    norm = normalize_email(email)
    if len(form["full_name"]) < 2 or len(form["full_name"]) > 150:
        errors.append("Please enter your full name.")
    if not norm:
        errors.append("Please enter a valid email address.")
    elif find_user(db, norm):
        errors.append("An account with this email already exists.")
    if major not in MAJORS:
        errors.append("Please select your major.")
    errors += password_problems(password)
    if password != confirm_password:
        errors.append("Passwords do not match.")
    if errors:
        return render(request, "auth/register.html", {"majors": MAJORS, "form": form, "errors": errors}, status_code=400)

    user = User(
        email=norm, full_name=form["full_name"], password_hash=hash_password(password), role=ROLE_STUDENT,
        major=major, student_no=form["student_no"] or None,
    )
    db.add(user)
    db.commit()
    log_event(db, "register", user.id, "/register")
    send_verification(request, db, user, background)
    if not settings.email_enabled:
        # No email provider configured: the link is printed to the console and the account is auto-verified.
        user.email_verified = True
        db.commit()
        flash(request, "Account created. Email delivery is not configured, so your email was verified automatically. "
                       "You can sign in now.", "success")
    else:
        flash(request, f"Account created! We sent a verification link to {norm}. Please check your inbox.", "success")
    return RedirectResponse("/login", status_code=303)


@router.get("/verify")
def verify_email(request: Request, token: str = "", db: Session = Depends(get_db)):
    user = consume_token(db, token, "verify")
    if not user:
        flash(request, "This verification link is invalid or has expired. Request a new one below.", "danger")
        return RedirectResponse("/login", status_code=303)
    user.email_verified = True
    db.commit()
    flash(request, "Email verified. You can now sign in.", "success")
    return RedirectResponse("/login", status_code=303)


@router.post("/resend-verification")
def resend_verification(request: Request, background: BackgroundTasks, email: str = Form(""),
                        db: Session = Depends(get_db)):
    if email_limiter.hit("resend:" + client_ip(request)):
        user = find_user(db, email)
        if user and not user.email_verified and user.is_active:
            send_verification(request, db, user, background)
    flash(request, "If that account exists and is unverified, a new verification email has been sent.", "info")
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------ password reset

@router.get("/forgot", name="forgot")
def forgot_page(request: Request):
    return render(request, "auth/forgot.html")


@router.post("/forgot")
def forgot_submit(request: Request, background: BackgroundTasks, email: str = Form(""), db: Session = Depends(get_db)):
    if email_limiter.hit("forgot:" + client_ip(request)):
        user = find_user(db, email)
        if user and user.is_active:
            token = create_token(db, user, "reset", RESET_HOURS)
            link = f"{base_url(request)}/reset?token={token}"
            html = mail.wrap("Reset your password", f"<p>Hi {user.full_name},</p><p>Use the button below within "
                             f"{RESET_HOURS} hour to choose a new password. If you didn't ask for this, ignore this "
                             "email.</p>" + mail.button(link, "Reset password"))
            background.add_task(mail.send_email, user.email, "Smart Prep password reset", html, user.full_name)
    flash(request, "If an account exists for that email, a password reset link has been sent.", "info")
    return RedirectResponse("/login", status_code=303)


@router.get("/reset")
def reset_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not peek_token(db, token, "reset"):
        flash(request, "This reset link is invalid or has expired.", "danger")
        return RedirectResponse("/forgot", status_code=303)
    return render(request, "auth/reset.html", {"token": token})


@router.post("/reset")
def reset_submit(request: Request, token: str = Form(""), password: str = Form(""),
                 confirm_password: str = Form(""), db: Session = Depends(get_db)):
    errors = password_problems(password)
    if password != confirm_password:
        errors.append("Passwords do not match.")
    if errors:
        return render(request, "auth/reset.html", {"token": token, "errors": errors}, status_code=400)
    user = consume_token(db, token, "reset")
    if not user:
        flash(request, "This reset link is invalid or has expired.", "danger")
        return RedirectResponse("/forgot", status_code=303)
    user.password_hash = hash_password(password)
    user.session_version += 1  # sign out other sessions
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    flash(request, "Password updated. Please sign in.", "success")
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------ two-factor authentication

def _twofa_user(request: Request, db: Session) -> tuple[User | None, bool]:
    """User for a 2FA step: the pending login user, else the signed-in user. Returns (user, pending)."""
    pid = request.session.get("pending_uid")
    if pid:
        return db.get(User, pid), True
    uid = request.session.get("uid")
    if uid:
        user = db.get(User, uid)
        if user and user.session_version == request.session.get("sv"):
            request.state.user = user
            return user, False
    return None, False


def _finish_pending(request: Request, db: Session, user: User) -> RedirectResponse:
    remember = request.session.get("pending_remember", False)
    nxt = safe_next(request.session.get("pending_next"))
    complete_login(request, db, user, remember)
    return RedirectResponse(nxt, status_code=303)


@router.get("/2fa/setup", name="twofa_setup")
def twofa_setup_page(request: Request, db: Session = Depends(get_db)):
    user, pending = _twofa_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    secret = request.session.get("totp_setup_secret") or new_totp_secret()
    request.session["totp_setup_secret"] = secret
    return render(request, "auth/twofa_setup.html", {
        "secret": secret, "qr": totp_qr_data_uri(secret, user.email), "pending": pending, "user": user,
    })


@router.post("/2fa/setup")
def twofa_setup_submit(request: Request, code: str = Form(""), db: Session = Depends(get_db)):
    user, pending = _twofa_user(request, db)
    secret = request.session.get("totp_setup_secret")
    if not user or not secret:
        return RedirectResponse("/login", status_code=303)
    if not verify_totp(secret, code):
        return render(request, "auth/twofa_setup.html", {
            "secret": secret, "qr": totp_qr_data_uri(secret, user.email), "pending": pending, "user": user,
            "error": "That code is not valid. Check your authenticator app's time and try again.",
        }, status_code=400)
    user.totp_secret = secret
    user.totp_enabled = True
    db.commit()
    request.session.pop("totp_setup_secret", None)
    if pending:
        return _finish_pending(request, db, user)
    flash(request, "Two-factor authentication is now enabled.", "success")
    return RedirectResponse("/profile", status_code=303)


@router.get("/2fa/verify", name="twofa_verify")
def twofa_verify_page(request: Request, db: Session = Depends(get_db)):
    user, pending = _twofa_user(request, db)
    if not user or not pending:
        return RedirectResponse("/login", status_code=303)
    if not user.totp_enabled:
        return RedirectResponse("/2fa/setup", status_code=303)
    return render(request, "auth/twofa_verify.html")


@router.post("/2fa/verify")
def twofa_verify_submit(request: Request, code: str = Form(""), db: Session = Depends(get_db)):
    user, pending = _twofa_user(request, db)
    if not user or not pending:
        return RedirectResponse("/login", status_code=303)
    if verify_totp(user.totp_secret, code):
        return _finish_pending(request, db, user)
    tries = request.session.get("pending_tries", 0) + 1
    request.session["pending_tries"] = tries
    log_event(db, "2fa_failed", user.id, "/2fa/verify")
    if tries >= MAX_FAILED_LOGINS:
        request.session.clear()
        flash(request, "Too many invalid codes. Please sign in again.", "danger")
        return RedirectResponse("/login", status_code=303)
    return render(request, "auth/twofa_verify.html", {"error": "Invalid authentication code."}, status_code=400)


# ------------------------------------------------------------------ Google login (optional)

@router.get("/auth/google", name="google_login")
async def google_login(request: Request):
    if oauth is None:
        return RedirectResponse("/login", status_code=303)
    redirect_uri = f"{base_url(request)}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if oauth is None:
        return RedirectResponse("/login", status_code=303)
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        flash(request, "Google sign-in failed. Please try again.", "danger")
        return RedirectResponse("/login", status_code=303)
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified"):
        flash(request, "Your Google account email is not verified.", "danger")
        return RedirectResponse("/login", status_code=303)
    user = db.scalar(select(User).where(User.google_sub == info.get("sub"))) or find_user(db, email)
    created = False
    if user is None:
        if not get_setting(db, "allow_registration"):
            flash(request, "Self-registration is closed. Ask the administrator for an account.", "warning")
            return RedirectResponse("/login", status_code=303)
        user = User(email=email, full_name=info.get("name") or email.split("@")[0], role=ROLE_STUDENT,
                    email_verified=True, google_sub=info.get("sub"))
        db.add(user)
        db.commit()
        log_event(db, "register", user.id, "/auth/google")
        created = True
    if not user.is_active:
        flash(request, "Your account has been deactivated.", "danger")
        return RedirectResponse("/login", status_code=303)
    if not user.google_sub:
        user.google_sub = info.get("sub")
    user.email_verified = True
    db.commit()
    if needs_second_factor(user):
        return start_second_factor(request, user, False, "/dashboard")
    complete_login(request, db, user, False)
    if created or not user.major:
        flash(request, "Welcome! Please choose your major so we can tailor your review.", "info")
        return RedirectResponse("/profile", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)
