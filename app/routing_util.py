"""Walk every APIRoute of the app, including routes of included routers.

Recent FastAPI versions keep included routers as wrapper objects in ``app.routes`` instead of copying
their routes, so code that needs the full list (sidebar visibility, permission tests) uses this helper.
"""
from collections.abc import Iterator

from fastapi.routing import APIRoute


def iter_api_routes(routes, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
            continue
        original = getattr(r, "original_router", None)
        if original is not None:
            ctx = getattr(r, "include_context", None)
            yield from iter_api_routes(original.routes, prefix + (getattr(ctx, "prefix", "") or ""))


def route_names(app) -> set[str]:
    return {route.name for _, route in iter_api_routes(app.routes)}
