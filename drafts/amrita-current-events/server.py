"""Student Jarvis — current events & news notifications (Amrita's draft).

Run:   python server.py        -> http://localhost:9003
Tests: python -m pytest
No API key required. Optional keys go in .env (see .env.example).
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from news import digest, outlets, push, sources
from news.tools import NEWS_TOOLS

HERE = Path(__file__).parent


def _load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(HERE / ".env")
_load_env(HERE.parent.parent / "shared.env")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = None
    if os.environ.get("PUSH_ENABLED", "1") != "0":
        push.public_key()  # create VAPID keys on first run
        task = asyncio.create_task(push.run_forever())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Student Jarvis News", docs_url="/news/docs", openapi_url="/news/openapi.json", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


# The service worker must be served from the root so it controls the whole site.
@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(HERE / "static" / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(HERE / "static" / "manifest.webmanifest", media_type="application/manifest+json")


# ───────────────────────── phone push notifications ─────────────────────────

@app.get("/push/public-key")
async def push_key():
    return {"publicKey": push.public_key()}


class PushBody(BaseModel):
    subscription: dict
    interests: Optional[list[dict]] = None
    trusted_only: bool = True
    tz_offset_min: int = 0
    quiet_start: int = 22
    quiet_end: int = 7


@app.post("/push/subscribe")
async def push_subscribe(body: PushBody, background: BackgroundTasks):
    try:
        info = push.upsert(body.subscription, body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    rec = push.get(body.subscription["endpoint"])
    if rec and rec.get("last_check") is None:
        # Welcome: the top confirmed story right away, then only new ones.
        background.add_task(push.check_one, info["id"], rec, True)
    return {"ok": True, **info}


class EndpointBody(BaseModel):
    endpoint: str


@app.post("/push/unsubscribe")
async def push_unsubscribe(body: EndpointBody):
    return {"ok": push.remove(body.endpoint)}


@app.post("/push/test")
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
        raise HTTPException(410, "This phone's subscription expired. Turn notifications on again.")
    return {"ok": True, "sent": data["title"]}


@app.get("/push/status")
async def push_status():
    return {"subscribers": push.count(), "interval_seconds": push.INTERVAL}


@app.get("/news/health")
async def health():
    return {"ok": True, "keyed_sources": outlets.active_keys(),
            "outlet_feeds": {s: [n for n, _ in f] for s, f in outlets.FEEDS.items()}}


@app.get("/news/interests")
async def interests():
    """Default (demo) interests until the student's real profile/memory is connected."""
    return {"items": digest.DEFAULT_INTERESTS, "demo": True}


class DigestBody(BaseModel):
    interests: Optional[list[dict]] = None
    per_topic: int = 5
    since: Optional[str] = None
    window_hours: int = 24
    trusted_only: bool = True


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


@app.post("/news/digest")
async def post_digest(body: DigestBody):
    return await digest.build(body.interests, per_topic=_clamp(body.per_topic, 1, 10), since=body.since,
                              window_hours=_clamp(body.window_hours, 1, 72), trusted_only=body.trusted_only)


@app.get("/news/digest")
async def get_digest(topics: str = "", per_topic: int = 5, since: Optional[str] = None,
                     window_hours: int = 24, trusted_only: bool = True):
    """Quick form: /news/digest?topics=politics,Phoenix Suns,machine learning"""
    ints = [_topic(t) for t in topics.split(",") if t.strip()] or None
    return await digest.build(ints, per_topic=_clamp(per_topic, 1, 10), since=since,
                              window_hours=_clamp(window_hours, 1, 72), trusted_only=trusted_only)


def _topic(t: str) -> dict:
    """'world' -> the World section; anything else -> keyword topic."""
    t = t.strip()
    if t.lower() in outlets.SECTIONS:
        return {"label": t.title(), "kind": "section", "section": t.lower()}
    return {"label": t, "kind": "topic", "query": t}


@app.post("/news/tools")
async def tools_webhook(request: Request):
    """Vapi-style tool-calls webhook (same envelope as apps/voice/server.py /vapi)."""
    body = await request.json()
    message = body.get("message") or {}
    results = []
    for call in message.get("toolCallList") or message.get("toolCalls") or []:
        fn_info = call.get("function") or {}
        name = fn_info.get("name") or call.get("name")
        args = fn_info.get("arguments") or call.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if name != "get_news_digest":
            results.append({"toolCallId": call.get("id"), "result": {"error": f"unknown tool: {name}", "available": list(NEWS_TOOLS)}})
            continue
        topics = args.get("topics")
        ints = [_topic(t) for t in topics] if topics else None
        d = await digest.build(ints, per_topic=3)
        results.append({"toolCallId": call.get("id"), "result": {
            "speak": d["speak"],
            "items": [{k: i[k] for k in ("title", "source", "url", "published_at", "topic", "outlets")} for i in d["items"][:12]],
        }})
    return JSONResponse({"results": results})


@app.post("/news/cache/clear")
async def clear_cache():
    sources.clear_cache()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("NEWS_PORT", "9003"))
    print(f"Student Jarvis News running at http://localhost:{port}")
    uvicorn.run(app, host=os.environ.get("NEWS_HOST", "127.0.0.1"), port=port, log_level="warning")
