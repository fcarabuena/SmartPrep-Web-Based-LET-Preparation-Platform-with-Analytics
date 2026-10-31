from pathlib import Path

import pyotp
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.config import normalize_database_url
from app.models import AuthToken, User
from tests.conftest import PASSWORD, get_csrf, login, make_user, post


def test_healthz_does_not_touch_db(client, monkeypatch):
    import app.db as dbmod

    def boom(*a, **k):
        raise RuntimeError("db used")

    monkeypatch.setattr(dbmod, "SessionLocal", boom)
    r = client.get("/healthz")
    assert r.status_code == 200 and r.text == "ok"


def test_normalize_database_url():
    assert normalize_database_url("") == "sqlite:///./smartprep.db"
    u = normalize_database_url("postgres://u:p@ep-x.neon.tech/db")
    assert u.startswith("postgresql+psycopg://u:p@ep-x.neon.tech/db") and "sslmode=require" in u
    u = normalize_database_url("postgresql://u:p@host/db?sslmode=verify-full")
    assert u == "postgresql+psycopg://u:p@host/db?sslmode=verify-full"
    assert "sslmode" not in normalize_database_url("postgresql://u:p@localhost/db")


def test_security_headers(client):
    r = client.get("/login")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "cdn.jsdelivr.net" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_anonymous_redirected_to_login(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")


def test_register_autoverifies_without_brevo_and_login(client, db):
    token = get_csrf(client, "/register")
    r = client.post("/register", data={
        "full_name": "Ana Reyes", "email": "Ana@Example.com", "password": PASSWORD, "confirm_password": PASSWORD,
        "major": "english", "csrf_token": token,
    })
    assert r.status_code == 200 and "verified automatically" in r.text
    user = db.scalar(select(User).where(User.email == "ana@example.com"))
    assert user and user.email_verified and user.role == "student" and user.major == "english"
    r = login(client, user)
    assert "Hello, Ana" in r.text


def test_register_validation(client):
    token = get_csrf(client, "/register")
    r = client.post("/register", data={"full_name": "X", "email": "bad", "password": "short",
                                       "confirm_password": "nope", "major": "", "csrf_token": token})
    assert r.status_code == 400
    assert "valid email" in r.text and "Passwords do not match" in r.text


def test_email_verification_flow_with_brevo(client, db, monkeypatch):
    from app.config import settings
    from app.services import email as mail

    sent = []
    monkeypatch.setattr(settings, "BREVO_API_KEY", "fake-key")
    monkeypatch.setattr(mail, "send_email", lambda to, subj, html, name="": sent.append(html) or True)
    token = get_csrf(client, "/register")
    client.post("/register", data={"full_name": "Ben Cruz", "email": "ben@example.com", "password": PASSWORD,
                                   "confirm_password": PASSWORD, "major": "math", "csrf_token": token})
    user = db.scalar(select(User).where(User.email == "ben@example.com"))
    assert not user.email_verified
    r = login(client, user)
    assert "verify your email" in r.text
    link = sent[0].split("href='")[1].split("'")[0]
    path = link.replace("http://testserver", "")
    client.get(path)
    db.refresh(user)
    assert user.email_verified


def test_csrf_required(client, student):
    r = client.post("/login", data={"email": student.email, "password": PASSWORD})
    assert r.status_code == 403


def test_login_lockout(client, db, student):
    for _ in range(5):
        token = get_csrf(client)
        client.post("/login", data={"email": student.email, "password": "wrong", "csrf_token": token})
    token = get_csrf(client)
    r = client.post("/login", data={"email": student.email, "password": PASSWORD, "csrf_token": token})
    assert r.status_code == 423 and "temporarily locked" in r.text


def test_login_rate_limit(client, student):
    status = None
    for _ in range(12):
        token = get_csrf(client)
        status = client.post("/login", data={"email": "nobody@example.com", "password": "x", "csrf_token": token}).status_code
    assert status == 429


def test_remember_me_sets_persistent_cookie(client, student):
    token = get_csrf(client)
    r = client.post("/login", data={"email": student.email, "password": PASSWORD, "remember": "true",
                                    "csrf_token": token}, follow_redirects=False)
    assert "Max-Age=" in r.headers["set-cookie"]
    client.cookies.clear()
    token = get_csrf(client)
    r = client.post("/login", data={"email": student.email, "password": PASSWORD, "csrf_token": token},
                    follow_redirects=False)
    assert "Max-Age=" not in r.headers["set-cookie"]


def test_logout(student_client):
    r = post(student_client, "/logout")
    assert "signed out" in r.text
    assert student_client.get("/dashboard", follow_redirects=False).status_code == 303


def test_password_reset_flow(client, db, student, monkeypatch):
    from app.services import email as mail

    sent = []
    monkeypatch.setattr(mail, "send_email", lambda to, subj, html, name="": sent.append(html) or True)
    token = get_csrf(client, "/forgot")
    client.post("/forgot", data={"email": student.email, "csrf_token": token})
    link = sent[0].split("href='")[1].split("'")[0].replace("http://testserver", "")
    reset_token = link.split("token=")[1]
    page = client.get(link)
    assert "Choose a new password" in page.text
    token = get_csrf(client, link)
    client.post("/reset", data={"token": reset_token, "password": "NewPass456", "confirm_password": "NewPass456",
                                "csrf_token": token})
    r = login(client, student, password="NewPass456")
    assert "Hello" in r.text
    # token is single-use
    assert db.scalar(select(AuthToken).where(AuthToken.purpose == "reset")).used_at is not None
    assert "invalid or has expired" in client.get(link).text


def test_staff_must_set_up_2fa(client, db):
    fac = make_user(db, "faculty", email="newfac@example.com")
    fac.totp_enabled, fac.totp_secret = False, None
    db.commit()
    token = get_csrf(client)
    r = client.post("/login", data={"email": fac.email, "password": PASSWORD, "csrf_token": token})
    assert "Set up two-factor authentication" in r.text
    # not logged in yet
    assert client.get("/dashboard", follow_redirects=False).status_code == 303
    page = client.get("/2fa/setup").text
    secret = page.split('user-select-all">')[1].split("<")[0]
    token = get_csrf(client, "/2fa/setup")
    r = client.post("/2fa/setup", data={"code": pyotp.TOTP(secret).now(), "csrf_token": token})
    assert "Faculty Dashboard" in r.text
    db.refresh(fac)
    assert fac.totp_enabled


def test_2fa_wrong_code(client, faculty):
    token = get_csrf(client)
    client.post("/login", data={"email": faculty.email, "password": PASSWORD, "csrf_token": token})
    token = get_csrf(client, "/2fa/verify")
    r = client.post("/2fa/verify", data={"code": "000000", "csrf_token": token})
    assert r.status_code == 400
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_role_dashboards(client, db, student, faculty, admin):
    assert "Hello, Juan" in login(client, student).text
    client.cookies.clear()
    assert "Faculty Dashboard" in login(client, faculty).text
    client.cookies.clear()
    assert "Administration" in login(client, admin).text


def test_student_cannot_access_admin(student_client):
    assert student_client.get("/admin/users").status_code == 403


def test_profile_update_and_password_change(student_client, db, student):
    r = post(student_client, "/profile", {"full_name": "Juan P. Dela Cruz", "major": "science", "bio": "Hi"},
             csrf_from="/profile")
    assert "Profile updated" in r.text
    db.refresh(student)
    assert student.major == "science"
    r = post(student_client, "/profile/password", {"current_password": PASSWORD, "new_password": "Another123",
                                                   "confirm_password": "Another123"}, csrf_from="/profile")
    assert "Password changed" in r.text
    assert student_client.get("/profile").status_code == 200  # current session kept


def test_admin_user_management(admin_client, db):
    r = post(admin_client, "/admin/users/new", {"full_name": "New Faculty", "email": "nf@example.com",
                                                "role": "faculty", "password": "Faculty123"})
    assert "nf@example.com created" in r.text
    u = db.scalar(select(User).where(User.email == "nf@example.com"))
    assert u.role == "faculty"
    post(admin_client, f"/admin/users/{u.id}/toggle")
    db.refresh(u)
    assert not u.is_active
    r = post(admin_client, f"/admin/users/{u.id}/edit", {"full_name": "Renamed", "email": "nf@example.com",
                                                         "role": "student", "major": "tle", "is_active": "true",
                                                         "email_verified": "true"})
    db.refresh(u)
    assert u.full_name == "Renamed" and u.role == "student" and u.is_active
    assert "Renamed" in admin_client.get("/admin/users?q=renamed").text
    uid = u.id
    post(admin_client, f"/admin/users/{uid}/delete")
    db.expire_all()
    assert db.get(User, uid) is None


def test_admin_cannot_delete_self(admin_client, admin, db):
    r = post(admin_client, f"/admin/users/{admin.id}/delete")
    assert "cannot delete your own" in r.text


def test_deactivated_user_session_ends(client, db, student):
    login(client, student)
    student.is_active = False
    db.commit()
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_error_pages(client, student_client):
    r = student_client.get("/does-not-exist")
    assert r.status_code == 404 and "Page not found" in r.text


def test_alembic_migration_matches_models(tmp_path):
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.attributes["url"] = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if models and migrations diverge


def test_seed_curriculum_idempotent(db):
    from app.models import Category, Topic
    from app.services.curriculum import seed_curriculum

    first = seed_curriculum(db)
    second = seed_curriculum(db)
    assert first["categories"] == 3 and first["topics"] > 50
    assert second == {"categories": 0, "courses": 0, "topics": 0}
    assert db.query(Category).count() == 3 and db.query(Topic).count() == first["topics"]
