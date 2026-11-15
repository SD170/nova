"""Reputable outlets + keyed news APIs.

Outlet RSS feeds are free and need no key (each URL was checked live).
Keyed APIs switch on automatically when their key is in .env:

  NEWSAPI_KEY       newsapi.org        (80k+ sources; free dev plan is localhost-only)
  GNEWS_API_KEY     gnews.io           (global, 100 requests/day free)
  NEWSDATA_API_KEY  newsdata.io        (global, 200 credits/day free)
  GUARDIAN_API_KEY  open-platform.theguardian.com (free developer key)
  NYT_API_KEY       developer.nytimes.com          (Top Stories API, free)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from . import sources
from .sources import Item, _cached, _iso, _parse_rss, _strip_html, client

# section -> [(outlet name, rss url)]
FEEDS: dict[str, list[tuple[str, str]]] = {
    "top": [
        ("NPR", "https://feeds.npr.org/1001/rss.xml"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
        ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
        ("PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/headlines"),
        ("CBS News", "https://www.cbsnews.com/latest/rss/main"),
        ("ABC News", "https://abcnews.go.com/abcnews/topstories"),
    ],
    "politics": [
        ("NPR", "https://feeds.npr.org/1014/rss.xml"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml"),
        ("The Washington Post", "https://feeds.washingtonpost.com/rss/politics"),
        ("The Guardian", "https://www.theguardian.com/us-news/us-politics/rss"),
        ("PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/politics"),
        ("CBS News", "https://www.cbsnews.com/latest/rss/politics"),
        ("BBC News", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"),
    ],
    "world": [
        ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("NPR", "https://feeds.npr.org/1004/rss.xml"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/world"),
        ("CBS News", "https://www.cbsnews.com/latest/rss/world"),
    ],
    "science": [
        ("NPR", "https://feeds.npr.org/1007/rss.xml"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml"),
        ("BBC News", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/science/rss"),
        ("Nature", "https://www.nature.com/nature.rss"),
        ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml"),
    ],
    "tech": [
        ("NPR", "https://feeds.npr.org/1019/rss.xml"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
        ("BBC News", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ],
    "education": [
        ("NPR", "https://feeds.npr.org/1013/rss.xml"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Education.xml"),
        ("BBC News", "https://feeds.bbci.co.uk/news/education/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/education/rss"),
        ("Inside Higher Ed", "https://www.insidehighered.com/rss.xml"),
    ],
    "sports": [
        ("ESPN", "https://www.espn.com/espn/rss/news"),
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ],
    "business": [
        ("NPR", "https://feeds.npr.org/1006/rss.xml"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
        ("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ],
    "health": [
        ("NPR", "https://feeds.npr.org/1128/rss.xml"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml"),
        ("BBC News", "https://feeds.bbci.co.uk/news/health/rss.xml"),
    ],
}
SECTIONS = tuple(FEEDS)

# Established newsrooms with editorial standards. Used to filter keyword search
# results (Google News / keyed APIs) when "trusted outlets only" is on.
TRUSTED = {
    "associated press", "ap news", "reuters", "npr", "pbs", "pbs newshour", "bbc", "bbc news", "bbc sport",
    "the new york times", "new york times", "the washington post", "washington post", "the wall street journal",
    "wall street journal", "the guardian", "cbs news", "abc news", "nbc news", "cnn", "fox news", "usa today",
    "los angeles times", "bloomberg", "financial times", "the economist", "politico", "axios", "the hill",
    "al jazeera", "al jazeera english", "time", "the atlantic", "npr.org", "cnbc", "forbes", "nature",
    "science", "sciencedaily", "scientific american", "new scientist", "ars technica", "the verge", "wired",
    "techcrunch", "espn", "the athletic", "sports illustrated", "cbs sports", "yahoo sports", "inside higher ed",
    "the chronicle of higher education", "education week", "the arizona republic", "azcentral", "arizona republic",
    "asu news", "state press", "the state press", "arizona sports", "abc15 arizona", "12news", "kjzz",
    "propublica", "c-span", "voice of america", "deutsche welle", "dw", "france 24", "the independent",
    "sky news", "cbc", "cbc news", "the conversation", "nasa", "stat", "stat news", "kff health news",
    "mit technology review", "ieee spectrum", "quanta magazine",
}


def is_trusted(source: str) -> bool:
    s = (source or "").lower().strip()
    return s in TRUSTED or any(s.startswith(t + " ") or s.endswith(" " + t) for t in TRUSTED)


async def outlet_feed(outlet: str, url: str, topic: str, limit: int = 8) -> list[Item]:
    async def fetch() -> list[Item]:
        async with client() as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0 (StudentJarvis news reader)"})
        r.raise_for_status()
        items = _parse_rss(r.content, topic, limit)
        for i in items:
            i.source, i.provider = outlet, f"{outlet} RSS"
        return items
    return await _cached(f"rss:{url}:{limit}", fetch)


# ───────────────────────── keyed APIs ─────────────────────────

def active_keys() -> dict[str, bool]:
    return {k: bool(os.environ.get(v)) for k, v in {
        "newsapi": "NEWSAPI_KEY", "gnews": "GNEWS_API_KEY", "newsdata": "NEWSDATA_API_KEY",
        "guardian": "GUARDIAN_API_KEY", "nyt": "NYT_API_KEY"}.items()}


def _dt(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        return _iso(datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T")))
    except ValueError:
        return None


GNEWS_CAT = {"top": "general", "world": "world", "politics": "nation", "science": "science", "tech": "technology",
             "sports": "sports", "business": "business", "health": "health"}
NYT_SECTION = {"top": "home", "world": "world", "politics": "politics", "science": "science", "tech": "technology",
               "sports": "sports", "business": "business", "health": "health", "education": "us"}
GUARDIAN_SECTION = {"world": "world", "politics": "us-news", "science": "science", "tech": "technology",
                    "sports": "sport", "business": "business", "education": "education", "health": "society"}


async def gnews(topic: str, query: Optional[str], section: Optional[str], limit: int = 8) -> list[Item]:
    key = os.environ.get("GNEWS_API_KEY")
    if not key:
        return []

    async def fetch() -> list[Item]:
        async with client() as c:
            if query:
                r = await c.get("https://gnews.io/api/v4/search", params={"q": query, "lang": "en", "max": limit, "sortby": "publishedAt", "apikey": key})
            else:
                r = await c.get("https://gnews.io/api/v4/top-headlines", params={"category": GNEWS_CAT.get(section or "top", "general"), "lang": "en", "country": "us", "max": limit, "apikey": key})
        r.raise_for_status()
        return [Item(title=a["title"], url=a["url"], source=(a.get("source") or {}).get("name") or "GNews",
                     published_at=_dt(a.get("publishedAt")), topic=topic, provider="GNews",
                     summary=_strip_html(a.get("description") or ""))
                for a in r.json().get("articles", []) if a.get("title") and a.get("url")]
    return await _cached(f"gnews:{query}:{section}:{limit}", fetch)


async def newsdata(topic: str, query: Optional[str], section: Optional[str], limit: int = 8) -> list[Item]:
    key = os.environ.get("NEWSDATA_API_KEY")
    if not key:
        return []

    async def fetch() -> list[Item]:
        params = {"apikey": key, "language": "en", "size": min(limit, 10)}
        if query:
            params["q"] = query
        else:
            params["category"] = {"tech": "technology", "politics": "politics", "education": "education"}.get(section or "top", section or "top")
            params["country"] = "us"
        async with client() as c:
            r = await c.get("https://newsdata.io/api/1/latest", params=params)
        r.raise_for_status()
        return [Item(title=a["title"], url=a["link"], source=a.get("source_name") or a.get("source_id") or "NewsData",
                     published_at=_dt(a.get("pubDate")), topic=topic, provider="NewsData.io",
                     summary=_strip_html(a.get("description") or "")[:400])
                for a in r.json().get("results", []) if a.get("title") and a.get("link")]
    return await _cached(f"newsdata:{query}:{section}:{limit}", fetch)


async def guardian(topic: str, query: Optional[str], section: Optional[str], limit: int = 8) -> list[Item]:
    key = os.environ.get("GUARDIAN_API_KEY")
    if not key:
        return []

    async def fetch() -> list[Item]:
        params = {"api-key": key, "page-size": limit, "order-by": "newest", "show-fields": "trailText"}
        if query:
            params["q"] = query
        elif section in GUARDIAN_SECTION:
            params["section"] = GUARDIAN_SECTION[section]
        async with client() as c:
            r = await c.get("https://content.guardianapis.com/search", params=params)
        r.raise_for_status()
        return [Item(title=a["webTitle"], url=a["webUrl"], source="The Guardian", published_at=_dt(a.get("webPublicationDate")),
                     topic=topic, provider="Guardian API", summary=_strip_html((a.get("fields") or {}).get("trailText", "")))
                for a in r.json().get("response", {}).get("results", [])]
    return await _cached(f"guardian:{query}:{section}:{limit}", fetch)


async def nyt(topic: str, section: Optional[str], limit: int = 8) -> list[Item]:
    key = os.environ.get("NYT_API_KEY")
    if not key or not section:
        return []

    async def fetch() -> list[Item]:
        async with client() as c:
            r = await c.get(f"https://api.nytimes.com/svc/topstories/v2/{NYT_SECTION.get(section, 'home')}.json", params={"api-key": key})
        r.raise_for_status()
        return [Item(title=a["title"], url=a["url"], source="The New York Times", published_at=_dt(a.get("published_date")),
                     topic=topic, provider="NYT API", summary=a.get("abstract", ""))
                for a in r.json().get("results", [])[:limit] if a.get("title") and a.get("url")]
    return await _cached(f"nyt:{section}:{limit}", fetch)


async def newsapi(topic: str, query: Optional[str], section: Optional[str], limit: int = 8) -> list[Item]:
    if not query and section:
        cat = {"top": "general", "tech": "technology", "politics": "general", "world": "general"}.get(section, section)
        if os.environ.get("NEWSAPI_KEY"):
            async def fetch() -> list[Item]:
                async with client() as c:
                    r = await c.get("https://newsapi.org/v2/top-headlines", params={"country": "us", "category": cat, "pageSize": limit},
                                    headers={"X-Api-Key": os.environ["NEWSAPI_KEY"]})
                r.raise_for_status()
                return [Item(title=a["title"], url=a["url"], source=(a.get("source") or {}).get("name") or "NewsAPI",
                             published_at=_dt(a.get("publishedAt")), topic=topic, provider="NewsAPI",
                             summary=_strip_html(a.get("description") or ""))
                        for a in r.json().get("articles", []) if a.get("title") and a.get("url") and a["title"] != "[Removed]"]
            return await _cached(f"newsapi-top:{cat}:{limit}", fetch)
        return []
    return await sources.newsapi(query or topic, topic, limit)


KEYED = {"gnews": gnews, "newsdata": newsdata, "guardian": guardian, "newsapi": newsapi}


def keyed_fetchers():
    """Only the providers whose key is configured."""
    keys = active_keys()
    return [fn for name, fn in KEYED.items() if keys[name]]
