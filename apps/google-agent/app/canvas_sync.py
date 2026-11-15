"""Canvas -> Calendar: pure planning logic + the small client for the Canvas service.

The Canvas service (apps/browser-agent, localhost:9001) already knows what is on the
student's to-do list. We read /items/next from it and make the Nova calendar match:
  - create an event for each to-do item / exam with a due time in the future,
  - update it if the due date, title or details changed,
  - remove it when the item was submitted, marked done, or disappeared from Canvas.
Events are keyed by the Canvas item id, so running it twice never duplicates anything.
"""

from datetime import datetime, timedelta, timezone

import httpx

from .models import CalendarEvent, CanvasUnavailable, EventSpec, SyncChange

WORK_MINUTES = 30      # assignments/quizzes: a 30-minute marker ending... starting at the due time
EXAM_MINUTES = 90
WORK_REMINDERS = [1440, 120]   # 1 day + 2 hours before
EXAM_REMINDERS = [2880, 1440]  # 2 days + 1 day before


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def wanted(item: dict, now: datetime) -> bool:
    """Should this Canvas item be on the calendar?"""
    due = _parse(item.get("due_at"))
    if not due or due < now:
        return False
    if item.get("user_done") or item.get("submitted"):
        return False
    return item.get("type") == "exam" or bool(item.get("in_todo"))


def to_spec(item: dict) -> EventSpec:
    due = _parse(item["due_at"])
    code = item.get("course_code") or ""
    title = item.get("title") or "Canvas item"
    is_exam = item.get("type") == "exam"
    prefix = f"[{code}] " if code else ""
    lines: list[str] = []
    if item.get("points") is not None:
        lines.append(f"Points: {item['points']:g}")
    steps = (item.get("what_to_do") or [])[:5]
    if steps:
        lines.append("What to do:\n" + "\n".join(f"- {s}" for s in steps))
    topics = item.get("topics") or []
    if topics:
        lines.append("Topics: " + ", ".join(topics))
    if item.get("source_url"):
        lines.append(f"Canvas: {item['source_url']}")
    lines.append("Added by Nova from Canvas.")
    return EventSpec(
        title=f"{prefix}{title}" if is_exam else f"{prefix}{title} (due)",
        start=due,
        end=due + timedelta(minutes=EXAM_MINUTES if is_exam else WORK_MINUTES),
        description="\n\n".join(lines),
        reminders_minutes=EXAM_REMINDERS if is_exam else WORK_REMINDERS,
        canvas_item_id=str(item["id"]),
    )


def desired_events(items: list[dict], now: datetime) -> dict[str, EventSpec]:
    return {str(i["id"]): to_spec(i) for i in items if wanted(i, now)}


def _differences(spec: EventSpec, ev: CalendarEvent) -> list[str]:
    diff = []
    if spec.title != ev.title:
        diff.append("title")
    if spec.start != ev.start or spec.end != ev.end:
        diff.append("time")
    if spec.description.strip() != ev.description.strip():
        diff.append("details")
    return diff


def plan(desired: dict[str, EventSpec], existing: list[CalendarEvent],
         now: datetime) -> list[tuple[SyncChange, str | None]]:
    """Diff -> [(change, existing_event_id_or_None)] ordered by start time."""
    by_item = {e.canvas_item_id: e for e in existing if e.canvas_item_id}
    out: list[tuple[SyncChange, str | None]] = []
    for item_id, spec in desired.items():
        ev = by_item.get(item_id)
        if ev is None:
            out.append((SyncChange(action="create", canvas_item_id=item_id, title=spec.title,
                                   start=spec.start, end=spec.end,
                                   reason="new item on your Canvas to-do list"), None))
            continue
        diff = _differences(spec, ev)
        if diff:
            out.append((SyncChange(action="update", canvas_item_id=item_id, title=spec.title,
                                   start=spec.start, end=spec.end,
                                   reason="changed in Canvas: " + ", ".join(diff)), ev.id))
        else:
            out.append((SyncChange(action="keep", canvas_item_id=item_id, title=spec.title,
                                   start=spec.start, end=spec.end, reason="already up to date"),
                        ev.id))
    for item_id, ev in by_item.items():
        if item_id in desired:
            continue
        if ev.start >= now:
            out.append((SyncChange(
                action="delete", canvas_item_id=item_id, title=ev.title, start=ev.start,
                end=ev.end, reason="no longer on your to-do list (submitted, marked done, "
                                   "or removed in Canvas)"), ev.id))
        # past events are left alone: they are history
    out.sort(key=lambda pair: pair[0].start or now)
    return out


def counts(changes: list[SyncChange]) -> dict[str, int]:
    c = {"create": 0, "update": 0, "delete": 0, "keep": 0}
    for ch in changes:
        c[ch.action] += 1
    return c


class CanvasClient:
    """Reads the to-do list from the Canvas service on this machine."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 20):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def items(self, days: int = 30) -> tuple[list[dict], dict]:
        headers = {"X-Canvas-Key": self.api_key} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/items/next", headers=headers,
                                        params={"days": days, "include_done": "true"})
        except httpx.HTTPError as exc:
            raise CanvasUnavailable(
                f"Could not reach the Canvas service at {self.base_url} ({exc}). "
                "Is apps/browser-agent running?") from exc
        if resp.status_code == 401:
            raise CanvasUnavailable("The Canvas service rejected our key (CANVAS_API_KEY).")
        if resp.status_code != 200:
            raise CanvasUnavailable(f"Canvas service returned HTTP {resp.status_code}.")
        data = resp.json()
        return data.get("items", []), {"data_source": data.get("data_source", ""),
                                       "synced_at": data.get("synced_at")}
