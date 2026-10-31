import os
import re

# Configure an isolated in-memory database and no external services BEFORE importing the app.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ENV"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key"
for key in ("BREVO_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GEMINI_API_KEY", "BASE_URL"):
    os.environ[key] = ""

import logging  # noqa: E402

import pyotp  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.cache import clear_cache  # noqa: E402
from app.services.ratelimit import email_limiter, login_limiter  # noqa: E402
from app.services.settings_store import clear_settings_cache  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)
PASSWORD = "Passw0rd123"
CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"|name="csrf_token" value="([^"]+)"')


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    clear_cache()
    clear_settings_cache()
    login_limiter.reset()
    email_limiter.reset()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def get_csrf(client: TestClient, path: str = "/login") -> str:
    html = client.get(path).text
    m = CSRF_RE.search(html)
    assert m, f"no csrf token on {path}"
    return m.group(1) or m.group(2)


def make_user(db, role="student", email=None, password=PASSWORD, major="math", totp=None, **kw) -> User:
    email = email or f"{role}{db.query(User).count() + 1}@example.com"
    user = User(email=email, full_name=kw.pop("full_name", f"Test {role.title()}"), role=role,
                password_hash=hash_password(password), email_verified=True, major=major if role == "student" else None,
                **kw)
    if role in ("admin", "faculty") or totp:
        user.totp_secret = totp or pyotp.random_base32()
        user.totp_enabled = True
    db.add(user)
    db.commit()
    return user


def login(client: TestClient, user: User, password: str = PASSWORD, remember: bool = False):
    token = get_csrf(client, "/login")
    data = {"email": user.email, "password": password, "csrf_token": token}
    if remember:
        data["remember"] = "true"
    r = client.post("/login", data=data)
    if user.totp_enabled:
        token = get_csrf(client, "/2fa/verify")
        r = client.post("/2fa/verify", data={"code": pyotp.TOTP(user.totp_secret).now(), "csrf_token": token})
    return r


def post(client: TestClient, url: str, data: dict | None = None, csrf_from: str = "/dashboard", **kw):
    data = dict(data or {})
    data["csrf_token"] = get_csrf(client, csrf_from)
    return client.post(url, data=data, **kw)


@pytest.fixture
def student(db):
    return make_user(db, "student", email="student@example.com", full_name="Juan Dela Cruz")


@pytest.fixture
def faculty(db):
    return make_user(db, "faculty", email="faculty@example.com", full_name="Maria Santos")


@pytest.fixture
def admin(db):
    return make_user(db, "admin", email="admin@example.com", full_name="Site Admin")


@pytest.fixture
def student_client(client, student):
    login(client, student)
    return client


@pytest.fixture
def faculty_client(client, faculty):
    login(client, faculty)
    return client


@pytest.fixture
def admin_client(client, admin):
    login(client, admin)
    return client
