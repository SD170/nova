"""HTTP routes, X-Jarvis-Key auth and error mapping only. Logic lives in service.py / tools.py.

Run:   uvicorn app.main:app --port 9004        (docs: http://localhost:9004/docs)
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import digest, events, push, tools
from .config import ROOT, settings
from .models import DedupeIn, ToolCall

STATIC = ROOT / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = None
    if settings.push_enabled:
        push.public_key()  # create VAPID keys on first run
        task = asyncio.create_task(push.run_forever())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Student Jarvis — news & ASU events tools", lifespan=lifespan,
              description="Tool catalog for the Jarvis brain. Send header X-Jarvis-Key when NEWS_AGENT_API_KEY is set.")
# The team UI (Vite :5173, Electron file://) calls these tools straight from the browser.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-Jarvis-Key"])
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def require_key(x_jarvis_key: Optional[str] = Header(None)) -> None:
    if settings.api_key and x_jarvis_key != settings.api_key:
        raise HTTPException(401, "missing or wrong X-Jarvis-Key")


async def _run(name: str, args: dict):
    try:
        return await tools.call(name, args)
    except tools.ToolError as e:
        raise HTTPException(e.status, str(e))


# ───────────────────────── tool endpoints (brain-facing, auth) ─────────────────────────

@app.get("/health")
async def health():
    return tools.health()


@app.get("/topics", dependencies=[Depends(require_key)])
async def get_available_topics():
    return await _run("get_available_topics", {})


@app.get("/news", dependencies=[Depends(require_key)])
async def fetch_news(topics: str = Query(..., description="Comma-separated, e.g. world, Phoenix Suns, AI"),
                     since_hours: int = Query(24, ge=1, le=72), trusted_only: bool = True,
                     per_topic: int = Query(5, ge=1, le=15),
                     live: bool = Query(False, description="true = fetch now (≤60 s old) instead of the 15-min cache")):
    return await _run("fetch_news", {"topics": topics, "since_hours": since_hours,
                                     "trusted_only": trusted_only, "per_topic": per_topic, "live": live})


@app.get("/news/candidates", dependencies=[Depends(require_key)])
async def news_candidates(topics: str = "top,politics,world,science,tech,education,sports",
                          since: str = Query("24h", pattern=r"^\d{1,2}h$")):
    """Saswata's contract name: raw pool for the brain to rank (same data as fetch_news, up to 15 per topic)."""
    return await _run("fetch_news", {"topics": topics, "since_hours": int(since[:-1]), "per_topic": 15})


@app.get("/news/item/{item_id}", dependencies=[Depends(require_key)])
async def get_news_item(item_id: str):
    return await _run("get_news_item", {"item_id": item_id})


@app.post("/news/dedupe", dependencies=[Depends(require_key)])
async def dedupe_news(items: list[DedupeIn]):
    return await _run("dedupe_news", {"items": [i.model_dump() for i in items]})


@app.get("/events", dependencies=[Depends(require_key)])
async def fetch_asu_events(days: int = Query(7, ge=1, le=60), query: str = "", campus: str = "",
                           limit: int = Query(25, ge=1, le=100), live: bool = False):
    return await _run("fetch_asu_events", {"days": days, "query": query, "campus": campus, "limit": limit,
                                           "live": live})


@app.get("/tools")
async def list_tools():
    """OpenAI-style function definitions — register these in Hermes / Vapi."""
    return {"tools": tools.TOOL_DEFINITIONS}


@app.post("/tools/call", dependencies=[Depends(require_key)])
async def call_tool(body: ToolCall):
    args = body.arguments if isinstance(body.arguments, dict) else body.arguments
    return {"name": body.name, "result": await _run(body.name, args)}


@app.post("/tools/vapi", dependencies=[Depends(require_key)])
async def vapi_tools(request: Request):
    """Vapi tool-calls webhook envelope (same as apps/voice/server.py /vapi)."""
    message = (await request.json()).get("message") or {}
    results = []
    for c in message.get("toolCallList") or message.get("toolCalls") or []:
        fn = c.get("function") or {}
        try:
            result = await tools.call(fn.get("name") or c.get("name"), fn.get("arguments") or c.get("arguments") or {})
        except tools.ToolError as e:
            result = {"error": str(e)}
        results.append({"toolCallId": c.get("id"), "result": result})
    return JSONResponse({"results": results})


# ───────────────────────── student web page + phone alerts (public) ─────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/news/interests", include_in_schema=False)
async def interests():
    return {"items": digest.DEFAULT_INTERESTS, "demo": True}


class DigestBody(BaseModel):
    interests: Optional[list[dict]] = None
    per_topic: int = 5
    since: Optional[str] = None
    window_hours: int = 24
    trusted_only: bool = True


@app.post("/news/digest", include_in_schema=False)
async def page_digest(body: DigestBody):
    """Used by the web page (personal interest chips). The brain uses fetch_news instead."""
    return await digest.build(body.interests, per_topic=max(1, min(body.per_topic, 10)), since=body.since,
                              window_hours=max(1, min(body.window_hours, 72)), trusted_only=body.trusted_only)


@app.get("/push/public-key", include_in_schema=False)
async def push_key():
    return {"publicKey": push.public_key()}


class PushBody(BaseModel):
    subscription: dict
    interests: Optional[list[dict]] = None
    trusted_only: bool = True
    tz_offset_min: int = 0
    quiet_start: int = 22
    quiet_end: int = 7


@app.post("/push/subscribe", include_in_schema=False)
async def push_subscribe(body: PushBody, background: BackgroundTasks):
    try:
        info = push.upsert(body.subscription, body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    rec = push.get(body.subscription["endpoint"])
    if rec and rec.get("last_check") is None:
        background.add_task(push.check_one, info["id"], rec, True)  # one welcome alert
    return {"ok": True, **info}


class EndpointBody(BaseModel):
    endpoint: str


@app.post("/push/unsubscribe", include_in_schema=False)
async def push_unsubscribe(body: EndpointBody):
    return {"ok": push.remove(body.endpoint)}


@app.post("/push/test", include_in_schema=False)
async def push_test(body: EndpointBody):
    rec = push.get(body.endpoint)
    if not rec:
        raise HTTPException(404, "This phone isn't subscribed yet.")
    d = await digest.build(rec["interests"], per_topic=3, trusted_only=rec.get("trusted_only", True))
    story = next((s for s in d["items"] if s.get("confirmed")), d["items"][0] if d["items"] else None)
    data = push.payload(story) if story else {"title": "Jarvis news", "body": "Notifications are working.", "url": "/"}
    try:
        await push.send(rec["subscription"], data)
    except push.Gone:
        push.remove(body.endpoint)
        raise HTTPException(410, "This phone's subscription expired. Turn alerts on again.")
    return {"ok": True, "sent": data["title"]}


@app.get("/push/status", include_in_schema=False)
async def push_status():
    return {"subscribers": push.count(), "interval_seconds": push.INTERVAL}


if __name__ == "__main__":
    import uvicorn

    print(f"Student Jarvis news tools running at http://localhost:{settings.port}  (docs: /docs)")
    uvicorn.run(app, host="127.0.0.1", port=settings.port, log_level="warning")
