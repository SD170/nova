"""Notification feed: meaningful events only (quiz ready, PDF saved, quiz score, ...).

The side panel / app polls GET /panel/feed?since=<last id>. Kept in memory and mirrored to
data/feed.json (last 100) so a restart does not lose them.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .quiz_models import FeedEvent

MAX_EVENTS = 100


class Feed:
    def __init__(self, path: Path):
        self.path = path
        self.events: list[FeedEvent] = []
        try:
            self.events = [FeedEvent(**e) for e in json.loads(path.read_text())]
        except (OSError, ValueError):
            self.events = []
        self._next = (self.events[-1].id + 1) if self.events else 1

    def post(self, kind: str, title: str, detail: str = "", data: dict | None = None) -> FeedEvent:
        ev = FeedEvent(id=self._next, at=datetime.now(timezone.utc), kind=kind, title=title,
                       detail=detail, data=data or {})
        self._next += 1
        self.events.append(ev)
        self.events = self.events[-MAX_EVENTS:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps([e.model_dump(mode="json") for e in self.events]))
            tmp.replace(self.path)
        except OSError:
            pass  # the in-memory feed still works
        return ev

    def since(self, last_id: int = 0, limit: int = 50) -> list[FeedEvent]:
        return [e for e in self.events if e.id > last_id][:limit]
