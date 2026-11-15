"""The brain of the browser agent: cache check -> fetch -> classify -> save.

One sync:
  backend.start_sync()
  courses -> raw items per course -> details (parallel)
  Gemini: ONE batched call for all items (optional; rules-only if it fails)
  classify each item (rules + LLM + hard to-do filter)
  materials
  backend.end_sync()   (always)
  save snapshot

main.py (HTTP) only calls methods on BrowserAgentService.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import materials as materials_mod
from .backends.base import BrowserBackend
from .cache import SnapshotCache
from .classify import EXAM_PATTERN, LLMResult, classify, is_done
from .config import Settings
from .llm import GeminiClassifier
from .models import Item, RawItem, Snapshot, SyncResult

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
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

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

    async def _fetch_snapshot(self) -> Snapshot:
        b = self.backend
        await b.start_sync()
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

            materials = []
            for course in courses:
                materials += await materials_mod.collect(b, course)
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

    async def get_snapshot(self) -> Snapshot:
        """Fresh cache -> return it. Stale -> sync. Sync fails but old data
        exists -> return the old data (demo keeps working); else raise."""
        cached = self.cache.load()
        if self.cache.is_fresh(cached):
            return cached
        try:
            return await self.sync()
        except Exception:
            if cached is not None:
                log.warning("Sync failed, serving stale snapshot from %s", cached.synced_at)
                return cached
            raise

    def last_sync(self):
        snap = self.cache.load()
        return snap.synced_at if snap else None

    @staticmethod
    def sync_result(snapshot: Snapshot) -> SyncResult:
        counts = {"courses": len(snapshot.courses), "items": len(snapshot.items),
                  "materials": len(snapshot.materials),
                  "todo": sum(i.in_todo for i in snapshot.items),
                  "submitted": sum(bool(i.submitted) for i in snapshot.items)}
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
