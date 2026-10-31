"""Optional Google Gemini question generation (free API key). Hidden when GEMINI_API_KEY is not set.

The model must return strict JSON; every item is validated and saved as pending_review / ai_generated.
"""
import json
import re

import httpx

from app.config import settings
from app.services.content import validate_question

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class AIError(Exception):
    pass


class GeminiClient:
    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None):
        self.api_key = api_key
        self.model = model
        self.http = http or httpx.Client(timeout=60)

    def generate_json(self, prompt: str, temperature: float = 0.7):
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature},
        }
        try:
            r = self.http.post(API.format(model=self.model), json=body,
                               headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise AIError(f"Could not reach Gemini: {exc.__class__.__name__}")
        if r.status_code == 429:
            raise AIError("Gemini free-tier rate limit reached. Please wait a minute and try again.")
        if r.status_code >= 400:
            raise AIError(f"Gemini returned HTTP {r.status_code}.")
        try:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError):
            raise AIError("Unexpected response from Gemini.")
        return parse_json(text)


def parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        raise AIError("Gemini did not return valid JSON.")


def get_client() -> GeminiClient | None:
    if not settings.gemini_enabled:
        return None
    return GeminiClient(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)


SCHEMA_HINT = (
    'Return ONLY a JSON array. Each item: {"stem": str, "choice_a": str, "choice_b": str, "choice_c": str, '
    '"choice_d": str, "correct": "A"|"B"|"C"|"D", "rationalization": str (why the key is right AND why each other '
    'option is wrong), "competency": str}.'
)


def _normalize(item: dict) -> dict:
    if isinstance(item.get("choices"), dict):
        for k in "abcd":
            item.setdefault(f"choice_{k}", item["choices"].get(k.upper()) or item["choices"].get(k))
    if isinstance(item.get("choices"), list) and len(item["choices"]) == 4:
        for k, v in zip("abcd", item["choices"]):
            item.setdefault(f"choice_{k}", v)
    out = {k: str(item.get(k) or "").strip() for k in ("stem", "choice_a", "choice_b", "choice_c", "choice_d",
                                                       "rationalization", "competency")}
    out["correct"] = str(item.get("correct") or item.get("answer") or "").strip().upper()[:1]
    return out


def generate_questions(client: GeminiClient, topic_path: str, difficulty: str, n: int) -> tuple[list[dict], int]:
    """Returns (valid items, number rejected by validation)."""
    n = max(1, min(n, 20))
    prompt = (
        "You are writing ORIGINAL practice items for the Philippine Licensure Examination for Teachers (LET). "
        f"Topic: {topic_path}. Difficulty: {difficulty}. Write {n} four-option multiple-choice questions with exactly "
        "one best answer. Do not copy items from published reviewers or past board exams. Use clear, accurate content "
        "aligned with Philippine teacher education. " + SCHEMA_HINT
    )
    data = client.generate_json(prompt)
    if isinstance(data, dict):
        data = data.get("questions") or data.get("items") or []
    if not isinstance(data, list):
        raise AIError("Gemini response was not a list of questions.")
    valid, rejected = [], 0
    for raw in data[: n * 2]:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        item = _normalize(raw)
        item["difficulty"] = difficulty if difficulty in ("easy", "medium", "hard") else "medium"
        if validate_question(item) or not item["rationalization"]:
            rejected += 1
            continue
        valid.append(item)
        if len(valid) >= n:
            break
    return valid, rejected


def improve_question(client: GeminiClient, q: dict) -> dict:
    prompt = (
        "Improve the wording of this LET multiple-choice question for clarity and grammar without changing what it "
        "tests or which option is correct. Make distractors plausible and parallel. Expand the rationalization so it "
        "explains why the key is right and why each other option is wrong. "
        + SCHEMA_HINT.replace("ONLY a JSON array. Each item", "ONLY one JSON object")
        + "\nQuestion: " + json.dumps({k: q[k] for k in ("stem", "choice_a", "choice_b", "choice_c", "choice_d",
                                                        "correct", "rationalization")})
    )
    data = client.generate_json(prompt, temperature=0.3)
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        raise AIError("Gemini did not return a question object.")
    item = _normalize(data)
    if validate_question(item):
        raise AIError("The improved question did not pass validation.")
    if item["correct"] != q["correct"]:
        raise AIError("The suggestion changed the correct answer, so it was discarded.")
    return item
