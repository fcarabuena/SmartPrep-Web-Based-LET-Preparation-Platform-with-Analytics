"""Scraping and AI tests: HTML fixtures + mocked transports. No live network."""
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.models import Question, Resource, ScrapeJob, Topic
from app.services import ai, scraper
from app.services.curriculum import seed_curriculum
from tests.conftest import post

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def fake_web(monkeypatch):
    """Serve fixtures from https://review.example.org; record requests; no real sleeps or DNS."""
    hits = []
    pages = {
        "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\n"),
        "/mcq": ("text/html; charset=utf-8", (FIX / "mcq_page.html").read_text(encoding="utf-8")),
        "/css": ("text/html", (FIX / "css_page.html").read_text(encoding="utf-8")),
        "/private/secret": ("text/html", "<p>1. hidden</p>"),
        "/file.pdf": ("application/pdf", "%PDF-1.4"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append((request.url.path, request.headers.get("user-agent")))
        if request.url.path == "/moved":
            return httpx.Response(302, headers={"location": "/mcq"})
        ctype, body = pages.get(request.url.path, ("text/html", None))
        if body is None:
            return httpx.Response(404, text="nope")
        return httpx.Response(200, text=body, headers={"content-type": ctype})

    sleeps = []
    monkeypatch.setattr(scraper, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(scraper, "resolver", lambda host: ["127.0.0.1"] if host == "localhost" else ["93.184.216.34"])
    monkeypatch.setattr(scraper, "sleep", lambda s: sleeps.append(s))
    return {"hits": hits, "sleeps": sleeps}


def test_parse_mcq_text_fixture():
    html = (FIX / "mcq_page.html").read_text(encoding="utf-8")
    items = scraper.parse_mcq_text(scraper.html_to_text(html), "https://x")
    assert len(items) == 2
    assert items[0]["stem"].startswith("Which quality of a test") and "same group?" in items[0]["stem"]
    assert items[0]["choice_b"] == "Reliability" and items[0]["correct"] == "B"
    assert items[0]["rationalization"].startswith("Reliability is consistency")
    assert items[1]["correct"] == "B" and items[1]["choice_b"] == "formative assessment"


def test_parse_css_fixture():
    html = (FIX / "css_page.html").read_text(encoding="utf-8")
    items = scraper.parse_css(html, {"question": ".q", "stem": ".stem", "choices": "li", "answer": ".answer",
                                     "rationale": ".why"})
    assert len(items) == 2
    assert items[0]["choice_a"] == "Batas Pambansa Blg. 232" and items[0]["correct"] == "A"
    assert items[1]["correct"] == "B"  # matched by answer text


def test_extract_links():
    html = (FIX / "mcq_page.html").read_text(encoding="utf-8")
    links = scraper.extract_links(html, "https://review.example.org/mcq")
    urls = {l["url"] for l in links}
    assert "https://review.example.org/files/assessment-module.pdf" in urls
    assert "https://www.youtube.com/watch?v=abc123" in urls
    assert "https://review.example.org/review/rubrics-guide" in urls
    assert "https://review.example.org/about" not in urls


def test_ssrf_protection(fake_web):
    with pytest.raises(scraper.ScrapeError):
        scraper.check_url("http://localhost/admin")
    with pytest.raises(scraper.ScrapeError):
        scraper.check_url("file:///etc/passwd")
    assert scraper.check_url("https://review.example.org/mcq")


def test_scrape_job_end_to_end(faculty_client, db, fake_web):
    seed_curriculum(db)
    topic = db.scalar(select(Topic).where(Topic.name == "Principles of Assessment"))
    urls = "https://review.example.org/mcq\nhttps://review.example.org/private/secret\nhttps://review.example.org/file.pdf\nhttps://review.example.org/moved"
    r = post(faculty_client, "/scrape", {"urls": urls, "parser": "mcq_text", "topic_id": topic.id,
                                         "confirm_permission": "true"}, csrf_from="/scrape")
    job = db.scalar(select(ScrapeJob))
    db.refresh(job)
    assert job.status == "done" and job.pages_fetched == 2 and job.items_found == 4
    log = json.loads(job.result)["log"]
    assert any("robots.txt" in line for line in log) and any("non-HTML" in line for line in log)
    # polite: custom UA on every request, robots fetched once, ~1s spacing enforced via sleep
    assert all(ua == scraper.USER_AGENT for _, ua in fake_web["hits"])
    assert [p for p, _ in fake_web["hits"]].count("/robots.txt") == 1
    assert fake_web["sleeps"] and all(0 < s <= 1.0 for s in fake_web["sleeps"])
    assert "Extracted questions" in r.text
    # save: first two questions (edited) + one link
    form = {"topic_id": topic.id, "keep": ["0", "1"], "keep_link": ["0"]}
    result = json.loads(job.result)
    for i, q in enumerate(result["questions"][:2]):
        for k in ("stem", "choice_a", "choice_b", "choice_c", "choice_d", "correct", "rationalization", "source_url"):
            form[f"q{i}_{k}"] = q[k]
        form[f"q{i}_difficulty"] = "easy"
    form["q1_stem"] = "Edited: " + form["q1_stem"]
    link = result["links"][0]
    form.update(l0_url=link["url"], l0_title=link["title"], l0_kind=link["kind"])
    r = post(faculty_client, f"/scrape/{job.id}/save", form, csrf_from=f"/scrape/{job.id}")
    assert "Saved 2 question(s)" in r.text
    qs = db.scalars(select(Question)).all()
    assert len(qs) == 2 and all(q.status == "pending_review" and q.source_type == "scraped" for q in qs)
    assert any(q.stem.startswith("Edited:") for q in qs) and all(q.source_url for q in qs)
    res = db.scalar(select(Resource))
    assert res and not res.approved and res.source_type == "scraped"


def test_scrape_requires_permission_and_blocks_private(faculty_client, db, fake_web):
    seed_curriculum(db)
    topic = db.scalar(select(Topic))
    r = post(faculty_client, "/scrape", {"urls": "https://review.example.org/mcq", "topic_id": topic.id},
             csrf_from="/scrape")
    assert "confirm that you are allowed" in r.text
    r = post(faculty_client, "/scrape", {"urls": "http://localhost/x", "topic_id": topic.id, "confirm_permission": "true"},
             csrf_from="/scrape")
    assert "private or local" in r.text
    assert db.scalar(select(ScrapeJob)) is None


def test_students_cannot_scrape(student_client):
    assert student_client.get("/scrape").status_code == 403


# ---------------------------------------------------------------- AI


class FakeGemini(ai.GeminiClient):
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def generate_json(self, prompt, temperature=0.7):
        self.prompts.append(prompt)
        return self.payload


GOOD = {"stem": "Which assessment method best evaluates a learner's ability to deliver a speech?",
        "choice_a": "Performance task with a rubric", "choice_b": "True-or-false test",
        "choice_c": "Matching type test", "choice_d": "Spelling quiz", "correct": "A",
        "rationalization": "A directly observes the skill; B, C and D only test recall.", "competency": "Authentic assessment"}


def test_ai_hidden_without_key(faculty_client):
    assert faculty_client.get("/ai/generate").status_code == 404
    assert "AI Generator" not in faculty_client.get("/dashboard").text


def test_ai_generation_validates_and_saves_pending(faculty_client, db, monkeypatch):
    seed_curriculum(db)
    bad = dict(GOOD, stem="short")
    dup_choices = dict(GOOD, stem=GOOD["stem"] + " (variant)", choice_b=GOOD["choice_a"])
    fake = FakeGemini([GOOD, bad, dup_choices, "not a dict"])
    monkeypatch.setattr(ai, "get_client", lambda: fake)
    topic = db.scalar(select(Topic).where(Topic.name == "Authentic Assessment and Rubrics"))
    assert faculty_client.get("/ai/generate").status_code == 200
    r = post(faculty_client, "/ai/generate", {"topic_id": topic.id, "difficulty": "medium", "count": 3},
             csrf_from="/ai/generate")
    assert "Generated 1 question(s)" in r.text and "3 were rejected" in r.text
    q = db.scalar(select(Question))
    assert q.status == "pending_review" and q.source_type == "ai_generated" and q.correct == "A"
    assert "Authentic Assessment and Rubrics" in fake.prompts[0] and "JSON" in fake.prompts[0]


def test_ai_parse_json_and_http_client():
    assert ai.parse_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    with pytest.raises(ai.AIError):
        ai.parse_json("not json")

    def handler(request):
        assert request.headers["x-goog-api-key"] == "k" and "key=" not in str(request.url)
        body = {"candidates": [{"content": {"parts": [{"text": json.dumps([GOOD])}]}}]}
        return httpx.Response(200, json=body)

    client = ai.GeminiClient("k", "gemini-test", http=httpx.Client(transport=httpx.MockTransport(handler)))
    items, rejected = ai.generate_questions(client, "Prof Ed › Assessment", "easy", 1)
    assert len(items) == 1 and rejected == 0 and items[0]["difficulty"] == "easy"
    limited = ai.GeminiClient("k", "m", http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))))
    with pytest.raises(ai.AIError, match="rate limit"):
        limited.generate_json("x")


