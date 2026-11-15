"""MCP face of the browser agent (streamable-HTTP at /mcp, same port 9001).

Same BrowserAgentService and same JSON shapes as the REST endpoints; MCP just lets
Hermes (or Claude Code / Cursor) discover the tools from one URL:

    mcp_servers:
      canvas:
        url: ${PUBLIC_CANVAS_BASE}/mcp
        headers: {X-Canvas-Key: ${CANVAS_API_KEY}}

Tool errors (login expired, unknown id, no text) come back as MCP tool errors with
a plain-English message the brain can read out.
"""

import hmac
import json
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .service import BrowserAgentService
from .voice import (
    compact_item,
    short_course,
    short_title,
    speak_courses,
    speak_item,
    speak_todo,
)

HIDE = {"fetch_ref"}  # internal Canvas API paths: not useful to an LLM
MAX_ITEMS = 8         # voice answers never need more; `count` still has the total


def _materials_payload(materials) -> list[dict[str, Any]]:
    """Compact on purpose: the list can have 140+ files; the brain only needs id + title."""
    out = []
    for m in materials:
        row = {"id": m.id, "title": m.title[:70], "type": m.type.value,
               "module": (m.module or "")[:50], "text_status": m.text_status.value}
        if m.week_start and m.week_end:
            row["week"] = f"{m.week_start:%b} {m.week_start.day}-{m.week_end.day}"
        out.append(row)
    return out


