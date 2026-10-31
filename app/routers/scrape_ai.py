"""Faculty: web scraping jobs (preview/edit then save as pending_review) and optional Gemini generation."""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import require_staff
from app.models import Question, Resource, ScrapeJob, Topic, User
from app.services import ai, scraper
from app.services.content import apply_question, stem_hash, topic_options, topic_path, validate_question
from app.templating import flash, render

router = APIRouter(tags=["scraping-ai"])


# ---------------------------------------------------------------- scraping

@router.get("/scrape", name="scrape_jobs")
def jobs(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    items = db.scalars(select(ScrapeJob).order_by(ScrapeJob.created_at.desc()).limit(30)).all()
    return render(request, "scrape/jobs.html", {"active": "scrape_jobs", "items": items, "topic_groups": topic_options(db),
                                                "max_pages": scraper.MAX_PAGES})


@router.post("/scrape")
def create_job(request: Request, background: BackgroundTasks, urls: str = Form(""), parser: str = Form("mcq_text"),
               topic_id: int = Form(0), sel_question: str = Form(""), sel_stem: str = Form(""),
               sel_choices: str = Form(""), sel_answer: str = Form(""), sel_rationale: str = Form(""),
               confirm_permission: bool = Form(False), user: User = Depends(require_staff),
               db: Session = Depends(get_db)):
    url_list = scraper.parse_urls(urls)
    errors = []
    if not url_list:
        errors.append("Enter at least one URL.")
    if not confirm_permission:
        errors.append("Please confirm that you are allowed to scrape these sources.")
    for u in url_list:
        try:
            scraper.check_url(u)
        except scraper.ScrapeError as exc:
            errors.append(str(exc))
    if parser not in ("mcq_text", "css"):
        errors.append("Unknown parser.")
    if parser == "css" and not (sel_question and sel_stem and sel_choices):
        errors.append("The CSS parser needs at least question, stem and choices selectors.")
    if not topic_id or not db.get(Topic, topic_id):
        errors.append("Choose the target topic for extracted questions.")
    if errors:
        for e in errors:
            flash(request, e, "danger")
        return RedirectResponse("/scrape", status_code=303)
    config = {"question": sel_question.strip(), "stem": sel_stem.strip(), "choices": sel_choices.strip(),
              "answer": sel_answer.strip(), "rationale": sel_rationale.strip()} if parser == "css" else {}
    job = ScrapeJob(created_by_id=user.id, urls="\n".join(url_list), parser=parser, topic_id=topic_id,
                    config=json.dumps(config), status="queued")
    db.add(job)
    db.commit()
    background.add_task(scraper.run_job, job.id)
    flash(request, f"Scrape job started for {len(url_list)} URL(s). This page refreshes until it finishes.", "info")
    return RedirectResponse(f"/scrape/{job.id}", status_code=303)


def _job(db: Session, jid: int) -> ScrapeJob:
    job = db.get(ScrapeJob, jid)
    if not job:
        raise HTTPException(404, "Scrape job not found")
    return job


@router.get("/scrape/{jid:int}")
def job_detail(request: Request, jid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    job = _job(db, jid)
    result = json.loads(job.result or "{}")
    for q in result.get("questions", []):
        q["_errors"] = validate_question(q)
        q["_duplicate"] = bool(q.get("stem")) and bool(db.scalar(select(Question.id).where(Question.stem_hash == stem_hash(q["stem"]))))
    return render(request, "scrape/job.html", {
        "active": "scrape_jobs", "job": job, "result": result, "topic": db.get(Topic, job.topic_id) if job.topic_id else None,
        "topic_groups": topic_options(db),
    })


@router.post("/scrape/{jid:int}/save")
async def save_job(request: Request, jid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    job = _job(db, jid)
    f = await request.form()
    topic_id = int(f.get("topic_id") or job.topic_id or 0)
    if not db.get(Topic, topic_id):
        flash(request, "Choose a valid topic.", "danger")
        return RedirectResponse(f"/scrape/{jid}", status_code=303)
    saved = skipped = 0
    for i in [int(x) for x in f.getlist("keep") if str(x).isdigit()]:
        data = {k: str(f.get(f"q{i}_{k}", "")) for k in ("stem", "choice_a", "choice_b", "choice_c", "choice_d",
                                                         "correct", "rationalization", "difficulty", "source_url")}
        data["correct"] = data["correct"].upper()
        data["difficulty"] = data["difficulty"] if data["difficulty"] in ("easy", "medium", "hard") else "medium"
        if validate_question(data) or db.scalar(select(Question.id).where(Question.stem_hash == stem_hash(data["stem"]))):
            skipped += 1
            continue
        # scraped items ALWAYS go to pending_review
        q = apply_question(Question(topic_id=topic_id, source_type="scraped", status="pending_review",
                                    created_by_id=user.id), data)
        db.add(q)
        db.flush()
        saved += 1
    links = 0
    for i in [int(x) for x in f.getlist("keep_link") if str(x).isdigit()]:
        url, title = str(f.get(f"l{i}_url", "")), str(f.get(f"l{i}_title", "")).strip()[:255]
        kind = str(f.get(f"l{i}_kind", "link"))
        if not url.startswith(("http://", "https://")) or db.scalar(select(Resource.id).where(Resource.url == url)):
            continue
        db.add(Resource(title=title or url[:255], kind=kind if kind in ("video", "article", "link") else "link", url=url,
                        topic_id=topic_id, level="standard", approved=False, source_type="scraped",
                        created_by_id=user.id, description=f"Captured by scrape job #{job.id}"))
        links += 1
    job.status = "saved"
    db.commit()
    flash(request, f"Saved {saved} question(s) to the review queue and {links} resource link(s) (hidden until approved)."
          + (f" Skipped {skipped} invalid or duplicate item(s)." if skipped else ""))
    return RedirectResponse("/questions/review?source=scraped", status_code=303)


# ---------------------------------------------------------------- Gemini (optional)

def _require_ai():
    client = ai.get_client()
    if client is None:
        raise HTTPException(404, "AI generation is not configured.")
    return client


@router.get("/ai/generate", name="ai_generate")
def ai_page(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    _require_ai()
    return render(request, "scrape/ai.html", {"active": "ai_generate", "topic_groups": topic_options(db)})


@router.post("/ai/generate")
def ai_generate(request: Request, topic_id: int = Form(0), difficulty: str = Form("medium"), count: int = Form(5),
                user: User = Depends(require_staff), db: Session = Depends(get_db)):
    client = _require_ai()
    topic = db.get(Topic, topic_id)
    if not topic:
        flash(request, "Choose a topic.", "danger")
        return RedirectResponse("/ai/generate", status_code=303)
    try:
        items, rejected = ai.generate_questions(client, topic_path(topic), difficulty, count)
    except ai.AIError as exc:
        flash(request, str(exc), "danger")
        return RedirectResponse("/ai/generate", status_code=303)
    saved = 0
    for item in items:
        if db.scalar(select(Question.id).where(Question.stem_hash == stem_hash(item["stem"]))):
            rejected += 1
            continue
        db.add(apply_question(Question(topic_id=topic.id, source_type="ai_generated", status="pending_review",
                                       created_by_id=user.id), item))
        saved += 1
    db.commit()
    flash(request, f"Generated {saved} question(s) for review." + (f" {rejected} were rejected by validation." if rejected else ""))
    return RedirectResponse("/questions/review?source=ai_generated", status_code=303)


@router.post("/questions/{qid:int}/improve")
def ai_improve(request: Request, qid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    client = _require_ai()
    q = db.get(Question, qid)
    if not q:
        raise HTTPException(404, "Question not found")
    original = {k: getattr(q, k) for k in ("stem", "choice_a", "choice_b", "choice_c", "choice_d", "correct",
                                            "rationalization")}
    try:
        suggestion = ai.improve_question(client, original)
    except ai.AIError as exc:
        flash(request, str(exc), "danger")
        return RedirectResponse(f"/questions/{qid}/edit", status_code=303)
    return render(request, "scrape/improve.html", {"active": "question_bank", "q": q, "original": original,
                                                   "s": suggestion})


@router.post("/questions/{qid:int}/apply-ai")
async def ai_apply(request: Request, qid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    _require_ai()
    q = db.get(Question, qid)
    if not q:
        raise HTTPException(404, "Question not found")
    f = await request.form()
    data = {k: str(f.get(k, "")) for k in ("stem", "choice_a", "choice_b", "choice_c", "choice_d", "correct",
                                           "rationalization")}
    data.update(difficulty=q.difficulty, competency=q.competency or "", source_url=q.source_url or "")
    errors = validate_question(data)
    if errors:
        flash(request, " ".join(errors), "danger")
        return RedirectResponse(f"/questions/{qid}/edit", status_code=303)
    apply_question(q, data)
    q.status = "pending_review"  # AI-edited text always gets a human review
    q.review_note = f"Wording improved with AI by {user.full_name} on {utcnow():%Y-%m-%d}"
    db.commit()
    flash(request, "AI suggestion applied. The question is back in the review queue.")
    return RedirectResponse("/questions/review", status_code=303)
