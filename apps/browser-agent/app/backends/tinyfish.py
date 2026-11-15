"""Real Canvas data: Canvas JSON through the TinyFish logged-in browser.

How one sync works (~3-7 s, all READ-ONLY):
  1. start_sync: ask TinyFish to open a browser with the saved Browser Context
     Profile (already logged into Canvas — Duo was done once, by hand).
  2. Connect Playwright to it over CDP.
  3. Use the browser's logged-in cookies to GET Canvas's own JSON:
       /api/v1/courses                 -> courses
       /api/v1/planner/items           -> everything due, all courses, one call
       /api/v1/courses/:id/assignments/:id -> instructions + submission types
  4. end_sync: close the browser WITHOUT saving (the saved login is untouched).

No AI clicks anything here. TinyFish's AI agent (TinyAgent) is not used for
Canvas because the JSON is faster and exact.
"""

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

from ..config import Settings
from ..models import Course, DataSource, Material, RawItem, SourceKind
from .base import BrowserBackend, CanvasLoginExpired

log = logging.getLogger(__name__)

KIND_FOR_PLANNABLE = {
    "assignment": SourceKind.assignment_list,
    "quiz": SourceKind.quiz_list,
    "discussion_topic": SourceKind.discussion,
    "announcement": SourceKind.announcement,
    "calendar_event": SourceKind.calendar_event,
}


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw_html: str | None) -> str:
    if not raw_html:
        return ""
    p = _TextExtractor()
    p.feed(raw_html)
    text = html.unescape("".join(p.parts))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _abs_url(base: str, url: str | None) -> str:
    if not url:
        return base
    return url if url.startswith("http") else base + url


def friendly_code(course: dict[str, Any]) -> str:
    """ASU course_code is an SIS id ('2026FallC-T-CSE579-73246'); the name starts
    with the readable code ('CSE 579: Knowledge Representation (2026 Fall C)')."""
    name = course.get("name") or ""
    if ":" in name:
        return name.split(":", 1)[0].strip()
    return course.get("course_code") or name


def planner_item_to_raw(it: dict[str, Any], base_url: str) -> RawItem | None:
    """Convert one /api/v1/planner/items element into a RawItem. Pure function."""
    kind = KIND_FOR_PLANNABLE.get(it.get("plannable_type", ""))
    if kind is None:  # planner_note, wiki_page, ... not supported yet
        return None
    pl = it.get("plannable") or {}
    subs = it.get("submissions") if isinstance(it.get("submissions"), dict) else None
    override = it.get("planner_override") or {}
    due = pl.get("due_at") or pl.get("todo_date") or pl.get("start_at") or it.get("plannable_date")
    assignment_id = pl.get("assignment_id") or (pl.get("id") if kind == SourceKind.assignment_list else None)
    return RawItem(
        id=f"{it.get('plannable_type')}-{it.get('plannable_id')}",
        course_id=str(it.get("course_id") or ""),
        source_kind=kind,
        title=(pl.get("title") or "").strip(),
        url=_abs_url(base_url, it.get("html_url")),
        due_at=_dt(due),
        points=pl.get("points_possible"),
        body_text=html_to_text(pl.get("description")),  # calendar events carry one
        submitted=subs.get("submitted") if subs else None,
        graded=subs.get("graded") if subs else None,
        excused=subs.get("excused") if subs else None,
        missing=subs.get("missing") if subs else None,
        marked_complete=override.get("marked_complete"),
        canvas_assignment_id=str(assignment_id) if assignment_id else None,
    )


def apply_assignment_detail(raw: RawItem, detail: dict[str, Any]) -> RawItem:
    """Merge /api/v1/courses/:id/assignments/:id into a RawItem. Pure function."""
    return raw.model_copy(update={
        "body_text": html_to_text(detail.get("description")) or raw.body_text,
        "submission_types": detail.get("submission_types") or raw.submission_types,
        "requires_lockdown": detail.get("require_lockdown_browser"),
        "points": detail.get("points_possible", raw.points),
    })


