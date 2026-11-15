"""Regenerate apps/browser-agent/mocks/canvas_snapshot.json from the mock backend.

Teammates (orchestrator, UI) can use that file without running this service.
Run from apps/browser-agent/:  python -m scripts.export_mock
"""

import asyncio
import tempfile
from pathlib import Path

from app.backends.mock import MockBackend
from app.cache import SnapshotCache
from app.config import Settings
from app.service import BrowserAgentService

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1] / "mocks" / "canvas_snapshot.json"


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(_env_file=None, data_dir=Path(tmp))
        cache = SnapshotCache(settings.snapshot_path, settings.cache_ttl_minutes)
        snapshot = await BrowserAgentService(settings, MockBackend(), cache).sync()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(snapshot.model_dump_json(indent=2) + "\n")
    print(f"Wrote {OUT.relative_to(REPO_ROOT)} ({len(snapshot.items)} items)")


if __name__ == "__main__":
    asyncio.run(main())
