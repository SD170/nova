"""Service behaviour: reads never wait on a slow sync; overrides get pruned."""

import asyncio
from datetime import datetime, timedelta, timezone

from app.backends.mock import MockBackend
from app.cache import SnapshotCache
from app.config import Settings
from app.service import BrowserAgentService


class SlowMock(MockBackend):
    def __init__(self):
        self.syncs = 0

    async def start_sync(self):
        self.syncs += 1
        await asyncio.sleep(0.2)  # pretend Canvas + Gemini are slow


def make_service(tmp_path, backend=None):
    s = Settings(_env_file=None, data_dir=tmp_path, gemini_api_key="")
    return BrowserAgentService(s, backend or SlowMock(), SnapshotCache(s.snapshot_path, 30))


def test_stale_read_returns_immediately_and_refreshes_in_background(tmp_path):
    async def run():
        svc = make_service(tmp_path)
        first = await svc.get_snapshot()  # nothing cached -> waits once
        old = first.model_copy(update={"synced_at": first.synced_at - timedelta(hours=2)})
        svc.cache.save(old)

        t = asyncio.get_running_loop().time()
        served = await svc.get_snapshot()  # stale -> instant
        assert asyncio.get_running_loop().time() - t < 0.1
        assert served.synced_at == old.synced_at
        assert svc.sync_in_progress or svc._bg_task is not None

        await svc._bg_task
        assert svc.cache.load().synced_at > old.synced_at
        assert svc.backend.syncs == 2

    asyncio.run(run())


def test_only_one_background_refresh_at_a_time(tmp_path):
    async def run():
        svc = make_service(tmp_path)
        await svc.get_snapshot()
        snap = svc.cache.load()
        svc.cache.save(snap.model_copy(update={"synced_at": snap.synced_at - timedelta(hours=2)}))
        await svc.get_snapshot()
        await svc.get_snapshot()
        await svc.get_snapshot()
        await svc._bg_task
        assert svc.backend.syncs == 2

    asyncio.run(run())


class FlippingMock(MockBackend):
    """Canvas says not submitted, then (after the student uploads) submitted."""

    submitted_now = False

    async def fetch_raw_items(self, course):
        raws = await super().fetch_raw_items(course)
        if self.submitted_now:
            raws = [r.model_copy(update={"submitted": True}) if r.id == "cse310-a3" else r
                    for r in raws]
        return raws


def test_override_dropped_once_canvas_catches_up(tmp_path):
    async def run():
        backend = FlippingMock()
        svc = make_service(tmp_path, backend)
        await svc.sync()
        await svc.mark_user_done("cse310-a3")
        assert "cse310-a3" in svc.overrides.load()

        backend.submitted_now = True
        snap = await svc.sync()
        item = next(i for i in snap.items if i.id == "cse310-a3")
        assert item.submitted is True and item.user_done is False
        assert item.todo_reason == "Already submitted in Canvas"
        assert "cse310-a3" not in svc.overrides.load()  # pruned

    asyncio.run(run())


def test_override_dropped_after_due_date(tmp_path):
    async def run():
        svc = make_service(tmp_path)
        snap = await svc.sync()
        await svc.mark_user_done("cse310-a3")
        past = [i.model_copy(update={"due_at": datetime.now(timezone.utc) - timedelta(days=1)})
                if i.id == "cse310-a3" else i for i in snap.items]
        svc.overrides.apply(past)
        assert "cse310-a3" not in svc.overrides.load()

    asyncio.run(run())