class TinyFishBackend(BrowserBackend):
    name = "tinyfish"
    data_source = DataSource.live

    def __init__(self, settings: Settings):
        self.s = settings
        self._session: dict[str, Any] | None = None
        self._pw = None
        self._browser = None
        self._ctx = None
        self._planner: list[dict[str, Any]] = []
        self._courses: list[dict[str, Any]] = []

    # ---------- session lifecycle ----------

    def _tf(self) -> httpx.AsyncClient:
        if not (self.s.tinyfish_api_key and self.s.tinyfish_profile_id):
            raise RuntimeError("Set TINYFISH_API_KEY and TINYFISH_PROFILE_ID in apps/browser-agent/.env")
        return httpx.AsyncClient(base_url=self.s.tinyfish_base_url, timeout=60,
                                 headers={"X-API-Key": self.s.tinyfish_api_key})

    async def start_sync(self) -> None:
        from playwright.async_api import async_playwright  # lazy: not needed for mock

        async with self._tf() as tf:
            r = await tf.post(f"/v1/profiles/{self.s.tinyfish_profile_id}/setup-session",
                              json={"url": self.s.canvas_base_url, "timeout_seconds": 300})
            r.raise_for_status()
            self._session = r.json()
        log.info("TinyFish browser open; live view: %s/stream/latest", self._session["base_url"])
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(self._session["cdp_url"])
        self._ctx = self._browser.contexts[0]

        # One planner call covers every course; fetched up front so we can tell
        # which courses are current (ASU leaves Canvas term dates empty).
        start = datetime.now(timezone.utc).date() - timedelta(days=self.s.sync_past_days)
        end = datetime.now(timezone.utc).date() + timedelta(days=self.s.sync_days)
        self._planner = await self._get(
            f"/api/v1/planner/items?start_date={start}&end_date={end}&per_page=100")
        self._courses = await self._get(
            "/api/v1/courses?enrollment_state=active&include[]=term&per_page=100")

    async def end_sync(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as exc:
            log.warning("Closing Playwright failed: %s", exc)
        if self._session:
            try:
                async with self._tf() as tf:
                    await tf.post(f"/v1/profiles/{self.s.tinyfish_profile_id}/setup-session/cancel",
                                  json={"session_id": self._session["session_id"]})
            except Exception as exc:
                log.warning("Closing TinyFish session failed: %s", exc)
        self._session = self._pw = self._browser = self._ctx = None

    async def _get(self, path: str) -> Any:
        resp = await self._ctx.request.get(self.s.canvas_base_url + path,
                                           headers={"Accept": "application/json"})
        body = await resp.text()
        # 401 / redirect to the login page = session gone. 403 is NOT a login problem:
        # it means this student may not see that resource (e.g. a hidden Files tab).
        if resp.status == 401 or "/login" in resp.url:
            raise CanvasLoginExpired(
                f"Canvas says not logged in (HTTP {resp.status}). Sign in again (Duo once): "
                f"tinyfish profile sign-in {self.s.tinyfish_profile_id}")
        if resp.status != 200:
            raise RuntimeError(f"Canvas {path} -> HTTP {resp.status}: {body[:200]}")
        return json.loads(body.removeprefix("while(1);"))

    # ---------- BrowserBackend ----------

    async def fetch_courses(self) -> list[Course]:
        active = {str(it.get("course_id")) for it in self._planner}
        courses = [
            Course(id=str(c["id"]), code=friendly_code(c), name=c.get("name", ""),
                   term=(c.get("term") or {}).get("name", ""))
            for c in self._courses if str(c.get("id")) in active
        ]
        if self.s.canvas_course_ids:  # optional manual override in .env
            wanted = set(self.s.canvas_course_ids)
            courses = [c for c in courses if c.id in wanted]
        return courses

    async def fetch_raw_items(self, course: Course) -> list[RawItem]:
        raws = (planner_item_to_raw(it, self.s.canvas_base_url) for it in self._planner
                if str(it.get("course_id")) == course.id)
        return [r for r in raws if r is not None]

    async def fetch_item_detail(self, raw: RawItem) -> RawItem:
        if not raw.canvas_assignment_id:
            return raw
        try:
            detail = await self._get(
                f"/api/v1/courses/{raw.course_id}/assignments/{raw.canvas_assignment_id}")
        except CanvasLoginExpired:
            raise
        except Exception as exc:  # one locked/odd item must not break the sync
            log.warning("Detail fetch failed for %s: %s", raw.id, exc)
            return raw
        return apply_assignment_detail(raw, detail)

    async def fetch_materials(self, course: Course) -> list[Material]:
        # TODO (next step, for Amrita): /api/v1/courses/:id/files + modules -> PDFs.
        return []
