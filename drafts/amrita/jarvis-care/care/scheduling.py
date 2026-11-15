"""Free-time suggestions for a follow-up visit.

These are the student's *own free windows*, not clinic availability. Sources:
- availability windows the user typed in (permittedContext.availability), or
- the bundled demo schedule for "Sam" (only when the user opts in).
No real calendar is read and nothing is booked.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional

from .models import TimeWindow

DEMO_SCHEDULE = Path(__file__).parent / "samples" / "schedule_sam.json"
# Fixed "today" so the demo is deterministic.
DEMO_TODAY = date(2026, 11, 14)
DAY_START, DAY_END = time(9, 0), time(17, 0)
MIN_MINUTES = 60


@dataclass
class Slot:
    start: datetime
    end: datetime

    def label(self) -> str:
        def t(d: datetime) -> str:
            return d.strftime("%I:%M %p").lstrip("0")
        return f"{self.start.strftime('%A, %B')} {self.start.day}, {t(self.start)} to {t(self.end)}"

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label()}


def load_demo_schedule() -> dict:
    return json.loads(DEMO_SCHEDULE.read_text(encoding="utf-8"))


def next_week(today: date = DEMO_TODAY) -> tuple[date, date]:
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return monday, monday + timedelta(days=4)


def _subtract(window: Slot, busy: Iterable[Slot]) -> list[Slot]:
    free = [window]
    for b in sorted(busy, key=lambda s: s.start):
        nxt: list[Slot] = []
        for f in free:
            if b.end <= f.start or b.start >= f.end:
                nxt.append(f)
                continue
            if b.start > f.start:
                nxt.append(Slot(f.start, b.start))
            if b.end < f.end:
                nxt.append(Slot(b.end, f.end))
        free = nxt
    return free


def suggest_from_schedule(schedule: dict, avoid_exam_days: bool, limit: int = 3) -> tuple[list[Slot], list[str]]:
    start_day, end_day = next_week()
    events = [
        (Slot(datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])), e)
        for e in schedule.get("events", [])
    ]
    exam_days = {s.start.date() for s, e in events if e.get("kind") == "exam"}
    notes = []
    if avoid_exam_days and exam_days:
        notes.append("I skipped " + ", ".join(sorted(d.strftime("%A") for d in exam_days)) + " because of your exam.")
    slots: list[Slot] = []
    day = start_day
    while day <= end_day:
        if not (avoid_exam_days and day in exam_days):
            window = Slot(datetime.combine(day, DAY_START), datetime.combine(day, DAY_END))
            busy = [s for s, _ in events if s.start.date() == day]
            for f in _subtract(window, busy):
                if (f.end - f.start) >= timedelta(minutes=MIN_MINUTES):
                    slots.append(f)
                    break  # one suggestion per day keeps the list short
        day += timedelta(days=1)
    return slots[:limit], notes


def suggest_from_windows(windows: list[TimeWindow], limit: int = 3) -> list[Slot]:
    out: list[Slot] = []
    for w in windows:
        try:
            s, e = datetime.fromisoformat(w.start), datetime.fromisoformat(w.end)
        except ValueError:
            continue
        if e - s >= timedelta(minutes=MIN_MINUTES):
            out.append(Slot(s, e))
    return sorted(out, key=lambda s: s.start)[:limit]


def deadlines(schedule: Optional[dict] = None) -> list[dict]:
    schedule = schedule or load_demo_schedule()
    return schedule.get("deadlines", [])
