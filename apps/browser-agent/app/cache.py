"""Read/write canvas_snapshot.json and decide whether it is still fresh."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Snapshot


class SnapshotCache:
    def __init__(self, path: Path, ttl_minutes: int):
        self.path = path
        self.ttl = timedelta(minutes=ttl_minutes)

    def load(self) -> Snapshot | None:
        if not self.path.exists():
            return None
        try:
            return Snapshot.model_validate_json(self.path.read_text())
        except ValueError:
            return None  # corrupt/old-format file: treat as no cache

    def save(self, snapshot: Snapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(snapshot.model_dump_json(indent=2))
        tmp.replace(self.path)  # atomic: readers never see a half-written file

    def is_fresh(self, snapshot: Snapshot | None) -> bool:
        if snapshot is None:
            return False
        return datetime.now(timezone.utc) - snapshot.synced_at < self.ttl
