"""Voice-sized answers for the MCP tools (pure functions, unit-tested).

Nova speaks every reply aloud, so tool results must be small and already short:
  - course codes become "CSE 507" (Canvas has "BMI/BME/CEN/CSE507-494"),
  - item titles lose the noise ("Graded Quiz: Module 5 - Requires Respondus ..." -> "Module 5 quiz"),
  - due dates read like a person says them ("today 11:59 PM", "Monday 11:59 PM"),
  - every tool returns a `speak` field: one short sentence the brain can say as is.
REST endpoints are unchanged (full data for the UI); only MCP uses these helpers.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

PHX = ZoneInfo("America/Phoenix")

_CODE = re.compile(r"\b([A-Z]{2,4})\s?-?(\d{3})\b")
_NOISE = re.compile(r"\s*[-–—]\s*(requires|respondus|lockdown|webcam).*$", re.I)
_KIND = re.compile(r"^(?:graded\s+)?(quiz|discussion prompt|discussion|exam)\s*[:\-]\s*(.+)$", re.I)
_NUMBERED = re.compile(
    r"\b(Milestone|Demo|Assignment|Homework|HW|Lab|Quiz|Exam|Midterm|Final|Project|Report)"
    r"\s*#?(\d+)\b", re.I)
_PAREN = re.compile(r"\s*\([^)]{12,}\)")


def short_course(code: str | None) -> str:
    """'BMI/BME/CEN/CSE507-494' -> 'CSE 507'; 'CSE 540' stays."""
    m = _CODE.search(code or "")
    return f"{m.group(1)} {m.group(2)}" if m else (code or "")[:12]


def short_title(title: str | None) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    t = _NOISE.sub("", t)
    m = _KIND.match(t)
    if m:
        kind = "discussion" if m.group(1).lower().startswith("discussion") else m.group(1).lower()
        rest = re.split(r"\s+[-–—]\s+", m.group(2))[0].strip()
        return f"{rest} {kind}"
    m = _NUMBERED.search(t)
    if m:
        word = m.group(1) if m.group(1).isupper() else m.group(1).title()
        return f"{word} {m.group(2)}"
    t = _PAREN.sub("", t)
    return " ".join(t.split()[:5])[:40].rstrip(" -:,")


def due_label(due: datetime | None, now: datetime | None = None, tz: ZoneInfo = PHX) -> str:
    """'today 11:59 PM' / 'tomorrow 11:59 PM' / 'Monday 11:59 PM' / 'Nov 28'."""
    if not due:
        return "no due date"
    now = (now or datetime.now(tz)).astimezone(tz)
    d = due.astimezone(tz)
    days = (d.date() - now.date()).days
    clock = d.strftime("%I:%M %p").lstrip("0")
    if days < 0:
        return f"overdue since {d:%b} {d.day}"
    if days == 0:
        return f"today {clock}"
    if days == 1:
        return f"tomorrow {clock}"
    if days < 7:
        return f"{d:%A} {clock}"
    return f"{d:%b} {d.day}"


def join_words(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def compact_item(item, now: datetime | None = None) -> dict:
    return {"id": item.id, "course": short_course(item.course_code),
            "title": short_title(item.title), "due": due_label(item.due_at, now),
            "points": item.points, "type": item.type.value, "source_url": item.source_url}


def speak_todo(items: list, days: int, now: datetime | None = None) -> str:
    n = len(items)
    window = "this week" if days == 7 else f"in the next {days} days"
    if n == 0:
        return f"Nothing due {window}."
    now_l = (now or datetime.now(PHX)).astimezone(PHX)
    today = sum(1 for i in items if i.due_at and i.due_at.astimezone(PHX).date() == now_l.date())
    head = f"{_plural(n, 'thing')} due {window}" + (f", {today} today" if today else "") + "."
    first = items[0]
    return (f"{head} First: {short_title(first.title)} for {short_course(first.course_code)}, "
            f"{due_label(first.due_at, now)}.")


def speak_item(item, now: datetime | None = None) -> str:
    pts = f", {item.points:g} points" if item.points else ""
    out = (f"{short_title(item.title)} for {short_course(item.course_code)}, "
           f"due {due_label(item.due_at, now)}{pts}.")
    if item.what_to_do:
        step = item.what_to_do[0].strip()
        out += f" First step: {step[:90]}"
        out += "." if not step.endswith((".", "!", "?")) else ""
    return out


def speak_courses(courses: list) -> str:
    codes = [short_course(c.code) for c in courses]
    return f"You're taking {join_words(codes)}." if codes else "No current courses found."
