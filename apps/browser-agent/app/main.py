"""HTTP layer only. All logic lives in service.py.

Run:  uvicorn app.main:app --port 9001   (from apps/browser-agent/; port from shared.env)
Docs: http://localhost:9001/docs

MCP:  streamable-HTTP at /mcp (same tools, see mcp_server.py)

Auth: if CANVAS_API_KEY is set, every endpoint except /health and the docs
(including /mcp) needs header `X-Canvas-Key: <key>` (use "Authorize" in /docs).
"""

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from pydantic import BaseModel
from starlette.routing import Route

from .backends import get_backend
from .backends.base import CanvasLoginExpired
from .cache import SnapshotCache
from .config import Settings, get_settings
from .llm import GeminiClassifier
from .mcp_server import HIDE, KeyGuard, build_mcp
from .models import (
    Brief,
    Course,
    DataSource,
    Health,
    Item,
    ItemNotFound,
    Material,
    MaterialNotFound,
    MaterialText,
    MaterialTextUnavailable,
    NoSnapshot,
    Snapshot,
    SyncResult,
)
from .service import BrowserAgentService

logging.basicConfig(level=logging.INFO)

API_KEY_HEADER = APIKeyHeader(name="X-Canvas-Key", auto_error=False,
                              description="Shared secret (CANVAS_API_KEY)")


class ItemsResponse(BaseModel):
    synced_at: datetime
    data_source: DataSource
    items: list[Item]


class CoursesResponse(BaseModel):
    synced_at: datetime
    data_source: DataSource
    courses: list[Course]


