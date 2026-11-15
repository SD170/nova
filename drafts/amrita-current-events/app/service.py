"""NewsService — everything the tools do. Routes in main.py stay thin.

Reads never block for long (same pattern as browser-agent):
  fresh cache (< NEWS_CACHE_TTL_MINUTES) -> answer instantly
  stale cache                            -> answer instantly AND refresh in the background
  nothing cached yet                     -> fetch now (~1-3 s, every source runs in parallel)
"""
from __future__ import annotations

import asyncio
import re
import time
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from . import digest, extract, outlets, sources
from .config import settings
from .models import (Cluster, DedupeIn, DedupeOut, ItemDetail, NewsItem, NewsOut, Topic, TopicsOut,
                     TopicStatus)

# Friendly names -> section ids
ALIASES = {
    "top": "top", "headlines": "top", "top stories": "top", "breaking": "top", "news": "top",
    "politics": "politics", "us politics": "politics", "election": "politics", "elections": "politics",
    "world": "world", "international": "world", "global": "world",
    "science": "science", "tech": "tech", "technology": "tech",
    "education": "education", "college": "education", "higher education": "education",
    "sports": "sports", "sport": "sports",
    "business": "business", "economy": "business", "finance": "business", "markets": "business",
    "health": "health", "medicine": "health",
}
SECTION_LABELS = {"top": "Top stories", "politics": "US politics", "world": "World", "science": "Science",
                  "tech": "Tech", "education": "Education", "sports": "Sports", "business": "Business",
                  "health": "Health"}
EXAMPLES = ["world, politics, tech", "Phoenix Suns, NBA, ASU football", "AI policy, climate, student loans",
            "machine learning, data structures"]


def parse_topics(topics: Union[str, list[str], None]) -> list[dict]:
    """'world, Phoenix Suns , AI' -> interests. Sections map to newsroom feeds; anything else is a search."""
    raw = topics.split(",") if isinstance(topics, str) else (topics or [])
    out, seen = [], set()
    for t in raw:
        t = re.sub(r"\s+", " ", str(t)).strip()[:80]
        if not t:
            continue
        sec = ALIASES.get(t.lower())
        entry = ({"label": SECTION_LABELS[sec], "kind": "section", "section": sec} if sec
                 else {"label": t, "kind": "topic", "query": t})
        if entry["label"].lower() in seen:  # "tech, technology" -> one Tech section
            continue
        seen.add(entry["label"].lower())
        out.append(entry)
    return out[:20]


MIN_TODAY_HOURS = 2  # just after midnight "today" is nearly empty, so show at least the last 2 hours


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def news_window(since_hours: Optional[int] = None, tz_offset_minutes: Optional[int] = None,
                now: Optional[datetime] = None) -> dict:
    """'today' = since midnight in the student's timezone; or a rolling 'last N hours' window."""
    now = now or datetime.now(timezone.utc)
    if since_hours:
        h = max(1, min(int(since_hours), 72))
        return {"start": _z(now - timedelta(hours=h)), "hours": h, "label": f"last {h} hours", "key": ("h", h)}
    off = settings.tz_offset_minutes if tz_offset_minutes is None else max(-840, min(int(tz_offset_minutes), 840))
    local = now.astimezone(timezone(timedelta(minutes=off)))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if local - midnight < timedelta(hours=MIN_TODAY_HOURS):
        return {"start": _z(now - timedelta(hours=MIN_TODAY_HOURS)), "hours": MIN_TODAY_HOURS,
                "label": f"last {MIN_TODAY_HOURS} hours (just after midnight)", "key": ("m", off, local.date().isoformat())}
    return {"start": _z(midnight), "hours": max(1, math.ceil((now - midnight).total_seconds() / 3600)),
            "label": f"today ({local.date().isoformat()})", "key": ("t", off, local.date().isoformat())}


