"""Student overrides: "I already did HW3" (POST /items/{id}/user-done).

Canvas is never written to. The override is kept in data/user_overrides.json
and re-applied after every sync, so the item does not pop back into the to-do
list every 30 minutes while Canvas still says "not submitted" (e.g. work handed
in on paper or another site).

An override is dropped automatically when:
  - Canvas itself now says submitted / excused / marked complete, or
  - the item's due date has passed, or
  - it is older than MAX_AGE_DAYS (safety net).
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Item

log = logging.getLogger(__name__)

MAX_AGE_DAYS = 30
USER_DONE_REASON = "Marked done by student (Canvas not updated yet)"


class OverrideStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, str]:
        """{item_id: marked_at ISO timestamp}"""
        if not self.path.exists():
            return {}
        try:
            return dict(json.loads(self.path.read_text()))
        except (ValueError, TypeError):
            log.warning("Corrupt %s, ignoring overrides", self.path)
            return {}

    def save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    def add(self, item_id: str) -> None:
        data = self.load()
        data[item_id] = datetime.now(timezone.utc).isoformat()
        self.save(data)

    def remove(self, item_id: str) -> bool:
        data = self.load()
        existed = data.pop(item_id, None) is not None
        if existed:
            self.save(data)
        return existed

    def apply(self, items: list[Item]) -> list[Item]:
        """Return items with overrides applied, and prune stale overrides."""
        data = self.load()
        if not data:
            return items
        now = datetime.now(timezone.utc)
        keep: dict[str, str] = {}
        out: list[Item] = []
        by_id = {i.id: i for i in items}

        for item_id, marked_at in data.items():
            item = by_id.get(item_id)
            too_old = now - datetime.fromisoformat(marked_at) > timedelta(days=MAX_AGE_DAYS)
            if too_old:
                continue
            if item is None:  # outside the sync window right now; keep for later
                keep[item_id] = marked_at
                continue
            canvas_done = item.submitted is True or item.todo_reason.startswith(
                ("Already submitted", "Excused", "Marked complete"))
            past_due = item.due_at is not None and item.due_at < now
            if canvas_done or past_due:
                continue  # Canvas caught up, or it no longer matters
            keep[item_id] = marked_at

        for item in items:
            if item.id in keep:
                item = mark(item)
            out.append(item)
        if keep != data:
            self.save(keep)
        return out


def mark(item: Item) -> Item:
    return item.model_copy(update={"in_todo": False, "user_done": True,
                                   "todo_reason": USER_DONE_REASON})
