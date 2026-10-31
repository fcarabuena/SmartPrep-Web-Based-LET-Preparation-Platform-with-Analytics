"""Phase 8 hardening: permission matrix for every route, security headers, errors, backups, query budget."""
import io
import re
import zipfile

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.db import engine
from app.main import app
from app.routing_util import iter_api_routes
from app.models import ErrorLog
from app.services.curriculum import seed_curriculum
from app.services.seed_content import seed_badges, seed_sample_questions
from tests.conftest import get_csrf, login, make_user

PUBLIC = {"/", "/login", "/logout", "/register", "/verify", "/resend-verification", "/forgot", "/reset",
          "/2fa/setup", "/2fa/verify", "/auth/google", "/auth/google/callback", "/healthz", "/favicon.ico",
          "/account/change-password"}  # signed-in users with a temporary password; redirects others itself


def required_roles(route: APIRoute) -> set[str] | None:
    """Roles from the require_role(...) dependency of a route (None if the route has none)."""
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        call = dep.call
        if getattr(call, "__qualname__", "").startswith("require_role.<locals>.checker"):
            cells = dict(zip(call.__code__.co_freevars, (c.cell_contents for c in call.__closure__ or ())))
            return set(cells["roles"])
        stack.extend(dep.dependencies)
    return None


def all_routes():
    out = []
    for path, r in iter_api_routes(app.routes):
        for m in sorted(r.methods - {"HEAD"}):
            out.append((m, path, r))
    assert len(out) > 150, "route walker found too few routes"
    return out


def test_every_non_public_route_requires_a_role():
    missing = [f"{m} {p}" for m, p, r in all_routes() if p not in PUBLIC and required_roles(r) is None]
    assert not missing, f"Routes without require_role: {missing}"


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "999999", path)


@pytest.mark.parametrize("role", [None, "student", "faculty", "admin"])
def test_permission_matrix(client, db, role):
    seed_curriculum(db)
    if role:
        login(client, make_user(db, role))
    token = get_csrf(client, "/dashboard" if role else "/login")
    problems = []
    for method, path, route in all_routes():
        if path in PUBLIC:
            continue
        allowed = required_roles(route) | {"admin"}
        url = _fill(path)
        if method == "GET":
            r = client.get(url, follow_redirects=False)
        else:
            r = client.request(method, url, headers={"X-CSRF-Token": token}, follow_redirects=False)
        code = r.status_code
        if role is None:
            ok = code in (303, 401)
        elif role not in allowed:
            ok = code == 403
        else:
            ok = code != 403 or method != "GET"  # allowed GETs must not be forbidden
        if not ok:
            problems.append(f"{role or 'anonymous'} {method} {path} -> {code} (allowed: {sorted(allowed)})")
    assert not problems, "\n".join(problems)


def test_security_headers_everywhere(student_client, monkeypatch):
    from app.config import settings

    for url in ("/dashboard", "/quizzes", "/static/css/app.css", "/healthz"):
        r = student_client.get(url)
        assert r.headers["X-Frame-Options"] == "DENY", url
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"], url
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    html = student_client.get("/dashboard")
    assert html.headers["Cache-Control"] == "no-store"
    assert "unsafe-inline" not in html.headers["Content-Security-Policy"].split("script-src")[1].split(";")[0]
    monkeypatch.setattr(settings, "ENV", "production")
    assert "max-age=31536000" in student_client.get("/healthz").headers["Strict-Transport-Security"]


