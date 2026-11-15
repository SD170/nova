"""The brain of the browser agent: cache check -> fetch -> classify -> save.

One sync:
  backend.start_sync()
  courses -> raw items per course -> details (parallel) -> materials list
  pre-extract text for this/next week's materials + syllabus (time-boxed)
  backend.end_sync()   (always)
  Gemini: ONE batched call for the open items (optional; rules-only if it fails)
  classify each item (rules + LLM + hard to-do filter)
  apply student overrides ("I already did HW3")
  save snapshot

Reads never block the caller on a slow sync:
  fresh snapshot           -> return it
  stale snapshot           -> return it NOW and refresh in the background
  no snapshot at all       -> sync once (first run only)

main.py (HTTP) only calls methods on BrowserAgentService.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from . import materials as materials_mod
from .backends.base import BrowserBackend, CanvasLoginExpired
from .cache import SnapshotCache
from .classify import EXAM_PATTERN, LLMResult, classify, is_done
from .config import Settings
from .llm import GeminiClassifier
from .models import (
    Brief,
    Item,
    ItemNotFound,
    Material,
    MaterialNotFound,
    MaterialText,
    MaterialTextUnavailable,
    NoSnapshot,
    RawItem,
    Snapshot,
    SyncResult,
    TextStatus,
)
from .overrides import OverrideStore, mark

log = logging.getLogger(__name__)

DETAIL_CONCURRENCY = 6  # max detail requests at once


def needs_llm_review(raw: RawItem) -> bool:
    """Skip items the rules already settle: done work, and plain calendar events
    (office hours, live sessions). Events whose text mentions an exam still go."""
    if is_done(raw)[0]:
        return False
    if raw.source_kind.value == "calendar_event":
        return bool(EXAM_PATTERN.search(raw.body_text))
    return True


class BrowserAgentService:
    def __init__(
        self,
        settings: Settings,
        backend: BrowserBackend,
        cache: SnapshotCache,
        llm: GeminiClassifier | None = None,
    ):
        self.settings = settings
        self.backend = backend
        self.cache = cache
        self.llm = llm
        self.overrides = OverrideStore(settings.data_dir / "user_overrides.json")
        self.texts = materials_mod.TextCache(settings.materials_dir)
        self._lock = asyncio.Lock()          # one sync at a time + snapshot writes
        self._browser_lock = asyncio.Lock()  # one TinyFish browser at a time
        self._bg_task: asyncio.Task | None = None
        self.last_error: str | None = None

    # ---------------- sync ----------------

    @property
    def sync_in_progress(self) -> bool:
        return self._lock.locked()

    async def sync(self) -> Snapshot:
        """Fetch everything from the backend and save a new snapshot.

        If another sync finishes while we wait for the lock, reuse its result
        instead of browsing Canvas twice.
        """
        requested_at = datetime.now(timezone.utc)
        async with self._lock:
            cached = self.cache.load()
            if cached and cached.synced_at >= requested_at:
                return cached
            try:
                snapshot = await self._fetch_snapshot()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                raise
            self.cache.save(snapshot)
            self.last_error = None
            return snapshot

    def refresh_in_background(self) -> bool:
        """Start a sync without waiting. Returns False if one is already running."""
        if self.sync_in_progress or (self._bg_task and not self._bg_task.done()):
            return False

        async def run():
            try:
                await self.sync()
            except Exception as exc:  # recorded in last_error; reads keep serving old data
                log.warning("Background sync failed: %s", exc)

        self._bg_task = asyncio.create_task(run())
        return True

    async def _fetch_snapshot(self) -> Snapshot:
        b = self.backend
        t0 = time.monotonic()
        async with self._browser_lock:
            await b.start_sync()
            t_open = time.monotonic()
            try:
                courses = await b.fetch_courses()
                code_by_id = {c.id: c.code for c in courses}
                sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

                async def detail(raw: RawItem) -> RawItem:
                    async with sem:
                        return await b.fetch_item_detail(raw)

                raws: list[RawItem] = []
                for course in courses:
                    raws += await b.fetch_raw_items(course)
                raws = list(await asyncio.gather(*(detail(r) for r in raws)))
                t_items = time.monotonic()

                async def listing(course) -> list[Material]:
                    try:
                        return await b.fetch_materials(course)
                    except CanvasLoginExpired:
                        raise
                    except Exception as exc:  # materials must never break the to-do list
                        log.warning("Materials listing failed for %s: %s", course.code, exc)
                        return []

                materials: list[Material] = [
                    m for ms in await asyncio.gather(*(listing(c) for c in courses)) for m in ms]
                t_list = time.monotonic()
                await self._prefetch_texts(materials)
                t_pre = time.monotonic()
                log.info("Sync timing: browser+planner %.1fs, items %.1fs, materials list %.1fs, "
                         "text prefetch %.1fs", t_open - t0, t_items - t_open, t_list - t_items,
                         t_pre - t_list)
            finally:
                await b.end_sync()

        llm_results, llm_used, llm_error = await self._run_llm(raws, code_by_id)
        items: list[Item] = [
            classify(
                r,
                course_code=code_by_id.get(r.course_id, r.course_id),
                data_source=b.data_source,
                llm=llm_results.get(r.id),
                threshold=self.settings.llm_confidence_threshold,
            )
            for r in raws
        ]
        items = self.overrides.apply(items)
        return Snapshot(
            synced_at=datetime.now(timezone.utc),
            backend=b.name,
            data_source=b.data_source,
            llm_used=llm_used,
            llm_error=llm_error,
            courses=courses,
            items=items,
            materials=materials,
        )

    async def _run_llm(self, raws: list[RawItem], code_by_id: dict[str, str]
                       ) -> tuple[dict[str, LLMResult], bool, str | None]:
        if self.llm is None:
            return {}, False, None
        # Only send what the LLM can add value to: open work + announcements.
        # Submitted work and calendar events are already decided by rules.
        needs_llm = [r for r in raws if needs_llm_review(r)]
        try:
            results = await self.llm.classify_batch(
                [(r, code_by_id.get(r.course_id, r.course_id)) for r in needs_llm])
            return results, True, None
        except Exception as exc:  # LLM down -> rules still work
            log.warning("LLM classification failed, using rules only: %s", exc)
            return {}, False, f"{type(exc).__name__}: {exc}"

    async def _prefetch_texts(self, materials: list[Material]) -> None:
        """Syllabus + this/next week's modules, so exam prep / quizzes are instant.
        Time-boxed; whatever is left is fetched on first request."""
        today = datetime.now(timezone.utc).date()
        todo = [m for m in materials if not self.texts.has(m)]
        picks: list[Material] = []
        for cid in dict.fromkeys(m.course_id for m in todo):  # limit is per course
            picks += materials_mod.select_prefetch(
                [m for m in todo if m.course_id == cid], today,
                self.settings.materials_prefetch_days, self.settings.materials_prefetch_limit)
        deadline = time.monotonic() + self.settings.materials_prefetch_seconds
        for m in picks:
            if time.monotonic() > deadline:
                log.info("Material prefetch time budget used; rest on demand")
                break
            await self._extract(m)

    async def _extract(self, m: Material) -> dict | None:
        """Needs an open backend session. Caches the text; never raises (except login)."""
        try:
            text, pages = await self.backend.fetch_material_text(m)
        except CanvasLoginExpired:
            raise
        except Exception as exc:
            log.warning("Text extraction failed for %s (%s): %s", m.id, m.title, exc)
            return None
        return self.texts.put(m, text, pages)

    # ---------------- materials ----------------

    def _with_status(self, m: Material) -> Material:
        if m.text_status in (TextStatus.not_fetched, TextStatus.error) and self.texts.has(m):
            return m.model_copy(update={"text_status": TextStatus.ready})
        return m

    async def list_materials(self, course_id: str | None = None, topic_hint: str | None = None,
                             this_week: bool = False) -> tuple[Snapshot, list[Material]]:
        """Listing (no text). topic_hint matches title/module words; this_week keeps
        modules dated today..+MATERIALS_PREFETCH_DAYS (plus the syllabus)."""
        snap = await self.get_snapshot()
        found = [m for m in snap.materials if course_id is None or m.course_id == course_id]
        if topic_hint:
            found = [m for m in found if materials_mod.matches_topic(m, topic_hint)]
        if this_week:
            today = datetime.now(timezone.utc).date()
            end = today + timedelta(days=self.settings.materials_prefetch_days)
            found = [m for m in found if m.type.value == "syllabus" or m.module == "Syllabus"
                     or materials_mod.in_window(m, today, end)]
        return snap, [self._with_status(m) for m in found]

    async def material_text(self, material_id: str, offset: int = 0,
                            max_chars: int = 50_000) -> MaterialText:
        """Cached -> instant. Otherwise open the browser once, download, extract, cache."""
        snap = await self.get_snapshot()
        m = next((x for x in snap.materials if x.id == material_id), None)
        if m is None:
            raise MaterialNotFound(material_id)
        if m.text_status not in (TextStatus.not_fetched, TextStatus.error):
            raise MaterialTextUnavailable(
                f"{m.title}: no text ({m.text_status.value}). Use the url instead: {m.url}")
        entry = self.texts.get(m)
        if entry is None:
            async with self._browser_lock:
                entry = self.texts.get(m)  # another request may have just fetched it
                if entry is None:
                    await self.backend.open_session()
                    try:
                        entry = await self._extract(m)
                    finally:
                        await self.backend.close_session()
        if entry is None:
            raise MaterialTextUnavailable(f"Could not read {m.title} from Canvas right now; "
                                          f"try again later or open {m.url}")
        return materials_mod.to_material_text(m, entry, offset, max_chars)

    # ---------------- reads ----------------

    async def get_snapshot(self) -> Snapshot:
        """Fresh -> return. Stale -> return now + refresh in background.
        Nothing cached yet -> sync once and wait (first run only)."""
        cached = self.cache.load()
        if cached is None:
            return await self.sync()
        if not self.cache.is_fresh(cached):
            self.refresh_in_background()
        return cached

    def last_sync(self):
        snap = self.cache.load()
        return snap.synced_at if snap else None

    async def brief(self, days: int) -> Brief:
        snap = await self.get_snapshot()
        age = (datetime.now(timezone.utc) - snap.synced_at).total_seconds() / 60
        return Brief(
            synced_at=snap.synced_at,
            last_sync_age_minutes=round(age, 1),
            sync_in_progress=self.sync_in_progress,
            data_source=snap.data_source,
            items=self.next_items(snap, days),
            courses=snap.courses,
        )

    async def get_item(self, item_id: str) -> Item:
        snap = await self.get_snapshot()
        for item in snap.items:
            if item.id == item_id:
                return item
        raise ItemNotFound(item_id)

    # ---------------- student overrides ----------------

    async def mark_user_done(self, item_id: str) -> Item:
        """'I already did HW3'. Never writes to Canvas. Survives re-syncs until
        Canvas shows it submitted or the due date passes (see overrides.py)."""
        await self.get_snapshot()  # first run: load Canvas before marking
        async with self._lock:
            snap = self.cache.load()
            if snap is None:
                raise NoSnapshot("No Canvas data yet; call POST /sync first")
            for idx, item in enumerate(snap.items):
                if item.id == item_id:
                    if not item.in_todo:  # already done in Canvas, or not a to-do at all
                        return item
                    self.overrides.add(item_id)
                    snap.items[idx] = mark(item)
                    self.cache.save(snap)
                    return snap.items[idx]
            raise ItemNotFound(item_id)

    async def undo_user_done(self, item_id: str) -> Item:
        """'Actually I haven't done HW3.' Puts it back as Canvas sees it."""
        await self.get_snapshot()
        async with self._lock:
            snap = self.cache.load()
            if snap is None:
                raise NoSnapshot("No Canvas data yet; call POST /sync first")
            self.overrides.remove(item_id)
            for idx, item in enumerate(snap.items):
                if item.id == item_id:
                    if item.user_done:
                        restored = item.model_copy(update={"user_done": False, "in_todo": True,
                                                           "todo_reason": "Not submitted yet"})
                        snap.items[idx] = restored
                        self.cache.save(snap)
                    return snap.items[idx]
            raise ItemNotFound(item_id)

    # ---------------- helpers ----------------

    def sync_result(self, snapshot: Snapshot) -> SyncResult:
        counts = {"courses": len(snapshot.courses), "items": len(snapshot.items),
                  "materials": len(snapshot.materials),
                  "materials_with_text": sum(self.texts.has(m) for m in snapshot.materials),
                  "todo": sum(i.in_todo for i in snapshot.items),
                  "submitted": sum(bool(i.submitted) for i in snapshot.items),
                  "user_done": sum(i.user_done for i in snapshot.items)}
        for item in snapshot.items:
            counts[item.type.value] = counts.get(item.type.value, 0) + 1
        return SyncResult(synced_at=snapshot.synced_at, backend=snapshot.backend,
                          data_source=snapshot.data_source, llm_used=snapshot.llm_used,
                          llm_error=snapshot.llm_error, counts=counts)

    @staticmethod
    def next_items(snapshot: Snapshot, days: int, include_done: bool = False) -> list[Item]:
        """Items due between now and now+days, soonest first.
        Default = the to-do list (not submitted, real work). include_done=True
        returns everything (submitted work, events) with in_todo flags."""
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        upcoming = [i for i in snapshot.items if i.due_at and now <= i.due_at <= end
                    and (include_done or i.in_todo)]
        return sorted(upcoming, key=lambda i: i.due_at)
