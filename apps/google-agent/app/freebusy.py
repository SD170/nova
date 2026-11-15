"""Free time = the gaps between busy blocks, inside waking hours. Pure, unit-tested."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Block


def compute_free(busy: list[Block], range_start: datetime, range_end: datetime, tz: ZoneInfo,
                 min_minutes: int = 30, day_start: int = 8, day_end: int = 22) -> list[Block]:
    """Gaps >= min_minutes between day_start and day_end (local time), never in the past."""
    merged: list[Block] = []
    for b in sorted(busy, key=lambda b: b.start):
        if merged and b.start <= merged[-1].end:
            if b.end > merged[-1].end:
                merged[-1] = Block(start=merged[-1].start, end=b.end)
        else:
            merged.append(Block(start=b.start, end=b.end))

    free: list[Block] = []
    day = range_start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    last_day = range_end.astimezone(tz)
    while day <= last_day:
        win_start = max(day.replace(hour=day_start), range_start.astimezone(tz))
        win_end = min(day.replace(hour=day_end), range_end.astimezone(tz))
        cursor = win_start
        for b in merged:
            if b.end <= cursor or b.start >= win_end:
                continue
            if b.start > cursor and (b.start - cursor) >= timedelta(minutes=min_minutes):
                free.append(Block(start=cursor, end=b.start))
            cursor = max(cursor, b.end)
        if win_end > cursor and (win_end - cursor) >= timedelta(minutes=min_minutes):
            free.append(Block(start=cursor, end=win_end))
        day = (day + timedelta(days=1)).replace(hour=0, minute=0)
    return free
