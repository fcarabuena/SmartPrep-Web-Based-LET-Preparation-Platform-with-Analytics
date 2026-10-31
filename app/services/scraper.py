"""Polite web scraping for faculty: robots.txt, custom User-Agent, 1 request/second, 10 s timeout, max 20 pages.

Two parsers:
- "mcq_text": numbered multiple-choice text (1. stem / A. … D. / Answer: B / Explanation: …)
- "css": CSS selectors for question blocks, stem, choices, answer and rationale

Also captures resource links (PDFs, videos, articles) found on the pages.
Everything extracted is only a *preview*; saving always creates pending_review items.
"""
import ipaddress
import json
import re
import socket
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.db import SessionLocal, utcnow
from app.models import ScrapeJob

USER_AGENT = "SmartPrepBot/1.0 (+LET review platform; RSU Cajidiocan; educational use)"
TIMEOUT = 10.0
MAX_PAGES = 20
MAX_BYTES = 2 * 1024 * 1024
REQUEST_DELAY = 1.0  # seconds between requests to the same host

# indirection points (tests replace these; no live network in tests)
resolver: Callable[[str], list[str]] = lambda host: [ai[4][0] for ai in socket.getaddrinfo(host, None)]  # noqa: E731
transport: httpx.BaseTransport | None = None
sleep: Callable[[float], None] = time.sleep


class ScrapeError(Exception):
    pass


