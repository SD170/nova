"""HTTP layer only. All logic lives in service.py.

Run:  uvicorn app.main:app --port 9001   (from apps/browser-agent/; port from shared.env)
Docs: http://localhost:9001/docs
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .backends import get_backend
from .backends.base import CanvasLoginExpired
from .cache import SnapshotCache
from .config import Settings, get_settings
from .llm import GeminiClassifier
from .models import Course, DataSource, Health, Item, Material, SyncResult
from .service import BrowserAgentService

logging.basicConfig(level=logging.INFO)


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

    app = FastAPI(title="Jarvis browser agent", version="0.1.0", lifespan=lifespan)

    def svc(request: Request) -> BrowserAgentService:
        return request.app.state.service

    @app.exception_handler(CanvasLoginExpired)
    async def login_expired(_req: Request, exc: CanvasLoginExpired):
        return JSONResponse(status_code=503,
                            content={"error": "canvas_login_expired", "detail": str(exc)})

    @app.get("/health", response_model=Health)
    async def health(request: Request):
        s = svc(request)
        llm = f"gemini ({settings.gemini_model})" if s.llm else "off (rules only)"
        return Health(ok=s.last_error is None, backend=s.backend.name, llm=llm,
                      last_sync=s.last_sync(), last_error=s.last_error)

    @app.post("/sync", response_model=SyncResult)
    async def sync(request: Request):
        s = svc(request)
        try:
            snapshot = await s.sync()
        except CanvasLoginExpired:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Backend sync failed: {exc}") from exc
        return s.sync_result(snapshot)

    async def snapshot_or_502(request: Request):
        try:
            return await svc(request).get_snapshot()
        except CanvasLoginExpired:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"No data available: {exc}") from exc

    @app.get("/courses", response_model=CoursesResponse)
    async def courses(request: Request):
        snap = await snapshot_or_502(request)
        return CoursesResponse(synced_at=snap.synced_at, data_source=snap.data_source,
                               courses=snap.courses)

    @app.get("/items/next", response_model=ItemsResponse)
    async def items_next(
        request: Request,
        days: int = Query(7, ge=1, le=60),
        include_done: bool = Query(False, description="also return submitted work and events"),
    ):
        """The to-do list: not submitted, real work, due in the next N days."""
        snap = await snapshot_or_502(request)
        return ItemsResponse(synced_at=snap.synced_at, data_source=snap.data_source,
                             items=BrowserAgentService.next_items(snap, days, include_done))

    @app.get("/items", response_model=ItemsResponse)
    async def items(request: Request, course_id: str | None = None):
        snap = await snapshot_or_502(request)
        found = [i for i in snap.items if course_id is None or i.course_id == course_id]
        return ItemsResponse(synced_at=snap.synced_at, data_source=snap.data_source, items=found)

    @app.get("/materials", response_model=MaterialsResponse)
    async def materials(request: Request, course_id: str | None = None):
        snap = await snapshot_or_502(request)
        found = [m for m in snap.materials if course_id is None or m.course_id == course_id]
        return MaterialsResponse(synced_at=snap.synced_at, data_source=snap.data_source,
                                 materials=found)

    return app


app = create_app()
