"""Smart Prep FastAPI application."""
import logging
import traceback
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.deps import LoginRequired, csrf_protect
from app.middleware import AppMiddleware
from app.routers import ROUTERS
from app.services.activity import log_error
from app.sessions import SessionMiddleware
from app.templating import render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title=settings.APP_NAME,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
    dependencies=[Depends(csrf_protect)],
)

# Order matters: the last added middleware is the outermost (sessions must wrap AppMiddleware).
app.add_middleware(AppMiddleware)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, https_only=settings.is_production)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

for router in ROUTERS:
    app.include_router(router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Liveness probe for Render. Does not touch the database."""
    return PlainTextResponse("ok")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse("/static/img/logo.svg", status_code=301)


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", "")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    if _wants_json(request):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(nxt)}", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if _wants_json(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    template = {403: "errors/403.html", 404: "errors/404.html"}.get(exc.status_code, "errors/error.html")
    detail = exc.detail if isinstance(exc.detail, str) else ""
    if exc.status_code == 404 and detail == "Not Found":
        detail = ""
    return render(request, template, {"status": exc.status_code, "detail": detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def server_error_handler(request: Request, exc: Exception):
    uid = request.session.get("uid") if "session" in request.scope else None
    logging.getLogger("smartprep").error("Unhandled error on %s %s: %r", request.method, request.url.path, exc)
    log_error(request.method, request.url.path, "".join(traceback.format_exception(exc))[-4000:], uid)
    try:
        return render(request, "errors/500.html", {"status": 500}, status_code=500)
    except Exception:
        return PlainTextResponse("Internal Server Error", status_code=500)
