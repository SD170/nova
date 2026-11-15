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

HIDE = {"fetch_ref"}  # internal Canvas API paths: not useful to an LLM


def _materials_payload(materials) -> list[dict[str, Any]]:
    return [m.model_dump(mode="json", exclude=HIDE) for m in materials]


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

    @mcp.tool(description="Student's to-do list (not submitted, due in the next `days`) + "
                          "current courses + data age, in one call. Instant from cache. "
                          "Use for 'good morning' / 'what's due'.")
    async def get_daily_brief(days: int = 7) -> dict:
        return (await get_svc().brief(days)).model_dump(mode="json")

    @mcp.tool(description="Upcoming to-do items (not submitted), soonest first. "
                          "include_done=true also returns submitted work and events.")
    async def get_todo_list(days: int = 7, include_done: bool = False) -> dict:
        snap = await get_svc().get_snapshot()
        items = BrowserAgentService.next_items(snap, days, include_done)
        return {"synced_at": snap.synced_at.isoformat(), "data_source": snap.data_source.value,
                "items": [i.model_dump(mode="json") for i in items]}

    @mcp.tool(description="Full details for one Canvas item by id (e.g. 'assignment-123'): "
                          "steps (what_to_do), topics, notes, due date, points.")
    async def get_item_details(item_id: str) -> dict:
        return (await get_svc().get_item(item_id)).model_dump(mode="json")

    @mcp.tool(description="Student says they already did an item. Removes it from the to-do "
                          "list locally until Canvas catches up. Never writes to Canvas.")
    async def mark_item_done_locally(item_id: str) -> dict:
        return (await get_svc().mark_user_done(item_id)).model_dump(mode="json")

    @mcp.tool(description="Undo mark_item_done_locally (student hadn't actually finished it).")
    async def unmark_item_done(item_id: str) -> dict:
        return (await get_svc().undo_user_done(item_id)).model_dump(mode="json")

    @mcp.tool(description="Current-term courses (ones with work due): id, code, name.")
    async def list_courses() -> dict:
        snap = await get_svc().get_snapshot()
        return {"synced_at": snap.synced_at.isoformat(),
                "courses": [c.model_dump(mode="json") for c in snap.courses]}

    @mcp.tool(description="All items for one course. include_done=false keeps only to-dos.")
    async def get_course_items(course_id: str, include_done: bool = True) -> dict:
        snap = await get_svc().get_snapshot()
        items = [i for i in snap.items if i.course_id == course_id
                 and (include_done or i.in_todo)]
        return {"synced_at": snap.synced_at.isoformat(),
                "items": [i.model_dump(mode="json") for i in items]}

    @mcp.tool(description="List a course's study materials (syllabus, lecture PDFs, Canvas "
                          "pages, links) with module name and week dates. NO text here: call "
                          "get_material_text(material_id) for the content. topic_hint filters "
                          "by title/module words ('heaps', 'module 5'); this_week=true keeps "
                          "the current/next week's modules + syllabus (exam prep).")
    async def get_course_materials(course_id: str, topic_hint: str | None = None,
                                   this_week: bool = False) -> dict:
        snap, mats = await get_svc().list_materials(course_id, topic_hint, this_week)
        return {"synced_at": snap.synced_at.isoformat(), "materials": _materials_payload(mats)}

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
        return svc.sync_result(await svc.sync()).model_dump(mode="json")

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
