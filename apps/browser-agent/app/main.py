"""HTTP layer only. All logic lives in service.py.

Run:  uvicorn app.main:app --port 9001   (from apps/browser-agent/; port from shared.env)
Docs: http://localhost:9001/docs

Auth: if BROWSER_AGENT_API_KEY is set, every endpoint except /health and the docs
needs header `X-Jarvis-Key: <key>` (use the "Authorize" button in /docs).
"""

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from .backends import get_backend
from .backends.base import CanvasLoginExpired
from .cache import SnapshotCache
from .config import Settings, get_settings
from .llm import GeminiClassifier
from .models import (
    Brief,
    Course,
    DataSource,
    Health,
    Item,
    ItemNotFound,
    Material,
    NoSnapshot,
    Snapshot,
    SyncResult,
)
from .service import BrowserAgentService

logging.basicConfig(level=logging.INFO)

API_KEY_HEADER = APIKeyHeader(name="X-Jarvis-Key", auto_error=False,
                              description="Shared secret (BROWSER_AGENT_API_KEY)")


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
        yield
        await backend.close()

    def require_key(key: str | None = Security(API_KEY_HEADER)) -> None:
        expected = settings.browser_agent_api_key
        if expected and not (key and hmac.compare_digest(key, expected)):
            raise HTTPException(status_code=401, detail="Missing or wrong X-Jarvis-Key header")

    app = FastAPI(title="Jarvis browser agent", version="0.2.0", lifespan=lifespan)
    protected = [Depends(require_key)]

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

    @app.get("/materials", response_model=MaterialsResponse, dependencies=protected)
    async def materials(request: Request, course_id: str | None = None):
        snap = await snapshot_or_502(request)
        found = [m for m in snap.materials if course_id is None or m.course_id == course_id]
        return MaterialsResponse(synced_at=snap.synced_at, data_source=snap.data_source,
                                 materials=found)

    return app


app = create_app()
