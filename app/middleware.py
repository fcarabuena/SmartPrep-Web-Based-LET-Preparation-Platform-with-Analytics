"""Security headers, request counters and page-view logging."""
import threading
import time
from collections import Counter

from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.services.activity import log_page_view

CDN = "https://cdn.jsdelivr.net"
CSP = "; ".join(
    [
        "default-src 'self'",
        f"script-src 'self' {CDN}",
        f"style-src 'self' 'unsafe-inline' {CDN}",
        f"font-src 'self' data: {CDN}",
        "img-src 'self' data: https:",
        f"connect-src 'self' {CDN}",
        "frame-src https://www.youtube-nocookie.com https://www.youtube.com",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ]
)

SKIP_LOG_PREFIXES = ("/static", "/healthz", "/favicon", "/api/")

_counter_lock = threading.Lock()
REQUEST_STATS: Counter = Counter()
STARTED_AT = time.time()


class AppMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)

        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if "content-security-policy" not in h:
            h["Content-Security-Policy"] = CSP
        if settings.is_production:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        ctype = h.get("content-type", "")
        if ctype.startswith("text/html"):
            h["Cache-Control"] = "no-store"

        path = request.url.path
        with _counter_lock:
            REQUEST_STATS["total"] += 1
            REQUEST_STATS[f"{response.status_code // 100}xx"] += 1

        if (
            request.method == "GET"
            and ctype.startswith("text/html")
            and response.status_code < 400
            and not path.startswith(SKIP_LOG_PREFIXES)
        ):
            uid = request.session.get("uid") if "session" in request.scope else None
            if uid:
                response.background = BackgroundTask(log_page_view, uid, path, response.status_code, duration_ms)
        return response
