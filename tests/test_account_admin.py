"""Admin-created users (temporary password + forced change + 2FA), 2FA recovery script, scraper contact."""
import importlib.util
import re
import sys
from pathlib import Path

import pyotp
from sqlalchemy import select

from app.models import User
from app.security import verify_password
from tests.conftest import PASSWORD, get_csrf, make_user, post

ROOT = Path(__file__).resolve().parents[1]


def _create(admin_client, **data):
    return post(admin_client, "/admin/users/new", data, csrf_from="/admin/users/new")


def _sign_in(client, email, password):
    token = get_csrf(client, "/login")
    return client.post("/login", data={"email": email, "password": password, "csrf_token": token})


def test_create_user_page_and_button(admin_client):
    assert "Create user" in admin_client.get("/admin/users").text
    page = admin_client.get("/admin/users/new")
    assert "Temporary password" in page.text and 'name="role"' in page.text


def test_admin_creates_faculty_who_must_set_2fa_and_change_password(admin_client, db, client_factory):
    r = _create(admin_client, full_name="Liza Marquez", email="liza@example.com", role="faculty", password="TempPass123")
    assert "created as faculty" in r.text and "must change the password and set up 2FA" in r.text
    user = db.scalar(select(User).where(User.email == "liza@example.com"))
    assert user.must_change_password and not user.totp_enabled and user.email_verified
    assert "Temp password" in admin_client.get("/admin/users").text

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        # 1) password accepted -> 2FA setup is required before anything else
        r = _sign_in(c, "liza@example.com", "TempPass123")
        assert "Set up two-factor authentication" in r.text
        secret = c.get("/2fa/setup").text.split('user-select-all">')[1].split("<")[0]
        token = get_csrf(c, "/2fa/setup")
        r = c.post("/2fa/setup", data={"code": pyotp.TOTP(secret).now(), "csrf_token": token})
        # 2) then the temporary password must be replaced
        assert "Choose your own password" in r.text
        for url in ("/dashboard", "/questions", "/profile"):
            resp = c.get(url, follow_redirects=False)
            assert resp.status_code == 303 and resp.headers["location"] == "/account/change-password", url
        assert c.get("/api/notifications/count").status_code == 403
        token = get_csrf(c, "/account/change-password")
        r = c.post("/account/change-password", data={"new_password": "TempPass123", "confirm_password": "TempPass123",
                                                     "csrf_token": token})
        assert r.status_code == 400 and "different from your temporary password" in r.text
        r = c.post("/account/change-password", data={"new_password": "MyOwnPass456", "confirm_password": "MyOwnPass456",
                                                     "csrf_token": token})
        assert "Faculty Dashboard" in r.text and "new password is set" in r.text
    db.refresh(user)
    assert not user.must_change_password and user.totp_enabled
    assert verify_password("MyOwnPass456", user.password_hash)


def test_admin_creates_student_with_generated_password(admin_client, db):
    r = _create(admin_client, full_name="Ana Reyes", email="ana@example.com", role="student")
    assert r.status_code == 400 and "Choose a major for this student" in r.text
    r = _create(admin_client, full_name="Ana Reyes", email="ana@example.com", role="student", major="english")
    temp = re.search(r"Temporary password: (\S+) ", r.text).group(1)
    assert "must change the password on first sign-in" in r.text
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = _sign_in(c, "ana@example.com", temp)
        assert "Choose your own password" in r.text  # students skip 2FA but must change the password
        token = get_csrf(c, "/account/change-password")
        r = c.post("/account/change-password", data={"new_password": "Student456", "confirm_password": "Student456",
                                                     "csrf_token": token})
        assert "Hello, Ana" in r.text


def test_admin_can_create_another_admin(admin_client, db):
    _create(admin_client, full_name="Backup Admin", email="backup@example.com", role="admin", password="Backup1234")
    u = db.scalar(select(User).where(User.email == "backup@example.com"))
    assert u.role == "admin" and u.must_change_password


def test_admin_set_password_on_edit_is_temporary(admin_client, db):
    stu = make_user(db, "student", email="edit@example.com")
    post(admin_client, f"/admin/users/{stu.id}/edit", {"full_name": stu.full_name, "email": stu.email, "role": "student",
                                                       "major": "math", "is_active": "true", "email_verified": "true",
                                                       "new_password": "Reset1234"}, csrf_from=f"/admin/users/{stu.id}/edit")
    db.refresh(stu)
    assert stu.must_change_password


def test_regular_users_are_not_forced(student_client):
    assert student_client.get("/account/change-password", follow_redirects=False).headers["location"] == "/profile"
    assert student_client.get("/dashboard").status_code == 200


def test_anonymous_change_password_page_redirects(client):
    assert client.get("/account/change-password", follow_redirects=False).headers["location"] == "/login"


def _run_create_admin(monkeypatch, *argv):
    spec = importlib.util.spec_from_file_location("create_admin", ROOT / "scripts" / "create_admin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["create_admin.py", *argv])
    return mod.main()


def test_create_admin_reset_2fa(db, monkeypatch, capsys, client):
    from app.db import utcnow

    admin = make_user(db, "admin", email="boss@example.com")
    admin.failed_logins, admin.locked_until = 3, utcnow()
    old_hash, old_sv = admin.password_hash, admin.session_version
    db.commit()
    assert admin.totp_enabled
    assert _run_create_admin(monkeypatch, "--email", "BOSS@example.com", "--reset-2fa") == 0
    assert "2FA reset for boss@example.com" in capsys.readouterr().out
    db.refresh(admin)
    assert not admin.totp_enabled and admin.totp_secret is None and admin.locked_until is None
    assert admin.password_hash == old_hash and admin.session_version == old_sv + 1
    # next sign-in shows the QR setup again
    assert "Set up two-factor authentication" in _sign_in(client, "boss@example.com", PASSWORD).text
    assert _run_create_admin(monkeypatch, "--email", "nobody@example.com", "--reset-2fa") == 1


def test_create_admin_script_creates_admin_without_forced_change(db, monkeypatch):
    assert _run_create_admin(monkeypatch, "--email", "root@example.com", "--name", "Root", "--password", "RootPass123") == 0
    u = db.scalar(select(User).where(User.email == "root@example.com"))
    assert u.role == "admin" and not u.must_change_password


def test_scraper_user_agent_has_contact():
    from app.services import scraper

    assert "fcarabuena793@gmail.com" in scraper.USER_AGENT
    assert scraper.USER_AGENT.startswith("SmartPrepBot/1.0 (+https://")
