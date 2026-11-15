"""News sources. Everything here works with NO API key:

- Google News RSS search  — any topic: politics, a team, a course subject, a hobby
- ESPN public news JSON   — sports leagues (college football, NBA, ...)
- Hacker News (Algolia)   — tech / CS headlines

Optional keyed source, used only if a key is present in .env:
- NewsAPI.org (NEWSAPI_KEY)

Every item carries its source URL so Jarvis can always cite where a headline came from.
"""
from __future__ import annotations

import asyncio
import contextvars
import email.utils
import weakref
import hashlib
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

# Tests swap this for an httpx.MockTransport.
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None
UA = {"User-Agent": "StudentJarvis-News/0.1 (+hackathon project)"}

ESPN_LEAGUES = {
    "college-football": "football/college-football",
    "nfl": "football/nfl",
    "nba": "basketball/nba",
    "college-basketball": "basketball/mens-college-basketball",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "soccer": "soccer/eng.1",
}


@dataclass
class Item:
    title: str
    url: str
    source: str
    published_at: Optional[str]  # ISO 8601 UTC
    topic: str
    provider: str
    summary: str = ""
    id: str = field(default="")

    def __post_init__(self):
        if not self.id:
            self.id = hashlib.sha1(self.url.encode()).hexdigest()[:12]

    def as_dict(self) -> dict:
        return self.__dict__.copy()


_CLIENTS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


class _SharedClient:
    """One pooled AsyncClient per event loop. Creating a client per request costs
    a full TLS setup each time (44 feeds: ~69s vs ~10s pooled)."""

    async def __aenter__(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        per_loop = _CLIENTS.setdefault(loop, {})
        key = id(TRANSPORT)
        c = per_loop.get(key)
        if c is None or c.is_closed:
            c = httpx.AsyncClient(timeout=httpx.Timeout(10, connect=6), headers=UA, transport=TRANSPORT,
                                  follow_redirects=True, limits=httpx.Limits(max_connections=48))
            per_loop[key] = c
        return c

    async def __aexit__(self, *exc) -> bool:
        return False  # keep the pool open for the next request


def client() -> _SharedClient:
    return _SharedClient()


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


# Small in-memory cache so a page refresh doesn't hammer free public services.
_CACHE: dict[str, tuple[float, list[Item]]] = {}
CACHE_SECONDS = 300
LIVE_SECONDS = 60  # live=true: nothing older than this, but still protects sources from a fast-polling UI
# Set to LIVE_SECONDS for the duration of a live request (copied into every gathered task).
MAX_AGE: contextvars.ContextVar[int] = contextvars.ContextVar("news_max_age", default=CACHE_SECONDS)


async def _cached(key: str, fetch) -> list[Item]:
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < min(CACHE_SECONDS, MAX_AGE.get()):
        return hit[1]
    items = await fetch()
    _CACHE[key] = (time.time(), items)
    return items


def clear_cache() -> None:
    _CACHE.clear()


async def google_news(query: str, topic: str, limit: int = 6, when: str = "7d") -> list[Item]:
    """`when` limits Google News to recent stories (1d = today). Results are relevance-ordered."""
    async def fetch() -> list[Item]:
        q = urllib.parse.quote_plus(f"{query} when:{when}")
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        async with client() as c:
            r = await c.get(url)
        r.raise_for_status()
        return _parse_rss(r.content, topic, limit)
    return await _cached(f"gn:{query}:{limit}:{when}", fetch)


GOOGLE_SECTIONS = ("WORLD", "NATION", "BUSINESS", "TECHNOLOGY", "ENTERTAINMENT", "SPORTS", "SCIENCE", "HEALTH")


def _parse_rss(content: bytes, topic: str, limit: int) -> list[Item]:
    root = ET.fromstring(content)
    out: list[Item] = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else "Google News"
        # Google appends " - Publisher" to titles; drop it since we show the source separately.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        pub = it.findtext("pubDate")
        dt = email.utils.parsedate_to_datetime(pub) if pub else None
        if title and link:
            out.append(Item(title=title, url=link, source=source, published_at=_iso(dt),
                            topic=topic, provider="Google News"))
        if len(out) >= limit:
            break
    return out


async def google_section(section: str, topic: str, limit: int = 6) -> list[Item]:
    """Google News top stories for a section (WORLD, SCIENCE, ...)."""
    async def fetch() -> list[Item]:
        url = f"https://news.google.com/rss/headlines/section/topic/{section}?hl=en-US&gl=US&ceid=US:en"
        async with client() as c:
            r = await c.get(url)
        r.raise_for_status()
        return _parse_rss(r.content, topic, limit)
    return await _cached(f"gs:{section}:{limit}", fetch)


async def espn_news(league: str, topic: str, limit: int = 6) -> list[Item]:
    path = ESPN_LEAGUES.get(league, league)

    async def fetch() -> list[Item]:
        async with client() as c:
            r = await c.get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/news", params={"limit": limit})
        r.raise_for_status()
        out: list[Item] = []
        for a in r.json().get("articles", [])[:limit]:
            link = ((a.get("links") or {}).get("web") or {}).get("href")
            if not (a.get("headline") and link):
                continue
            pub = a.get("published")
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None
            out.append(Item(title=a["headline"], url=link, source="ESPN", published_at=_iso(dt),
                            topic=topic, provider="ESPN",
                            summary=(a.get("description") or "").lstrip("—–- ").strip()))
        return out
    return await _cached(f"espn:{path}:{limit}", fetch)


async def hacker_news(topic: str, query: str = "", limit: int = 6) -> list[Item]:
    async def fetch() -> list[Item]:
        params = {"tags": "story", "hitsPerPage": limit}
        if query:
            params["query"] = query
            params["numericFilters"] = f"created_at_i>{int(time.time()) - 7 * 86400}"
            endpoint = "https://hn.algolia.com/api/v1/search"
        else:
            params["tags"] = "front_page"
            endpoint = "https://hn.algolia.com/api/v1/search"
        async with client() as c:
            r = await c.get(endpoint, params=params)
        r.raise_for_status()
        out: list[Item] = []
        for h in r.json().get("hits", [])[:limit]:
            link = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            if not h.get("title"):
                continue
            dt = datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc) if h.get("created_at_i") else None
            out.append(Item(title=h["title"], url=link, source="Hacker News", published_at=_iso(dt),
                            topic=topic, provider="Hacker News"))
        return out
    return await _cached(f"hn:{query}:{limit}", fetch)


async def newsapi(query: str, topic: str, limit: int = 6) -> list[Item]:
    """Only used when NEWSAPI_KEY is set. Key stays server-side."""
    key = os.environ.get("NEWSAPI_KEY")
    if not key:
        return []

    async def fetch() -> list[Item]:
        async with client() as c:
            r = await c.get("https://newsapi.org/v2/everything",
                            params={"q": query, "pageSize": limit, "sortBy": "publishedAt", "language": "en"},
                            headers={"X-Api-Key": key})
        r.raise_for_status()
        out = []
        for a in r.json().get("articles", [])[:limit]:
            if not (a.get("title") and a.get("url")):
                continue
            pub = a.get("publishedAt")
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None
            out.append(Item(title=a["title"], url=a["url"], source=(a.get("source") or {}).get("name") or "NewsAPI",
                            published_at=_iso(dt), topic=topic, provider="NewsAPI",
                            summary=_strip_html(a.get("description") or "")))
        return out
    return await _cached(f"newsapi:{query}:{limit}", fetch)