def build_mcp(get_svc: Callable[[], BrowserAgentService]) -> FastMCP:
    mcp = FastMCP(
        "canvas",
        instructions=("Student's real ASU Canvas (read-only): to-do list, items, courses, "
                      "course materials text for exam prep and quizzes. Reads are instant "
                      "from cache; only sync_canvas is slow."),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        # Host check off: requests arrive via the Cloudflare tunnel host. Access is
        # guarded by X-Canvas-Key instead (see KeyGuard).
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(description="Student's to-do list (not submitted, due in the next `days`) in one "
                          "call. Instant from cache. Use for 'good morning' / 'what's due'. "
                          "Result has `speak`: say it as is (it is already short); add detail "
                          "only if the student asks.")
    async def get_daily_brief(days: int = 7) -> dict:
        b = await get_svc().brief(days)
        return {"speak": speak_todo(b.items, days), "count": len(b.items),
                "items": [compact_item(i) for i in b.items[:MAX_ITEMS]],
                "courses": [short_course(c.code) for c in b.courses],
                "data_source": b.data_source.value, "synced_at": b.synced_at.isoformat(),
                "data_age_minutes": round(b.last_sync_age_minutes),
                "sync_in_progress": b.sync_in_progress}

    @mcp.tool(description="Upcoming to-do items (not submitted), soonest first. "
                          "include_done=true also returns submitted work and events. "
                          "Say `speak`; details only if asked.")
    async def get_todo_list(days: int = 7, include_done: bool = False) -> dict:
        snap = await get_svc().get_snapshot()
        items = BrowserAgentService.next_items(snap, days, include_done)
        return {"speak": speak_todo(items, days), "count": len(items),
                "items": [compact_item(i) for i in items[:MAX_ITEMS]],
                "synced_at": snap.synced_at.isoformat(), "data_source": snap.data_source.value}

    @mcp.tool(description="Details for one Canvas item by id (e.g. 'assignment-123'): due date, "
                          "points, steps (what_to_do), topics. Say `speak` (one short line); "
                          "read the steps only if the student asks for them.")
    async def get_item_details(item_id: str) -> dict:
        i = await get_svc().get_item(item_id)
        return {"speak": speak_item(i), **compact_item(i), "full_title": i.title,
                "steps": [s[:160] for s in i.what_to_do[:5]], "topics": i.topics[:6],
                "submitted": i.submitted, "in_todo": i.in_todo}

    @mcp.tool(description="Student says they already did an item. Removes it from the to-do "
                          "list locally until Canvas catches up. Never writes to Canvas.")
    async def mark_item_done_locally(item_id: str) -> dict:
        i = await get_svc().mark_user_done(item_id)
        return {"speak": f"Done, I took {short_title(i.title)} off your list.", "id": i.id,
                "user_done": i.user_done, "in_todo": i.in_todo}

    @mcp.tool(description="Undo mark_item_done_locally (student hadn't actually finished it).")
    async def unmark_item_done(item_id: str) -> dict:
        i = await get_svc().undo_user_done(item_id)
        return {"speak": f"Okay, {short_title(i.title)} is back on your list.", "id": i.id,
                "user_done": i.user_done, "in_todo": i.in_todo}

    @mcp.tool(description="Current-term courses (ones with work due): id, short code, name. "
                          "Always say the short code (CSE 540), never the long name.")
    async def list_courses() -> dict:
        snap = await get_svc().get_snapshot()
        return {"speak": speak_courses(snap.courses), "synced_at": snap.synced_at.isoformat(),
                "courses": [{"id": c.id, "code": short_course(c.code), "name": c.name}
                            for c in snap.courses]}

    @mcp.tool(description="Items for one course. include_done=false keeps only to-dos. "
                          "Say `speak`; details only if asked.")
    async def get_course_items(course_id: str, include_done: bool = True) -> dict:
        snap = await get_svc().get_snapshot()
        items = [i for i in snap.items if i.course_id == course_id
                 and (include_done or i.in_todo)]
        code = short_course(items[0].course_code) if items else course_id
        todo = sum(1 for i in items if i.in_todo)
        return {"speak": (f"{code}: {len(items)} items, {todo} still to do." if items
                          else f"No items found for {code}."),
                "count": len(items), "items": [compact_item(i) for i in items[:MAX_ITEMS]],
                "synced_at": snap.synced_at.isoformat()}

    @mcp.tool(description="List a course's study materials (syllabus, lecture PDFs, Canvas "
                          "pages, links), compact: id, title, module, week. NO text here: call "
                          "get_material_text(material_id) for the content. topic_hint filters "
                          "by title/module words ('heaps', 'module 5'); this_week=true keeps "
                          "the current/next week's modules + syllabus (exam prep). Shows at "
                          "most `limit` files; `total` is the real count.")
    async def get_course_materials(course_id: str, topic_hint: str | None = None,
                                   this_week: bool = False, limit: int = 20) -> dict:
        snap, mats = await get_svc().list_materials(course_id, topic_hint, this_week)
        limit = max(1, min(limit, 50))
        code = short_course(mats[0].course_code) if mats else course_id
        return {"speak": (f"{len(mats)} materials for {code}." if mats
                          else f"No materials found for {code}."),
                "total": len(mats), "shown": min(limit, len(mats)),
                "materials": _materials_payload(mats[:limit]),
                "synced_at": snap.synced_at.isoformat()}

    @mcp.tool(description="Plain text of one material (PDF text keeps [page N] markers for "
                          "citations). Instant if text_status was 'ready', else ~2-10 s to "
                          "download once. Long documents come in slices: call again with "
                          "offset=next_offset until next_offset is null.")
    async def get_material_text(material_id: str, offset: int = 0, max_chars: int = 20_000) -> dict:
        max_chars = max(1_000, min(max_chars, 100_000))
        t = await get_svc().material_text(material_id, offset, max_chars)
        return t.model_dump(mode="json")

    @mcp.tool(description="Force a fresh Canvas pull (10-40 s). Only when the student "
                          "explicitly asks to refresh; normal reads are already fresh enough.")
    async def sync_canvas() -> dict:
        svc = get_svc()
        r = svc.sync_result(await svc.sync()).model_dump(mode="json")
        c = r["counts"]
        r["speak"] = (f"Synced Canvas. {c.get('todo', 0)} to do across "
                      f"{c.get('courses', 0)} courses.")
        return r

    @mcp.tool(description="Service health: last sync time, sync in progress, last error.")
    async def get_canvas_health() -> dict:
        svc = get_svc()
        last = svc.last_sync()
        return {"ok": svc.last_error is None, "backend": svc.backend.name,
                "last_sync": last.isoformat() if last else None,
                "sync_in_progress": svc.sync_in_progress, "last_error": svc.last_error}

    return mcp


class KeyGuard:
    """ASGI wrapper: require X-Canvas-Key on /mcp (mounted apps skip FastAPI deps)."""

    def __init__(self, app, expected_key: str):
        self.app = app
        self.expected = expected_key

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.expected:
            headers = dict(scope.get("headers") or [])
            key = headers.get(b"x-canvas-key", b"").decode("latin-1")
            if not hmac.compare_digest(key, self.expected):
                body = json.dumps({"detail": "Missing or wrong X-Canvas-Key header"}).encode()
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