class MaterialsResponse(BaseModel):
    synced_at: datetime
    data_source: DataSource
    materials: list[Material]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        backend = get_backend(settings)
        cache = SnapshotCache(settings.snapshot_path, settings.cache_ttl_minutes)
        llm = (GeminiClassifier(settings.gemini_api_key,
                                [settings.gemini_model, *settings.gemini_fallback_models],
                                timeout=settings.gemini_timeout_seconds)
               if settings.llm_active else None)
        app.state.service = BrowserAgentService(settings, backend, cache, llm)
        async with mcp.session_manager.run():
            yield
        await backend.close()

    def require_key(key: str | None = Security(API_KEY_HEADER)) -> None:
        expected = settings.browser_agent_api_key
        if expected and not (key and hmac.compare_digest(key, expected)):
            raise HTTPException(status_code=401, detail="Missing or wrong X-Canvas-Key header")

    app = FastAPI(title="Jarvis browser agent", version="0.3.0", lifespan=lifespan)
    protected = [Depends(require_key)]

    # MCP at /mcp: a second face over the same service (tools resolve it lazily)
    mcp = build_mcp(lambda: app.state.service)
    mcp.streamable_http_app()  # creates mcp.session_manager
    app.router.routes.append(Route(
        "/mcp", KeyGuard(StreamableHTTPASGIApp(mcp.session_manager), settings.browser_agent_api_key),
        methods=["GET", "POST", "DELETE"], include_in_schema=False))

    def svc(request: Request) -> BrowserAgentService:
        return request.app.state.service

    # ---------- error mapping ----------

    @app.exception_handler(CanvasLoginExpired)
    async def login_expired(_req: Request, exc: CanvasLoginExpired):
        return JSONResponse(status_code=503,
                            content={"error": "canvas_login_expired", "detail": str(exc)})

    @app.exception_handler(ItemNotFound)
    async def item_not_found(_req: Request, exc: ItemNotFound):
        return JSONResponse(status_code=404,
                            content={"error": "item_not_found", "detail": f"No item {exc}"})

    @app.exception_handler(NoSnapshot)
    async def no_snapshot(_req: Request, exc: NoSnapshot):
        return JSONResponse(status_code=409, content={"error": "no_snapshot", "detail": str(exc)})

    @app.exception_handler(MaterialNotFound)
    async def material_not_found(_req: Request, exc: MaterialNotFound):
        return JSONResponse(status_code=404,
                            content={"error": "material_not_found", "detail": f"No material {exc}"})

    @app.exception_handler(MaterialTextUnavailable)
    async def material_no_text(_req: Request, exc: MaterialTextUnavailable):
        return JSONResponse(status_code=422,
                            content={"error": "material_text_unavailable", "detail": str(exc)})

    async def snapshot_or_502(request: Request) -> Snapshot:
        try:
            return await svc(request).get_snapshot()
        except CanvasLoginExpired:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"No data available: {exc}") from exc

    # ---------- routes ----------

    @app.get("/health", response_model=Health)
    async def health(request: Request):
        s = svc(request)
        llm = f"gemini ({settings.gemini_model})" if s.llm else "off (rules only)"
        return Health(ok=s.last_error is None, backend=s.backend.name, llm=llm,
                      last_sync=s.last_sync(), sync_in_progress=s.sync_in_progress,
                      last_error=s.last_error)

    @app.post("/sync", response_model=SyncResult, dependencies=protected)
    async def sync(request: Request):
        """Fetch fresh Canvas data now (10–35 s). Prefer the cached reads in conversation."""
        s = svc(request)
        try:
            snapshot = await s.sync()
        except CanvasLoginExpired:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Backend sync failed: {exc}") from exc
        return s.sync_result(snapshot)

    @app.get("/brief", response_model=Brief, dependencies=protected)
    async def brief(request: Request, days: int = Query(7, ge=1, le=60)):
        """One call for 'good morning / what's due': to-do list + courses + data age."""
        await snapshot_or_502(request)
        return await svc(request).brief(days)

    @app.get("/courses", response_model=CoursesResponse, dependencies=protected)
    async def courses(request: Request):
        snap = await snapshot_or_502(request)
        return CoursesResponse(synced_at=snap.synced_at, data_source=snap.data_source,
                               courses=snap.courses)

    # /items/next must be registered before /items/{item_id}
    @app.get("/items/next", response_model=ItemsResponse, dependencies=protected)
    async def items_next(
        request: Request,
        days: int = Query(7, ge=1, le=60),
        include_done: bool = Query(False, description="also return submitted work and events"),
    ):
        """The to-do list: not submitted, real work, due in the next N days."""
        snap = await snapshot_or_502(request)
        return ItemsResponse(synced_at=snap.synced_at, data_source=snap.data_source,
                             items=BrowserAgentService.next_items(snap, days, include_done))

    @app.get("/items", response_model=ItemsResponse, dependencies=protected)
    async def items(request: Request, course_id: str | None = None):
        snap = await snapshot_or_502(request)
        found = [i for i in snap.items if course_id is None or i.course_id == course_id]
        return ItemsResponse(synced_at=snap.synced_at, data_source=snap.data_source, items=found)

    @app.get("/items/{item_id}", response_model=Item, dependencies=protected)
    async def item_detail(request: Request, item_id: str):
        """Full details of one item ('tell me more about HW3')."""
        await snapshot_or_502(request)
        return await svc(request).get_item(item_id)

    @app.post("/items/{item_id}/user-done", response_model=Item, dependencies=protected)
    async def mark_user_done(request: Request, item_id: str):
        """Student says 'I already did this'. Removes it from the to-do list until
        Canvas shows it submitted or it is past due. Never writes to Canvas."""
        return await svc(request).mark_user_done(item_id)

    @app.delete("/items/{item_id}/user-done", response_model=Item, dependencies=protected)
    async def undo_user_done(request: Request, item_id: str):
        """Undo: 'actually I haven't done it'."""
        return await svc(request).undo_user_done(item_id)

    @app.get("/materials", response_model=MaterialsResponse, dependencies=protected,
             response_model_exclude={"materials": {"__all__": HIDE}})
    async def materials(
        request: Request,
        course_id: str | None = None,
        topic_hint: str | None = Query(None, description="words to match in title/module"),
        this_week: bool = Query(False, description="only modules dated today..+7 days + syllabus"),
    ):
        """Study materials LIST (no text): syllabus, PDFs, Canvas pages, links, with module
        + week dates. text_status=ready means GET /materials/{id}/text is instant."""
        await snapshot_or_502(request)
        snap, found = await svc(request).list_materials(course_id, topic_hint, this_week)
        return MaterialsResponse(synced_at=snap.synced_at, data_source=snap.data_source,
                                 materials=found)

    @app.get("/materials/{material_id}/text", response_model=MaterialText, dependencies=protected)
    async def material_text(
        request: Request,
        material_id: str,
        offset: int = Query(0, ge=0),
        max_chars: int = Query(50_000, ge=1_000, le=200_000),
    ):
        """Plain text of one material (PDFs keep [page N] markers). Cached after the first
        call; long texts come in slices (repeat with offset=next_offset)."""
        await snapshot_or_502(request)
        try:
            return await svc(request).material_text(material_id, offset, max_chars)
        except (CanvasLoginExpired, MaterialNotFound, MaterialTextUnavailable):
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not read material: {exc}") from exc

    return app


app = create_app()
