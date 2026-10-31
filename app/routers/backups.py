"""Admin: download a ZIP of CSV exports of the core tables (no secrets, no file blobs)."""
import csv
import io
import zipfile

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Base, get_db, utcnow
from app.deps import require_admin
from app.models import User
from app.services.activity import log_event
from app.templating import render

router = APIRouter(prefix="/admin/backups", tags=["admin"])

TABLES = [
    "users", "categories", "courses", "topics", "questions", "resources", "assessments", "assessment_topics",
    "assessment_questions", "attempts", "attempt_answers", "points_ledger", "badges", "user_badges", "goals",
    "notifications", "announcements", "messages", "calendar_events", "forum_threads", "forum_posts",
    "resource_views", "system_settings", "scrape_jobs",
]
# never export credentials or second-factor secrets
EXCLUDED_COLUMNS = {"users": {"password_hash", "totp_secret", "google_sub"}}


def _export(db: Session, name: str) -> tuple[bytes, int]:
    table = Base.metadata.tables[name]
    cols = [c for c in table.columns if c.name not in EXCLUDED_COLUMNS.get(name, set())]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.name for c in cols])
    n = 0
    for row in db.execute(select(*cols)).yield_per(2000):
        w.writerow(["" if v is None else v for v in row])
        n += 1
    return buf.getvalue().encode("utf-8-sig"), n


@router.get("", name="admin_backups")
def backups_page(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    counts = {t: db.scalar(select(func.count()).select_from(Base.metadata.tables[t])) or 0 for t in TABLES}
    return render(request, "admin/backups.html", {"active": "admin_backups", "counts": counts,
                                                  "excluded": EXCLUDED_COLUMNS})


@router.get("/download")
def download(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    mem = io.BytesIO()
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    manifest = [f"Smart Prep backup {stamp} UTC", "table,rows"]
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for t in TABLES:
            data, n = _export(db, t)
            zf.writestr(f"{t}.csv", data)
            manifest.append(f"{t},{n}")
        manifest.append("Excluded columns: users.password_hash, users.totp_secret, users.google_sub; "
                        "stored_files blobs are not included.")
        zf.writestr("MANIFEST.txt", "\n".join(manifest))
    log_event(db, "backup_download", user.id, "/admin/backups/download")
    return Response(mem.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="smartprep-backup-{stamp}.zip"'})
