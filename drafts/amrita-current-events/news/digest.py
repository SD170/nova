"""Build a personalized news digest from a student's interests.

An interest is {label, kind, query?, league?}:
  kind = "topic"   -> Google News search (politics, world, a hobby, a celebrity...)
  kind = "sports"  -> ESPN league feed (+ Google News search for a specific team)
  kind = "course"  -> Google News search on the course subject
  kind = "tech"    -> Hacker News (+ query if given)
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Optional

from . import sources

# Demo student until Canvas / memory provide the real profile. Courses mirror the
# mock courses in apps/voice/server.py.
DEFAULT_INTERESTS: list[dict] = [
    {"label": "US politics", "kind": "topic", "query": "Congress OR \"White House\" OR election"},
    {"label": "World", "kind": "topic", "section": "WORLD"},
    {"label": "Science", "kind": "topic", "section": "SCIENCE"},
    {"label": "ASU Sun Devils", "kind": "sports", "league": "college-football", "query": "Arizona State Sun Devils"},
    {"label": "NBA", "kind": "sports", "league": "nba"},
    {"label": "CSE 310 · Data Structures", "kind": "course", "query": "algorithms data structures computer science"},
    {"label": "MAT 243 · Discrete Math", "kind": "course", "query": "mathematics discovery"},
    {"label": "Tech", "kind": "tech"},
    {"label": "Higher education", "kind": "topic", "query": "college students higher education"},
]

MAX_INTERESTS = 15


def normalize(interests: Optional[list[dict]]) -> list[dict]:
    out = []
    for i in (interests or DEFAULT_INTERESTS)[:MAX_INTERESTS]:
        label = str(i.get("label") or i.get("query") or "").strip()[:80]
        if not label:
            continue
        kind = i.get("kind") if i.get("kind") in ("topic", "sports", "course", "tech") else "topic"
        out.append({"label": label, "kind": kind, "query": str(i.get("query") or label)[:120],
                    "league": i.get("league"), "section": i.get("section")})
    return out


def _fetchers(interest: dict, per_topic: int):
    label, kind, q = interest["label"], interest["kind"], interest["query"]
    if interest.get("section") in sources.GOOGLE_SECTIONS:
        yield sources.google_section(interest["section"], label, per_topic)
    elif kind == "sports":
        # A specific team ("Arizona State Sun Devils") → search for that team only.
        # A whole league ("NBA") → the ESPN league feed.
        is_whole_league = re.sub(r"[^a-z]+", "-", label.lower()).strip("-") == interest.get("league")
        if interest.get("league") in sources.ESPN_LEAGUES and is_whole_league:
            yield sources.espn_news(interest["league"], label, per_topic)
        else:
            yield sources.google_news(q, label, per_topic)
    elif kind == "tech":
        yield sources.hacker_news(label, "" if q == label else q, per_topic)
    else:
        yield sources.google_news(q, label, per_topic)
    if os.environ.get("NEWSAPI_KEY"):
        yield sources.newsapi(q, label, per_topic)


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:90]


async def build(interests: Optional[list[dict]] = None, per_topic: int = 5,
                since: Optional[str] = None) -> dict:
    ints = normalize(interests)
    jobs, owners = [], []
    for it in ints:
        for coro in _fetchers(it, per_topic):
            jobs.append(coro)
            owners.append(it["label"])
    results = await asyncio.gather(*jobs, return_exceptions=True)

    status: dict[str, dict] = {}
    seen: set[str] = set()
    items: list[sources.Item] = []
    for owner, res in zip(owners, results):
        st = status.setdefault(owner, {"topic": owner, "ok": False, "count": 0})
        if isinstance(res, BaseException):
            st.setdefault("error", "Source unavailable right now")
            continue
        st["ok"] = True
        for item in res:
            k = _key(item.title)
            if k in seen or item.url in seen:
                continue
            seen.update({k, item.url})
            items.append(item)
            st["count"] += 1

    # Newest first; cap each topic so one busy topic can't drown the rest.
    items.sort(key=lambda i: i.published_at or "", reverse=True)
    per: dict[str, int] = {}
    capped = []
    for i in items:
        per[i.topic] = per.get(i.topic, 0) + 1
        if per[i.topic] <= per_topic:
            capped.append(i)

    new = [i for i in capped if since and i.published_at and i.published_at > since]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "interests": ints,
        "items": [i.as_dict() for i in capped],
        "new_count": len(new),
        "sources": list(status.values()),
        "speak": spoken_digest(capped, ints),
    }


def spoken_digest(items: list[sources.Item], interests: list[dict], topics: int = 3) -> str:
    if not items:
        return "I couldn't find any new headlines for your interests right now."
    lines = []
    for it in interests:
        top = next((i for i in items if i.topic == it["label"]), None)
        if top:
            lines.append(f"In {it['label']}: {top.title}, from {top.source}.")
        if len(lines) >= topics:
            break
    return "Here's what's happening. " + " ".join(lines) + " Want me to read more on any of these?"
