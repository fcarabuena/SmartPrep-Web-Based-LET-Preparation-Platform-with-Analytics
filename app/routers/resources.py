"""Learning resources: staff management, student materials browser, view tracking, DB-stored files."""
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload, undefer

from app.db import get_db
from app.deps import require_any, require_staff
from app.models import Category, Course, Resource, ResourceView, StoredFile, Topic, User
from app.models.content import RESOURCE_KINDS, RESOURCE_LEVELS
from app.services.content import nav_categories, read_upload, store_file, topic_options, visible_course_filter
from app.templating import flash, render

router = APIRouter(tags=["resources"])
PAGE_SIZE = 24


def _opts():
    return selectinload(Resource.topic).selectinload(Topic.course).selectinload(Course.category)


def _search(stmt, q: str, category: int, course: int, topic: int, kind: str, level: str):
    stmt = stmt.outerjoin(Topic, Resource.topic_id == Topic.id).outerjoin(Course, Topic.course_id == Course.id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Resource.title).like(like), func.lower(Resource.description).like(like),
                              func.lower(Topic.name).like(like), func.lower(Course.name).like(like)))
    if category:
        stmt = stmt.where(Course.category_id == category)
    if course:
        stmt = stmt.where(Topic.course_id == course)
    if topic:
        stmt = stmt.where(Resource.topic_id == topic)
    if kind in RESOURCE_KINDS:
        stmt = stmt.where(Resource.kind == kind)
    if level in RESOURCE_LEVELS:
        stmt = stmt.where(Resource.level == level)
    return stmt


# ---------------------------------------------------------------- staff management

