"""Pull academic data from Abishek's Canvas MCP.

Pragmatic: we hit the MCP over HTTP JSON-RPC, same way the Hermes brain does.
No fancy MCP SDK. One init, one tools/call, parse `content[].text`.

For the first version we anchor on `get_daily_brief(days=120)` + `list_courses`
so we can ship a credential today. A real transcript endpoint lands later.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx


def _mcp_url() -> str:
    base = os.environ.get("PUBLIC_CANVAS_BASE", "").rstrip("/")
    if not base:
        raise RuntimeError("PUBLIC_CANVAS_BASE not set")
    return f"{base}/mcp"


def _headers() -> dict[str, str]:
    key = os.environ.get("CANVAS_API_KEY", "").strip()
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **({"X-Canvas-Key": key} if key else {}),
    }


async def _call_tool(client: httpx.AsyncClient, name: str, args: dict[str, Any]) -> Any:
    # Server is stateless_http=true in Abishek's build; one request per call.
    # Initialize is implicit on first POST in stateless mode, but being explicit
    # is cheap and future-proof.
    await client.post(_mcp_url(), headers=_headers(), json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18",
                   "capabilities": {},
                   "clientInfo": {"name": "cred-agent", "version": "0.1"}},
    })
    r = await client.post(_mcp_url(), headers=_headers(), json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"canvas MCP error on {name}: {data['error']}")
    content = data.get("result", {}).get("content") or []
    text = content[0].get("text", "") if content else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


async def fetch_transcript() -> dict[str, Any]:
    """Build a transcript-shaped payload from Canvas.

    Returns the same shape the credential will be signed over:
        {
          "student": {...},         # filled in by main.py
          "courses": [...],
          "assignments": [...],
          "generated_at": "...",    # filled in by main.py
          "source": "canvas-mcp"
        }
    This fn only fills courses + assignments; other fields are composed above.
    """
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        courses = await _call_tool(client, "list_courses", {})
        # get_daily_brief with a wide window gives upcoming+recent items. For a
        # real transcript we'd want completed graded items; the MCP's
        # get_todo_list returns due-soon only, so we pair it with per-course
        # get_course_items(include_done=True) for a fuller picture.
        brief = await _call_tool(client, "get_daily_brief", {"days": 120})
        # Pull done items for every course — cheap because Abishek caches.
        course_items: list[dict[str, Any]] = []
        for c in (courses.get("courses") or courses.get("items") or []):
            cid = c.get("id") or c.get("course_id")
            if not cid:
                continue
            try:
                items = await _call_tool(
                    client, "get_course_items",
                    {"course_id": cid, "include_done": True},
                )
                course_items.append({"course_id": cid, "items": items})
            except Exception as e:  # noqa: BLE001
                course_items.append({"course_id": cid, "error": str(e)})
    return {
        "courses": courses,
        "daily_brief": brief,
        "course_items": course_items,
    }
