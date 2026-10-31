"""Render every parameterless GET page for each role; nothing may raise or return 5xx."""
import pytest

from app.main import app
from app.routing_util import iter_api_routes
from app.services.curriculum import seed_curriculum
from app.services.seed_content import seed_badges, seed_sample_questions
from tests.conftest import login, make_user

SKIP = {"/logout", "/auth/google", "/auth/google/callback", "/verify", "/reset", "/healthz", "/favicon.ico",
        "/2fa/setup", "/2fa/verify",
        "/ai/generate"}  # 404 by design when GEMINI_API_KEY is not set (covered in test_scrape_ai)


def _get_routes():
    paths = [p for p, r in iter_api_routes(app.routes) if "GET" in r.methods and "{" not in p and p not in SKIP]
    assert len(paths) > 40
    return paths


@pytest.mark.parametrize("role", ["student", "faculty", "admin"])
def test_all_pages_render(client, db, role):
    seed_curriculum(db)
    seed_sample_questions(db)
    seed_badges(db)
    login(client, make_user(db, role))
    for path in _get_routes():
        r = client.get(path, follow_redirects=False)
        assert r.status_code < 500, (path, r.status_code)
        assert r.status_code in (200, 303, 307, 403), (path, r.status_code)


def test_detail_pages_render(client, db):
    from sqlalchemy import select

    from app.models import Question, Resource

    seed_curriculum(db)
    seed_sample_questions(db)
    login(client, make_user(db, "faculty"))
    q = db.scalar(select(Question))
    r = db.scalar(select(Resource))
    for path in (f"/questions/{q.id}", f"/questions/{q.id}/edit", f"/resources/{r.id}/edit", "/questions/new",
                 "/resources/new"):
        assert client.get(path).status_code == 200, path