class NewsService:
    def __init__(self) -> None:
        self._cache: dict[tuple, tuple[float, NewsOut]] = {}
        self._index: dict[str, NewsItem] = {}
        self._refreshing: set[tuple] = set()

    # ───────────────────────── tool: get_available_topics ─────────────────────────
    def available_topics(self) -> TopicsOut:
        return TopicsOut(
            sections=[Topic(id=s, label=SECTION_LABELS[s], kind="section", outlets=[n for n, _ in outlets.FEEDS[s]])
                      for s in outlets.FEEDS],
            custom_topics="Anything else (a team, a person, a course subject, a hobby) is searched across the news "
                          "and filtered to trusted newsrooms.",
            examples=EXAMPLES,
        )

    # ───────────────────────── tool: fetch_news ─────────────────────────
    async def fetch_news(self, topics: Union[str, list[str], None], since_hours: Optional[int] = None,
                         trusted_only: bool = True, per_topic: int = 5, live: bool = False,
                         tz_offset_minutes: Optional[int] = None) -> NewsOut:
        """Default window is TODAY in the student's timezone (since local midnight), newest first.
        since_hours=N switches to a rolling 'last N hours' window.
        live=True: wait for a fresh fetch (nothing older than sources.LIVE_SECONDS) instead of serving cache."""
        interests = parse_topics(topics) or parse_topics("top")
        win = news_window(since_hours, tz_offset_minutes)
        per = max(1, min(per_topic, settings.per_topic_max))
        key = (tuple(sorted(i["label"].lower() for i in interests)), win["key"], trusted_only, per)
        hit = self._cache.get(key)
        if live:
            if hit and time.time() - hit[0] < sources.LIVE_SECONDS:
                return hit[1]
            sources.MAX_AGE.set(sources.LIVE_SECONDS)
            return await self._refresh(key, interests, win, trusted_only, per)
        if hit:
            age = time.time() - hit[0]
            if age < settings.cache_ttl_minutes * 60:
                return hit[1]
            if key not in self._refreshing:
                self._refreshing.add(key)
                asyncio.create_task(self._refresh(key, interests, win, trusted_only, per))
            return hit[1]
        return await self._refresh(key, interests, win, trusted_only, per)

    async def _refresh(self, key, interests, win, trusted_only, per) -> NewsOut:
        try:
            d = await digest.build(interests, per_topic=per, window_hours=win["hours"], trusted_only=trusted_only,
                                   cutoff=win["start"])
            now = datetime.now(timezone.utc)
            items = []
            for i in d["items"]:
                item = NewsItem(**{k: v for k, v in i.items() if k in NewsItem.model_fields})
                if item.published_at:
                    pub = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
                    item.age_minutes = max(0, int((now - pub).total_seconds() // 60))
                items.append(item)
            out = NewsOut(
                generated_at=d["generated_at"], topics=[i["label"] for i in interests], since_hours=win["hours"],
                window=win["label"], window_start=win["start"],
                trusted_only=trusted_only, count=len(items), links=[i.url for i in items], items=items,
                by_topic=[TopicStatus(topic=s["topic"], kind=next((i["kind"] for i in interests if i["label"] == s["topic"]), "topic"),
                                      ok=s["ok"], count=s["count"], providers=s["providers"]) for s in d["sources"]],
                speak=d["speak"],
            )
            for it in items:
                self._index[it.id] = it
            if len(self._index) > 5000:  # keep memory bounded
                for k in list(self._index)[:1000]:
                    self._index.pop(k, None)
            self._cache[key] = (time.time(), out)
            return out
        finally:
            self._refreshing.discard(key)

    # ───────────────────────── tool: get_news_item ─────────────────────────
    async def get_item(self, item_id: str) -> Optional[ItemDetail]:
        item = self._index.get(item_id)
        if not item:
            return None
        text, note = await extract.article_text(item.url)
        return ItemDetail(**item.model_dump(), text=text, text_available=bool(text), text_note=note)

    # ───────────────────────── tool: dedupe_news ─────────────────────────
    def dedupe(self, items: list[DedupeIn]) -> DedupeOut:
        groups: list[dict] = []
        for it in items:
            toks = digest._tokens(it.title)
            for g in groups:
                if digest._same_story(toks, g["tokens"]):
                    g["items"].append(it)
                    g["tokens"] |= toks
                    break
            else:
                groups.append({"tokens": set(toks), "items": [it]})
        clusters = []
        for g in groups:
            m = g["items"]
            srcs = list(dict.fromkeys(i.source for i in m if i.source))
            lead = sorted(m, key=lambda i: (not outlets.is_trusted(i.source), -(len(i.published_at or ""))))[0]
            clusters.append(Cluster(lead_id=lead.id, ids=[i.id for i in m], sources=srcs,
                                    outlets=max(1, len(srcs)), confirmed=len(srcs) >= 2))
        return DedupeOut(clusters=clusters)

    def cached_stories(self) -> int:
        return len(self._index)


service = NewsService()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
