"""Voice-sized answers for the MCP tools (pure functions, unit-tested).

Nova speaks every reply aloud, so tool results are compact and each has a `speak` field:
one or two short sentences the brain can say as is. Details stay behind explicit asks
(gmail_get_message(full=true), the `more` block of research_company).
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
_EVENT = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


# ---------------- names ----------------

def short_course(code: str | None) -> str:
    m = _CODE.search(code or "")
    return f"{m.group(1)} {m.group(2)}" if m else (code or "")[:12]


def short_title(title: str | None) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    t = _NOISE.sub("", t)
    m = _KIND.match(t)
    if m:
        kind = "discussion" if m.group(1).lower().startswith("discussion") else m.group(1).lower()
        head = re.split(r"\s+[-–—]\s+", m.group(2))[0].strip()
        return f"{head} {kind}"
    m = _NUMBERED.search(t)
    if m:
        word = m.group(1) if m.group(1).isupper() else m.group(1).title()
        return f"{word} {m.group(2)}"
    t = _PAREN.sub("", t)
    return " ".join(t.split()[:5])[:40].rstrip(" -:,")


def short_event_title(title: str | None) -> str:
    """'[BMI/BME/CEN/CSE507-494] Demo 3: 2D+3D and EHR (due)' -> 'CSE 507 Demo 3 due'."""
    t = (title or "").strip()
    m = _EVENT.match(t)
    if not m:
        return cut(t, 50)
    rest = re.sub(r"\s*\(due\)\s*$", "", m.group(2))
    due = " due" if rest != m.group(2) else ""
    return f"{short_course(m.group(1))} {short_title(rest)}{due}"


def cut(text: str, n: int) -> str:
    """Cut at a word boundary, no ellipsis (it is spoken aloud)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(" -:,;.") or text[:n]


def short_sender(name: str | None, email: str | None = "") -> str:
    n = re.sub(r"\s+via\s+.+$", "", name or "", flags=re.I)
    n = re.sub(r"<[^>]*>", "", n).strip(" \"'")
    if not n or "@" in n:
        n = (email or "").split("@")[0].replace(".", " ").replace("_", " ").title()
    return " ".join(n.split()[:3])


def short_subject(subject: str | None, n: int = 55) -> str:
    s = re.sub(r"^(\s*(re|fwd?|fw):\s*)+", "", subject or "", flags=re.I)
    return cut(s, n)


# ---------------- time ----------------

def _clock(d: datetime) -> str:
    return d.strftime("%I:%M %p").lstrip("0").replace(":00", "")


def day_label(d: datetime, now: datetime) -> str:
    days = (d.date() - now.date()).days
    if days < 0:
        return f"{d:%b} {d.day}"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < 7:
        return f"{d:%A}"
    return f"{d:%b} {d.day}"


def when_label(dt: datetime, now: datetime | None = None, tz: ZoneInfo = PHX,
               all_day: bool = False) -> str:
    """'today 3 PM' / 'tomorrow 9:30 AM' / 'Monday 11:59 PM' / 'Nov 22 3 PM'."""
    now = (now or datetime.now(tz)).astimezone(tz)
    d = dt.astimezone(tz)
    day = day_label(d, now)
    return day if all_day else f"{day} {_clock(d)}"


def ago(dt: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(dt.tzinfo)
    s = (now - dt).total_seconds()
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} minutes ago"
    if s < 86400:
        h = int(s // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = int(s // 86400)
    return "yesterday" if d == 1 else f"{d} days ago"


def window_label(start: datetime, end: datetime, now: datetime | None = None,
                 tz: ZoneInfo = PHX) -> str:
    """'tomorrow 2 to 5 PM' / 'today 9 AM to 12 PM'."""
    now = (now or datetime.now(tz)).astimezone(tz)
    s, e = start.astimezone(tz), end.astimezone(tz)
    a, b = _clock(s), _clock(e)
    if a.split()[-1] == b.split()[-1]:
        a = a.rsplit(" ", 1)[0]
    return f"{day_label(s, now)} {a} to {b}"


def join_words(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


# ---------------- email ----------------

def compact_email(e, now: datetime | None = None) -> dict:
    return {"id": e.id, "from": short_sender(e.from_name, e.from_email),
            "subject": short_subject(e.subject), "snippet": cut(e.snippet, 100),
            "category": e.category.value, "important": e.important,
            "needs_reply": e.needs_reply, "unread": e.unread, "when": ago(e.date, now)}


def _lead(e) -> str:
    return f"{short_sender(e.from_name, e.from_email)}, {short_subject(e.subject)}"


def speak_inbox(emails: list, hours: int) -> str:
    total = len(emails)
    window = f"in the last {hours} hours" if hours < 48 else f"in the last {hours // 24} days"
    if total == 0:
        return f"No mail {window}."
    imp = [e for e in emails if e.important]
    reply = sum(1 for e in emails if e.needs_reply)
    out = f"{len(imp)} important out of {total}." if imp else f"{total} emails, none important."
    if imp:
        out += f" Top: {_lead(imp[0])}."
    if reply:
        out += f" {plural(reply, 'email')} need{'s' if reply == 1 else ''} a reply."
    return out


def speak_new(emails: list) -> str:
    if not emails:
        return "No new mail."
    imp = [e for e in emails if e.important]
    out = f"{plural(len(emails), 'new email')}"
    out += f", {len(imp)} important: {_lead(imp[0])}." if imp else "."
    return out


def speak_search(emails: list) -> str:
    if not emails:
        return "I found nothing for that search."
    return f"Found {plural(len(emails), 'email')}. First: {_lead(emails[0])}."


# ---------------- calendar ----------------

def compact_event(ev, now: datetime | None = None) -> dict:
    return {"id": ev.id, "title": short_event_title(ev.title),
            "when": when_label(ev.start, now, all_day=ev.all_day), "calendar": ev.calendar}


def speak_events(events: list, days_ahead: int, now: datetime | None = None) -> str:
    window = "today" if days_ahead == 0 else (
        "this week" if days_ahead == 7 else f"in the next {days_ahead} days")
    if not events:
        return f"Nothing on your calendar {window}."
    first = events[0]
    return (f"{plural(len(events), 'event')} {window}. Next: {short_event_title(first.title)}, "
            f"{when_label(first.start, now, all_day=first.all_day)}.")


def speak_free(free: list, now: datetime | None = None) -> str:
    if not free:
        return "You have no free gaps in that range."
    labels = [window_label(b.start, b.end, now) for b in free[:3]]
    return f"You're free {join_words(labels)}."


def speak_sync(counts: dict, changes: list, applied: bool, failed_note: str = "",
               now: datetime | None = None) -> str:
    c, u, d = counts.get("create", 0), counts.get("update", 0), counts.get("delete", 0)
    if not (c or u or d):
        return "Your Nova calendar is already up to date."
    if applied:
        done = join_words([p for p in (f"added {c}" if c else "", f"updated {u}" if u else "",
                                       f"removed {d}" if d else "") if p])
        return f"Done. {done[0].upper()}{done[1:]} on your Nova calendar.{failed_note}"
    plan = join_words([p for p in (f"add {c}" if c else "", f"update {u}" if u else "",
                                   f"remove {d}" if d else "") if p])
    first = changes[0] if changes else None
    lead = (f" First: {short_event_title(first.title)}, "
            f"{when_label(first.start, now)}." if first and first.start else "")
    return f"I'd {plan} on your Nova calendar.{lead} Want me to do it?"