@router.get("/resources", name="resources_admin")
def manage(request: Request, q: str = "", category: int = 0, course: int = 0, topic: int = 0, kind: str = "",
           level: str = "", approved: str = "", page: int = 1,
           user: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = _search(select(Resource), q, category, course, topic, kind, level)
    if approved in ("yes", "no"):
        stmt = stmt.where(Resource.approved.is_(approved == "yes"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page = max(page, 1)
    items = db.scalars(stmt.options(_opts()).order_by(Resource.created_at.desc())
                       .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    filters = {"q": q, "category": category, "course": course, "topic": topic, "kind": kind, "level": level,
               "approved": approved}
    return render(request, "resources/manage.html", {
        "active": "resources_admin", "items": items, "total": total, "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)), "filters": filters,
        "qs": "&".join(f"{k}={v}" for k, v in filters.items() if v),
        "categories": db.scalars(select(Category).order_by(Category.sort_order)).all(),
        "topic_groups": topic_options(db), "kinds": RESOURCE_KINDS, "levels": RESOURCE_LEVELS,
    })


def _form_ctx(db, form, resource=None, errors=None):
    return {"active": "resources_admin", "form": form, "resource": resource, "errors": errors or [],
            "topic_groups": topic_options(db), "kinds": RESOURCE_KINDS, "levels": RESOURCE_LEVELS}


@router.get("/resources/new")
def new_resource(request: Request, topic: int = 0, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return render(request, "resources/form.html", _form_ctx(db, {"kind": "video", "level": "standard",
                                                                  "topic_id": topic, "approved": True}))


async def _save(request: Request, db: Session, user: User, resource: Resource | None, title: str, kind: str, url: str,
                topic_id: int, level: str, description: str, approved: bool, upload: UploadFile | None):
    form = {"title": title.strip(), "kind": kind, "url": url.strip(), "topic_id": topic_id, "level": level,
            "description": description.strip(), "approved": approved}
    errors = []
    if not (3 <= len(form["title"]) <= 255):
        errors.append("Title must be 3–255 characters.")
    if kind not in RESOURCE_KINDS:
        errors.append("Invalid resource type.")
    if level not in RESOURCE_LEVELS:
        errors.append("Invalid level.")
    if topic_id and not db.get(Topic, topic_id):
        errors.append("Unknown topic.")
    has_upload = upload is not None and bool(upload.filename)
    data = None
    if has_upload:
        data, err = await read_upload(upload)
        if err:
            errors.append(err)
    if form["url"] and not re.match(r"^https?://", form["url"]):
        errors.append("URL must start with http:// or https://")
    if kind == "file" and not has_upload and not (resource and resource.file_id):
        errors.append("Choose a file to upload (max 5 MB).")
    if kind != "file" and not form["url"]:
        errors.append("A URL is required for videos, articles and links.")
    if errors:
        return None, render(request, "resources/form.html", _form_ctx(db, form, resource, errors), status_code=400)
    r = resource or Resource(created_by_id=user.id, source_type="manual")
    r.title, r.kind, r.url, r.level = form["title"], kind, form["url"] or None, level
    r.topic_id = topic_id or None
    r.description = form["description"] or None
    r.approved = approved
    if data is not None:
        old_file_id = r.file_id
        r.file_id = store_file(db, upload.filename, data, user.id).id
        if old_file_id:
            old = db.get(StoredFile, old_file_id)
            if old:
                db.delete(old)
    if resource is None:
        db.add(r)
    db.commit()
    return r, None


@router.post("/resources/new")
async def create_resource(request: Request, title: str = Form(""), kind: str = Form("link"), url: str = Form(""),
                          topic_id: int = Form(0), level: str = Form("standard"), description: str = Form(""),
                          approved: bool = Form(False), file: UploadFile | None = File(None),
                          user: User = Depends(require_staff), db: Session = Depends(get_db)):
    r, error_response = await _save(request, db, user, None, title, kind, url, topic_id, level, description, approved, file)
    if error_response:
        return error_response
    _after_publish(db, r)
    flash(request, "Resource added.")
    return RedirectResponse("/resources", status_code=303)


def _get(db: Session, rid: int) -> Resource:
    r = db.scalar(select(Resource).where(Resource.id == rid).options(_opts(), selectinload(Resource.file)))
    if not r:
        raise HTTPException(404, "Resource not found")
    return r


@router.get("/resources/{rid:int}/edit")
def edit_resource(request: Request, rid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    r = _get(db, rid)
    form = {"title": r.title, "kind": r.kind, "url": r.url or "", "topic_id": r.topic_id or 0, "level": r.level,
            "description": r.description or "", "approved": r.approved}
    return render(request, "resources/form.html", _form_ctx(db, form, r))


@router.post("/resources/{rid:int}/edit")
async def update_resource(request: Request, rid: int, title: str = Form(""), kind: str = Form("link"),
                          url: str = Form(""), topic_id: int = Form(0), level: str = Form("standard"),
                          description: str = Form(""), approved: bool = Form(False),
                          file: UploadFile | None = File(None),
                          user: User = Depends(require_staff), db: Session = Depends(get_db)):
    r = _get(db, rid)
    was_approved = r.approved
    _, error_response = await _save(request, db, user, r, title, kind, url, topic_id, level, description, approved, file)
    if error_response:
        return error_response
    if approved and not was_approved:
        _after_publish(db, r)
    flash(request, "Resource updated.")
    return RedirectResponse("/resources", status_code=303)


@router.post("/resources/{rid:int}/toggle")
def toggle_resource(request: Request, rid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    r = _get(db, rid)
    r.approved = not r.approved
    db.commit()
    if r.approved:
        _after_publish(db, r)
    flash(request, f"“{r.title}” is now {'approved' if r.approved else 'hidden from students'}.")
    return RedirectResponse(request.headers.get("referer") or "/resources", status_code=303)


@router.post("/resources/{rid:int}/delete")
def delete_resource(request: Request, rid: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    r = _get(db, rid)
    f = r.file
    db.delete(r)
    if f:
        db.delete(f)
    db.commit()
    flash(request, "Resource deleted.")
    return RedirectResponse("/resources", status_code=303)


# ---------------------------------------------------------------- students

@router.get("/materials", name="materials")
def materials(request: Request, q: str = "", category: int = 0, course: int = 0, topic: int = 0, kind: str = "",
              level: str = "", page: int = 1, user: User = Depends(require_any), db: Session = Depends(get_db)):
    stmt = _search(select(Resource).where(Resource.approved.is_(True)), q, category, course, topic, kind, level)
    if user.role == "student":
        stmt = stmt.where(or_(Resource.topic_id.is_(None), visible_course_filter(user.major)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page = max(page, 1)
    items = db.scalars(stmt.options(_opts()).order_by(Resource.view_count.desc(), Resource.created_at.desc())
                       .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    viewed = set(db.scalars(select(ResourceView.resource_id).where(ResourceView.user_id == user.id)))
    filters = {"q": q, "category": category, "course": course, "topic": topic, "kind": kind, "level": level}
    cats = nav_categories(db, user.major if user.role == "student" else None) if user.role == "student" else [
        {"id": c.id, "name": c.name, "courses": [{"id": co.id, "name": co.name} for co in c.courses]}
        for c in db.scalars(select(Category).options(selectinload(Category.courses)).order_by(Category.sort_order))
    ]
    return render(request, "resources/materials.html", {
        "active": "materials", "items": items, "total": total, "page": page, "pages": max(1, -(-total // PAGE_SIZE)),
        "filters": filters, "qs": "&".join(f"{k}={v}" for k, v in filters.items() if v), "cats": cats,
        "kinds": RESOURCE_KINDS, "levels": RESOURCE_LEVELS, "viewed": viewed,
    })


@router.get("/r/{rid:int}", name="open_resource")
def open_resource(request: Request, rid: int, rec: int = 0, user: User = Depends(require_any),
                  db: Session = Depends(get_db)):
    r = db.get(Resource, rid)
    if not r or (not r.approved and not user.is_staff):
        raise HTTPException(404, "Resource not found")
    db.add(ResourceView(resource_id=r.id, user_id=user.id, recommended=bool(rec)))
    r.view_count = (r.view_count or 0) + 1
    db.commit()
    if user.role == "student":
        try:
            from app.services.gamification import on_resource_view
        except ImportError:
            pass
        else:
            on_resource_view(db, user, r, recommended=bool(rec))
    if r.file_id:
        return RedirectResponse(f"/files/{r.file_id}", status_code=303)
    if not r.url:
        raise HTTPException(404, "Resource has no link")
    return RedirectResponse(r.url, status_code=303)


@router.get("/files/{fid:int}")
def serve_file(fid: int, download: int = 0, user: User = Depends(require_any), db: Session = Depends(get_db)):
    f = db.scalar(select(StoredFile).where(StoredFile.id == fid).options(undefer(StoredFile.data)))
    if not f:
        raise HTTPException(404, "File not found")
    if not user.is_staff:
        ok = db.scalar(select(func.count(Resource.id)).where(Resource.file_id == fid, Resource.approved.is_(True)))
        if not ok:
            raise HTTPException(404, "File not found")
    inline = f.content_type.startswith("image/") or f.content_type == "application/pdf"
    disp = "inline" if inline and not download else "attachment"
    safe_name = re.sub(r'[^\w.\- ]', "_", f.filename)
    return Response(f.data, media_type=f.content_type, headers={
        "Content-Disposition": f'{disp}; filename="{safe_name}"',
        "Cache-Control": "private, max-age=3600",
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
    })


def _after_publish(db: Session, r: Resource) -> None:
    """Hook for newly approved resources (notifications are added in a later phase)."""
    if not r.approved:
        return
    try:
        from app.services.notify import notify_new_resource
    except ImportError:
        return
    notify_new_resource(db, r)