def test_ai_improve_flow(faculty_client, db, monkeypatch):
    from app.services.curriculum import seed_curriculum as sc
    from app.services.seed_content import seed_sample_questions

    sc(db)
    seed_sample_questions(db)
    q = db.scalar(select(Question).where(Question.stem.like("%Pavlov%")))
    improved = {"stem": "In Pavlov's classic study, after repeated pairing with food the bell became which stimulus?",
                "choice_a": q.choice_a, "choice_b": q.choice_b, "choice_c": q.choice_c, "choice_d": q.choice_d,
                "correct": q.correct, "rationalization": "Expanded rationale."}
    monkeypatch.setattr(ai, "get_client", lambda: FakeGemini(improved))
    r = post(faculty_client, f"/questions/{q.id}/improve", csrf_from=f"/questions/{q.id}/edit")
    assert "AI wording suggestion" in r.text
    post(faculty_client, f"/questions/{q.id}/apply-ai", improved, csrf_from=f"/questions/{q.id}/edit")
    db.refresh(q)
    assert q.stem.startswith("In Pavlov's classic study") and q.status == "pending_review"
    # a suggestion that changes the key is discarded
    monkeypatch.setattr(ai, "get_client", lambda: FakeGemini(dict(improved, correct="D" if q.correct != "D" else "A")))
    r = post(faculty_client, f"/questions/{q.id}/improve", csrf_from=f"/questions/{q.id}/edit")
    assert "changed the correct answer" in r.text
