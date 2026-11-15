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

from .linkedin import LinkedInService
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


def build_mcp(get_svc: Callable[[], BrowserAgentService],
              get_li: Callable[[], LinkedInService] | None = None) -> FastMCP:
    mcp = FastMCP(
        "canvas",
        instructions=("Student's real ASU Canvas (read-only): to-do list, items, courses, "
                      "course materials text for exam prep and quizzes. Reads are instant "
                      "from cache; only sync_canvas is slow. Also linkedin_* tools: what the "
                      "student engaged with while scrolling LinkedIn (via the Jarvis Chrome "
                      "extension), people worth contacting, and drafted comments/DMs. "
                      "Drafts only: nothing is ever posted or sent on LinkedIn."),
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

    if get_li is not None:
        _add_linkedin_tools(mcp, get_li)
    return mcp


def _first(name: str) -> str:
    return (name or "").split()[0] if name else "them"


def _speak_people(people) -> str:
    if not people:
        return "Nobody stands out yet. Like or read a few more posts."
    bits = [f"{p.name}" + (f" from {p.company}" if p.company else "") for p in people[:2]]
    return "Worth reaching out to: " + " and ".join(bits) + "."


def _add_linkedin_tools(mcp: FastMCP, get_li: Callable[[], LinkedInService]) -> None:
    @mcp.tool(description="What the student saw and did on LinkedIn this session (via the "
                          "Nova Chrome extension): posts seen, people worth reaching out to "
                          "with reasons, companies, interests, recent likes. Instant. Use for "
                          "'who should I reach out to' / 'what did I find on LinkedIn'. "
                          "Say `speak`; details only if asked.")
    async def linkedin_session_summary(max_people: int = 3) -> dict:
        li = get_li()
        s = li.store.summary(max(1, min(max_people, 10)))
        return {"speak": f"You've looked at {s.posts_seen} posts. " + _speak_people(s.people),
                "people": [{"name": p.name, "headline": p.headline, "company": p.company,
                            "why": p.reasons, "action": p.suggested_action,
                            "post_id": p.post_ids[-1]} for p in s.people],
                "companies": [c.name for c in s.companies[:5]],
                "interests": [i.topic for i in s.interests[:5]],
                "recent_activity": [f"{a.kind} {a.author_name}"
                                    for a in li.store.recent_activity(5)]}

    @mcp.tool(description="Recent LinkedIn posts the student scrolled past (id, author, "
                          "short text). engaged_only=true keeps ones they liked / read / "
                          "expanded. Say `speak`.")
    async def linkedin_recent_posts(limit: int = 5, engaged_only: bool = False) -> dict:
        posts = get_li().store.recent(max(1, min(limit, 20)), engaged_only)
        return {"speak": (f"Last posts: " + ", ".join(p.author_name for p in posts[:3]) + "."
                          if posts else "No LinkedIn posts yet."),
                "posts": [{"id": p.id, "author": p.author_name, "headline": p.author_headline,
                           "text": p.text[:300], "engaged": p.score > 0} for p in posts]}

    @mcp.tool(description="Draft what the student could write on LinkedIn, shown in their "
                          "LinkedIn side panel to copy. person = the author's name as the "
                          "student said it ('Marcus'), or leave empty for the post on their "
                          "screen right now. kind: comment (for 'what should I comment'), "
                          "dm (for 'help me reach out / connect'), or both. note = anything "
                          "the student wants included. Takes ~5 s. Never posts. Say `speak`.")
    async def linkedin_draft_message(person: str | None = None, kind: str = "comment",
                                     note: str | None = None,
                                     post_id: str | None = None) -> dict:
        if kind not in ("comment", "dm", "both"):
            kind = "comment"
        card = await get_li().draft_card(post_id, person, kind, note)
        d = card.drafts
        if card.status != "done" or d is None:
            return {"speak": "I couldn't draft that one. Try again in a moment.",
                    "card_id": card.id, "error": card.error}
        who = _first(d.author_name)
        what = {"comment": "two comment options", "dm": "a connection note and a message",
                "both": "two comments and a reach-out message"}[kind]
        speak = f"I put {what} for {who}'s post in your LinkedIn panel."
        if kind == "comment" and d.comments:
            speak += f" First one: {d.comments[0]}"
        return {"speak": speak, "card_id": card.id, "author": d.author_name,
                "comments": d.comments, "connection_note": d.connection_note, "dm": d.dm}

    @mcp.tool(description="Research a company in the background (what they do, a recent "
                          "fact, the CEO, the CEO's LinkedIn link) and draft 2 short messages "
                          "to the CEO. Result appears in the student's LinkedIn panel in "
                          "~20 s. company = name as said ('Ramp'); or leave empty and give "
                          "person, or nothing for the post on screen. Say `speak` and move "
                          "on; use linkedin_get_research if they ask what you found.")
    async def linkedin_research_company(company: str | None = None,
                                        person: str | None = None) -> dict:
        card = get_li().start_research(company, person)
        name = card.title.removeprefix("Researching ").strip()
        if card.status == "failed":
            return {"speak": f"I can't research right now: {card.error}", "card_id": card.id}
        return {"speak": f"On it. I'm looking up {name} and its CEO. It'll pop up in your "
                         "LinkedIn panel in about 20 seconds.", "card_id": card.id,
                "status": card.status}

    @mcp.tool(description="The latest company research (or the one for `company`): short "
                          "brief, CEO, CEO LinkedIn link, 2 draft messages. status=working "
                          "means it isn't finished yet. Say `speak`.")
    async def linkedin_get_research(company: str | None = None) -> dict:
        cards = [c for c in get_li().recent_cards(30) if c.kind == "research"]
        if company:
            cards = [c for c in cards if company.lower() in c.title.lower()] or cards
        if not cards:
            return {"speak": "I haven't researched any company yet."}
        c = cards[0]
        if c.status == "working":
            return {"speak": "Still researching, give me a few more seconds.", "status": "working"}
        if c.status == "failed" or c.research is None:
            return {"speak": f"That research didn't work: {c.error}", "status": "failed"}
        r = c.research
        return {"speak": r.speak, "status": "done", "company": r.company, "summary": r.summary,
                "ceo": r.ceo_name, "ceo_linkedin_url": r.ceo_linkedin_url,
                "messages": r.messages}


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
