"""Student Jarvis — current events & news notifications (Amrita's draft).

Run:   python server.py        -> http://localhost:9003
Tests: python -m pytest
No API key required. Optional keys go in .env (see .env.example).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from news import digest, sources
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

app = FastAPI(title="Student Jarvis News", docs_url="/news/docs", openapi_url="/news/openapi.json")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/news/health")
async def health():
    return {"ok": True, "keyed_sources": {"newsapi": bool(os.environ.get("NEWSAPI_KEY"))}}


@app.get("/news/interests")
async def interests():
    """Default (demo) interests until the student's real profile/memory is connected."""
    return {"items": digest.DEFAULT_INTERESTS, "demo": True}


class DigestBody(BaseModel):
    interests: Optional[list[dict]] = None
    per_topic: int = 5
    since: Optional[str] = None


@app.post("/news/digest")
async def post_digest(body: DigestBody):
    return await digest.build(body.interests, per_topic=max(1, min(body.per_topic, 10)), since=body.since)


@app.get("/news/digest")
async def get_digest(topics: str = "", per_topic: int = 5, since: Optional[str] = None):
    """Quick form: /news/digest?topics=politics,Phoenix Suns,machine learning"""
    ints = [{"label": t.strip(), "kind": "topic", "query": t.strip()} for t in topics.split(",") if t.strip()] or None
    return await digest.build(ints, per_topic=max(1, min(per_topic, 10)), since=since)


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
        ints = [{"label": t, "kind": "topic", "query": t} for t in topics] if topics else None
        d = await digest.build(ints, per_topic=3)
        results.append({"toolCallId": call.get("id"), "result": {
            "speak": d["speak"],
            "items": [{k: i[k] for k in ("title", "source", "url", "published_at", "topic")} for i in d["items"][:12]],
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