def test_no_inline_scripts_in_templates():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    offenders = []
    for f in root.rglob("*.html"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>", text):
            offenders.append(f"{f.name}: {m.group(0)}")
        if re.search(r"\son(click|change|submit|load)=", text):
            offenders.append(f"{f.name}: inline event handler")
    assert not offenders, offenders


def test_server_error_page_and_log(db, monkeypatch):
    import app.routers.dashboard as dash

    user = make_user(db, "student")

    def boom(*a, **k):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(dash, "readiness", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        login(c, user)
        r = c.get("/dashboard")
    assert r.status_code == 500 and "Something went wrong" in r.text and "simulated failure" not in r.text
    err = db.scalar(select(ErrorLog))
    assert err and "simulated failure" in err.error and err.path == "/dashboard"


def test_403_and_404_pages(student_client):
    r = student_client.get("/admin/users")
    assert r.status_code == 403 and "Access denied" in r.text
    r = student_client.get("/questions/123")
    assert r.status_code == 403


def test_backup_zip_excludes_secrets(admin_client, db):
    seed_curriculum(db)
    page = admin_client.get("/admin/backups")
    assert "Download ZIP" in page.text
    r = admin_client.get("/admin/backups/download")
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert {"users.csv", "questions.csv", "attempts.csv", "MANIFEST.txt"} <= names
    users_csv = zf.read("users.csv").decode("utf-8-sig")
    header = users_csv.splitlines()[0]
    assert "password_hash" not in header and "totp_secret" not in header and "email" in header
    assert "$argon2" not in users_csv
    assert "topics,64" in zf.read("MANIFEST.txt").decode()


def test_query_budget_for_busy_pages(db, client_factory):
    """Guards against N+1 regressions on the busiest pages."""
    from tests.test_assessments import make_assessment
    from tests.test_gamification import _take

    seed_curriculum(db)
    seed_sample_questions(db)
    seed_badges(db)
    student = make_user(db, "student", major="math")
    for i in range(12):
        a = make_assessment(db, title=f"Quiz {i}", question_count=5)
        if i < 6:
            _take(db, student, a, i % 6)
    sc = client_factory(student)
    counter = {"n": 0}

    def count(*_):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        budgets = {"/quizzes": 40, "/examinations": 40, "/dashboard": 90, "/progress": 60, "/grades": 40,
                   "/gamification": 60, "/study-plan": 60}
        over = {}
        for url, budget in budgets.items():
            counter["n"] = 0
            assert sc.get(url).status_code == 200
            if counter["n"] > budget:
                over[url] = counter["n"]
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert not over, f"query budget exceeded: {over}"


def test_sidebar_shows_role_menus(db, client_factory):
    seed_curriculum(db)
    expected = {
        "student": ["Examinations", "Quizzes", "Learning Materials", "Grades", "Gamification", "Progress",
                    "Study Plan", "Goals", "Calendar", "Inbox", "Forum"],
        "faculty": ["Question Bank", "Review Queue", "Assessments", "Submissions", "Class Analytics",
                    "At-Risk Students", "Item Analysis", "Web Scraping", "Announcements"],
        "admin": ["Users", "System Analytics", "Settings", "System Health", "Backups", "Question Bank"],
    }
    for role, labels in expected.items():
        html = client_factory(role=role).get("/dashboard").text
        nav = html.split('class="sidebar-nav"')[1].split("</nav>")[0]
        missing = [label for label in labels if f"<span>{label}</span>" not in nav]
        assert not missing, (role, missing)
    student_nav = client_factory(role="student").get("/dashboard").text.split('class="sidebar-nav"')[1]
    assert "Question Bank" not in student_nav.split("</nav>")[0]


def test_seed_demo_script(db, monkeypatch, capsys):
    import importlib.util
    import sys
    from pathlib import Path

    from sqlalchemy import func

    from app.models import Attempt, ForumThread, Message, PointsLedger, Question, User, UserBadge

    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["seed_demo.py", "--students", "6", "--seed", "7"])
    mod.main()
    out = capsys.readouterr().out
    assert "Done in" in out and "student06@smartprep.demo" in out
    count = lambda m, *w: db.scalar(select(func.count()).select_from(m).where(*w))  # noqa: E731
    assert count(Question, Question.status == "approved") >= 300
    assert count(User, User.role == "student") == 6 and count(User, User.role == "faculty") == 3
    assert count(Attempt) > 30 and count(PointsLedger) > 0 and count(UserBadge) > 0
    assert count(Attempt, Attempt.attempt_no == 3, Attempt.kind == "mock_exam") > 0  # Exam 3 exists
    assert count(ForumThread) == 6 and count(Message) > 0
    # running again without --wipe does not duplicate activity
    monkeypatch.setattr(sys, "argv", ["seed_demo.py", "--students", "6"])
    before = count(Attempt)
    mod.main()
    assert count(Attempt) == before
