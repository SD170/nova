"""ASU events from ASU's own public feeds (no key exists for students — these are what ASU publishes openly).

  ASU Events calendar   https://asuevents.asu.edu/feed-json
      official university calendar: talks, arts, athletics, Barrett, career fairs, ... (~500 upcoming)
  Sun Devil Central     https://sundevilcentral.eoss.asu.edu/mobile_ws/v17/mobile_events_list
      (CampusGroups, a.k.a. SunDevilSync) student-organization events. The CampusGroups
      Data Export API needs an admin-only X-CG-API-Secret, so we read the same public
      list the Sun Devil Central website shows logged-out visitors.

Every event links to its official page. Times are converted to UTC ISO-8601 (Arizona is UTC-7, no DST).
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .sources import client

ASU_EVENTS_URL = "https://asuevents.asu.edu/feed-json"
SDC_BASE = "https://sundevilcentral.eoss.asu.edu"
SDC_URL = f"{SDC_BASE}/mobile_ws/v17/mobile_events_list"
AZ = timezone(timedelta(hours=-7))
CACHE_SECONDS = 30 * 60
MAX_SPAN = timedelta(days=2)   # longer "events" are semester-long recurring meetings, not things to attend
_cache: dict[str, tuple[float, list[dict]]] = {}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if dt else None


async def _get_json(key: str, url: str, params: Optional[dict] = None):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    async with client() as c:
        r = await c.get(url, params=params, headers={"User-Agent": "Mozilla/5.0 (StudentJarvis events reader)"},
                        timeout=30)
    r.raise_for_status()
    data = r.json()
    _cache[key] = (time.time(), data)
    return data


def clear_cache() -> None:
    _cache.clear()


# ───────────────────────── ASU Events (official calendar) ─────────────────────────

def _parse_utc(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


async def asu_calendar() -> list[dict]:
    data = await _get_json("asuevents", ASU_EVENTS_URL)
    out = []
    for wrap in data.get("nodes", []):
        n = wrap.get("node", {})
        start, end = _parse_utc(n.get("very_start_date", "")), _parse_utc(n.get("very_end_date", ""))
        if not (n.get("title") and n.get("alias") and start):
            continue
        location = ", ".join(x for x in (_clean(n.get("locations", "")), _clean(n.get("venue_address", ""))) if x)
        out.append({
            "id": f"asuevents-{n.get('nid')}",
            "title": _clean(n["title"]),
            "starts_at": _iso(start), "ends_at": _iso(end),
            "when_text": n.get("start_date", ""),
            "campus": _clean(n.get("campus", "")),
            "location": location,
            "host": _clean(n.get("college_unit", "") or n.get("department", "")).split(",")[0],
            "category": _clean(n.get("event_types", "")),
            "interests": [x.strip() for x in _clean(n.get("interests", "")).split("|") if x.strip()],
            "cost": _clean(n.get("asu_events_price_desc", "") or n.get("event_price_level", "")),
            "summary": _clean(n.get("body_summary", ""))[:300],
            "url": n["alias"],
            "rsvp_url": n.get("ticketing_rsvp_url") or None,
            "source": "ASU Events",
            "data_source": "live",
        })
    return out


# ───────────────────────── Sun Devil Central (student orgs) ─────────────────────────

SDC_DATE = re.compile(r"[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{1,2}, \d{4})(?: (\d{1,2}:\d{2} [AP]M))?")


def _sdc_dates(html_dates: str) -> tuple[Optional[datetime], Optional[datetime]]:
    found = SDC_DATE.findall(_clean(html_dates))
    parsed = []
    for day, t in found:
        try:
            parsed.append(datetime.strptime(f"{day} {t or '12:00 AM'}", "%b %d, %Y %I:%M %p").replace(tzinfo=AZ))
        except ValueError:
            continue
    if not parsed:
        return None, None
    start = parsed[0]
    end = parsed[1] if len(parsed) > 1 else start
    if end < start and len(found) > 1 and not found[1][0]:  # "7 PM – 9 PM" same day
        end = start
    return start, end


async def sun_devil_central(limit: int = 300) -> list[dict]:
    rows = await _get_json(f"sdc:{limit}", SDC_URL, {"range": 0, "limit": limit})
    out = []
    for row in rows or []:
        fields = (row.get("fields") or "").rstrip(",").split(",")
        r = {f: row.get(f"p{i}") for i, f in enumerate(fields)}
        if not r.get("eventName") or not r.get("eventUrl"):
            continue
        start, end = _sdc_dates(r.get("eventDates") or "")
        if not start:
            continue
        out.append({
            "id": f"sdc-{r.get('eventId')}",
            "title": _clean(r["eventName"]),
            "starts_at": _iso(start), "ends_at": _iso(end),
            "when_text": _clean(r.get("eventDates") or ""),
            "campus": "",
            "location": _clean(r.get("eventLocation") or ""),
            "host": _clean(r.get("clubName") or ""),
            "category": _clean(r.get("eventCategory") or ""),
            "interests": re.findall(r'aria-label="([^"]+)"', r.get("eventTags") or ""),
            "cost": "Free" if (r.get("eventPriceRange") or "").strip() in ("", "0", "Free") else _clean(r.get("eventPriceRange")),
            "summary": "",
            "url": SDC_BASE + r["eventUrl"],
            "rsvp_url": SDC_BASE + r["eventUrl"],
            "source": "Sun Devil Central",
            "data_source": "live",
            "_span": (end - start) if end else timedelta(0),
        })
    return out


# ───────────────────────── tool: fetch_asu_events ─────────────────────────

def _matches(ev: dict, words: list[str]) -> bool:
    blob = " ".join([ev["title"], ev["summary"], ev["host"], ev["category"], ev["location"], ev["campus"],
                     " ".join(ev["interests"])]).lower()
    return all(w in blob for w in words)


async def fetch(days: int = 7, query: str = "", campus: str = "", limit: int = 25,
                now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(days=days)
    import asyncio
    results = await asyncio.gather(asu_calendar(), sun_devil_central(), return_exceptions=True)
    sources, pool = [], []
    for name, res in zip(("ASU Events", "Sun Devil Central"), results):
        if isinstance(res, BaseException):
            sources.append({"source": name, "ok": False, "count": 0})
            continue
        kept = 0
        for ev in res:
            span = ev.pop("_span", None)
            start = _parse_utc(ev["starts_at"])
            end = _parse_utc(ev["ends_at"]) or start
            if span is not None and span > MAX_SPAN:
                continue  # semester-long recurring listing
            if not (now <= start <= horizon or (start < now <= end)):
                continue
            pool.append(ev)
            kept += 1
        sources.append({"source": name, "ok": True, "count": kept})

    words = [w for w in re.split(r"[\s,]+", query.lower()) if len(w) > 1]
    campus_l = campus.lower().strip()
    items = [e for e in pool if (not words or _matches(e, words))
             and (not campus_l or campus_l in e["campus"].lower() or campus_l in e["location"].lower())]
    items.sort(key=lambda e: e["starts_at"])
    seen, unique = set(), []
    for e in items:  # same event listed by both sources
        k = (re.sub(r"\W+", "", e["title"].lower()), e["starts_at"][:13])
        if k not in seen:
            seen.add(k)
            unique.append(e)
    unique = unique[:limit]

    if unique:
        first = unique[0]
        speak = (f"I found {len(unique)} ASU event{'s' if len(unique) != 1 else ''}"
                 f"{' about ' + query if query else ''} in the next {days} days. The next one is {first['title']}"
                 f"{', ' + first['host'] if first['host'] else ''}.")
    else:
        speak = f"I couldn't find ASU events{' about ' + query if query else ''} in the next {days} days."
    return {
        "generated_at": _iso(now), "days": days, "query": query, "campus": campus,
        "data_source": "live", "count": len(unique), "links": [e["url"] for e in unique],
        "items": unique, "sources": sources, "speak": speak,
    }