def check_url(url: str) -> str:
    """Allow only public http(s) URLs (blocks SSRF to localhost/private networks)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ScrapeError(f"Only http(s) URLs are allowed: {url}")
    try:
        addrs = resolver(parts.hostname)
    except OSError:
        raise ScrapeError(f"Cannot resolve host: {parts.hostname}")
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ScrapeError(f"Refusing to fetch a private or local address: {parts.hostname}")
    return url.strip()


class PoliteFetcher:
    def __init__(self, log: list[str]):
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=False,
                                   transport=transport)
        self.robots: dict[str, RobotFileParser | None] = {}
        self.last_hit: dict[str, float] = {}
        self.log = log

    def close(self):
        self.client.close()

    def _wait(self, host: str) -> None:
        last = self.last_hit.get(host)
        if last is not None:
            delta = time.monotonic() - last
            if delta < REQUEST_DELAY:
                sleep(REQUEST_DELAY - delta)
        self.last_hit[host] = time.monotonic()

    def _get(self, url: str, redirects: int = 3) -> httpx.Response:
        for _ in range(redirects + 1):
            check_url(url)
            self._wait(urlsplit(url).netloc)
            r = self.client.get(url)
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            return r
        raise ScrapeError("Too many redirects")

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self.robots:
            rp = RobotFileParser()
            try:
                r = self._get(base + "/robots.txt")
                if r.status_code >= 400:
                    rp = None  # no robots.txt -> allowed
                else:
                    rp.parse(r.text.splitlines())
            except (httpx.HTTPError, ScrapeError):
                rp = None
            self.robots[base] = rp
        rp = self.robots[base]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def fetch(self, url: str) -> str | None:
        if not self.allowed(url):
            self.log.append(f"Blocked by robots.txt: {url}")
            return None
        r = self._get(url)
        if r.status_code >= 400:
            self.log.append(f"HTTP {r.status_code}: {url}")
            return None
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            self.log.append(f"Skipped non-HTML content ({ctype or 'unknown'}): {url}")
            return None
        if len(r.content) > MAX_BYTES:
            self.log.append(f"Skipped page larger than 2 MB: {url}")
            return None
        self.log.append(f"Fetched: {url}")
        return r.text


# ---------------------------------------------------------------- parsers

CHOICE_RE = re.compile(r"^\s*(?:\(?([A-Da-d])[\.\)]|([A-Da-d])\s*[:\-])\s+(.+)$")
QNUM_RE = re.compile(r"^\s*(\d{1,3})[\.\)]\s+(.+)$")
ANSWER_RE = re.compile(r"^\s*(?:correct\s+answer|answer|ans|key|sagot)\s*[:\-]\s*\(?([A-Da-d])\b", re.I)
RATIONALE_RE = re.compile(r"^\s*(?:explanation|rationale|rationalization|reason|paliwanag)\s*[:\-]\s*(.+)$", re.I)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text("\n")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def parse_mcq_text(text: str, source_url: str = "") -> list[dict]:
    items: list[dict] = []
    cur: dict | None = None
    last_field = None

    def finish():
        if cur and cur.get("stem") and all(cur.get(f"choice_{k}") for k in "abcd"):
            items.append(cur)

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m_ans, m_rat = ANSWER_RE.match(line), RATIONALE_RE.match(line)
        m_choice, m_q = CHOICE_RE.match(line), QNUM_RE.match(line)
        if m_ans and cur:
            cur["correct"] = m_ans.group(1).upper()
            last_field = None
        elif m_rat and cur:
            cur["rationalization"] = m_rat.group(1).strip()
            last_field = "rationalization"
        elif m_choice and cur and cur.get("stem"):
            letter = (m_choice.group(1) or m_choice.group(2)).lower()
            cur[f"choice_{letter}"] = m_choice.group(3).strip()
            last_field = f"choice_{letter}"
        elif m_q:
            finish()
            cur = {"stem": m_q.group(2).strip(), "correct": "", "rationalization": "", "source_url": source_url}
            last_field = "stem"
        elif cur and last_field in ("stem", "rationalization"):
            cur[last_field] = (cur[last_field] + " " + line).strip()
    finish()
    return items


def _letter_from(answer_text: str, choices: list[str]) -> str:
    t = answer_text.strip()
    m = re.search(r"\b([A-Da-d])\b", t)
    if m and len(t) <= 20:
        return m.group(1).upper()
    for i, c in enumerate(choices):
        if c and c.lower() in t.lower():
            return "ABCD"[i]
    return ""


def parse_css(html: str, sel: dict, source_url: str = "") -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for block in soup.select(sel.get("question") or "body")[:500]:
        stem_el = block.select_one(sel["stem"]) if sel.get("stem") else None
        choices = [c.get_text(" ", strip=True) for c in block.select(sel.get("choices") or "li")][:4]
        choices = [re.sub(r"^\(?[A-Da-d][\.\)]\s*", "", c) for c in choices]
        if not stem_el or len(choices) < 4:
            continue
        ans_el = block.select_one(sel["answer"]) if sel.get("answer") else None
        rat_el = block.select_one(sel["rationale"]) if sel.get("rationale") else None
        out.append({
            "stem": stem_el.get_text(" ", strip=True), "choice_a": choices[0], "choice_b": choices[1],
            "choice_c": choices[2], "choice_d": choices[3],
            "correct": _letter_from(ans_el.get_text(" ", strip=True), choices) if ans_el else "",
            "rationalization": rat_el.get_text(" ", strip=True) if rat_el else "", "source_url": source_url,
        })
    return out


VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")


def extract_links(html: str, base_url: str, limit: int = 30) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    seen, links = set(), []
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"]).split("#")[0]
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        host = urlsplit(url).netloc.lower()
        title = a.get_text(" ", strip=True)[:200]
        if url.lower().endswith(".pdf"):
            kind = "file_link"
        elif any(h in host for h in VIDEO_HOSTS):
            kind = "video"
        elif len(title) >= 12 and re.search(r"(lesson|review|guide|notes|module|article|tutorial|lecture)", title, re.I):
            kind = "article"
        else:
            continue
        seen.add(url)
        links.append({"title": title or url, "url": url, "kind": "link" if kind == "file_link" else kind})
        if len(links) >= limit:
            break
    return links


# ---------------------------------------------------------------- job runner

def parse_urls(raw: str) -> list[str]:
    urls = [u.strip() for u in re.split(r"[\s,]+", raw or "") if u.strip()]
    return list(dict.fromkeys(urls))[:MAX_PAGES]


def run_job(job_id: int) -> None:
    """Runs inside the web process (FastAPI BackgroundTasks). Uses its own DB session."""
    db = SessionLocal()
    job = db.get(ScrapeJob, job_id)
    if job is None:
        db.close()
        return
    job.status = "running"
    db.commit()
    log: list[str] = []
    questions: list[dict] = []
    links: list[dict] = []
    fetcher = PoliteFetcher(log)
    try:
        config = json.loads(job.config or "{}")
        for url in parse_urls(job.urls):
            try:
                html = fetcher.fetch(check_url(url))
            except (ScrapeError, httpx.HTTPError) as exc:
                log.append(f"Error: {url}: {exc.__class__.__name__}: {exc}"[:300])
                continue
            if html is None:
                continue
            job.pages_fetched += 1
            if job.parser == "css":
                questions += parse_css(html, config, url)
            else:
                questions += parse_mcq_text(html_to_text(html), url)
            links += extract_links(html, url)
        job.items_found = len(questions)
        job.result = json.dumps({"questions": questions, "links": links, "log": log})
        job.status = "done"
    except Exception as exc:  # pragma: no cover - defensive
        job.status = "failed"
        job.error = f"{exc.__class__.__name__}: {exc}"[:2000]
        job.result = json.dumps({"questions": questions, "links": links, "log": log})
    finally:
        fetcher.close()
        job.finished_at = utcnow()
        db.commit()
        db.close()
