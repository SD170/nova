"""Shared fixtures. No test touches the network: every request is answered by a fake transport."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

os.environ["PUSH_ENABLED"] = "0"  # no background push loop during tests

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import digest, events, sources  # noqa: E402
from app.service import service  # noqa: E402

NOW = datetime.now(timezone.utc)
AZ = timezone(timedelta(hours=-7))


def rss_date(hours_ago: float) -> str:
    return format_datetime(NOW - timedelta(hours=hours_ago))


def rss(items) -> bytes:
    body = "".join(
        f"<item><title>{t}{' - ' + s if s else ''}</title><link>{u}</link><pubDate>{d}</pubDate>"
        + (f'<source url="https://x">{s}</source>' if s else "") + "</item>"
        for t, s, u, d in items)
    return f'<?xml version="1.0"?><rss><channel>{body}</channel></rss>'.encode()


GOOGLE = rss([
    ("Senate passes student loan relief bill", "Reuters", "https://reuters.example/a", rss_date(2)),
    ("Senate passes student loan relief bill in late vote", "AP News", "https://ap.example/a", rss_date(3)),
    ("You won't believe this loan trick", "Random Blog", "https://blog.example/x", rss_date(1)),
    ("Old news about loans", "Reuters", "https://reuters.example/old", rss_date(60)),
])
OUTLET = rss([("Earthquake strikes off coast of Japan", "", "https://www.bbc.co.uk/news/quake", rss_date(1))])
ESPN = {"articles": [{"headline": "Suns win in overtime", "description": "— Recap",
                      "published": (NOW - timedelta(hours=2)).isoformat(), "links": {"web": {"href": "https://espn.com/x"}}}]}
ARTICLE = ("<html><body><nav><p>Menu menu menu menu menu menu menu menu menu menu menu menu menu menu</p></nav>"
           "<p>A strong earthquake struck off the coast of Japan on Saturday, officials said, prompting brief tsunami advisories.</p>"
           "<p>No major damage was reported in the first hours, according to the national weather agency and local authorities.</p>"
           "</body></html>")


def _az(dt: datetime) -> str:
    return dt.astimezone(AZ).strftime("%a, %b %d, %Y %I:%M %p").replace(" 0", " ")


ASU_EVENTS = {"nodes": [
    {"node": {"nid": "1", "title": "Fall Career Fair", "alias": "https://asuevents.asu.edu/event/career-fair",
              "very_start_date": (NOW + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
              "very_end_date": (NOW + timedelta(days=2, hours=4)).isoformat().replace("+00:00", "Z"),
              "start_date": "Tue", "campus": "Tempe campus", "locations": "Memorial Union",
              "event_types": "Career and professional development", "interests": "Careers|Engineering",
              "body_summary": "<p>Meet <b>200</b> employers.</p>", "asu_events_price_desc": "Free",
              "college_unit": "Career and Professional Development Services"}},
    {"node": {"nid": "2", "title": "Last month's lecture", "alias": "https://asuevents.asu.edu/event/old",
              "very_start_date": (NOW - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
              "very_end_date": (NOW - timedelta(days=30)).isoformat().replace("+00:00", "Z"), "campus": "West"}},
]}
_FIELDS = "date_separator,eventId,eventName,eventDates,eventCategory,eventLocation,clubName,eventPriceRange,eventUrl,eventTags,"
SDC = [
    {"fields": "date_separator,date_text,", "p0": "true", "p1": "Upcoming"},
    {"fields": _FIELDS, "p0": "false", "p1": "501", "p2": "Robotics Club Build Night",
     "p3": f"<p>{_az(NOW + timedelta(days=1))} &ndash; </p><p>{_az(NOW + timedelta(days=1, hours=2))}</p>",
     "p4": "Meeting", "p5": "ISTB4 240", "p6": "Sun Devil Robotics", "p7": "0.00", "p8": "/rsvp_boot?id=501",
     "p9": '<a aria-label="Engineering">x</a>'},
    {"fields": _FIELDS, "p0": "false", "p1": "502", "p2": "Weekly Chapter (all semester)",
     "p3": f"<p>{_az(NOW - timedelta(days=60))} &ndash; </p><p>{_az(NOW + timedelta(days=20))}</p>",
     "p4": "Meeting", "p5": "Private", "p6": "A Fraternity", "p7": "0", "p8": "/rsvp_boot?id=502", "p9": ""},
]

CALLS: list[str] = []


def handler(request: httpx.Request) -> httpx.Response:
    CALLS.append(str(request.url))
    host, path = request.url.host, request.url.path
    if host == "news.google.com":
        return httpx.Response(200, content=GOOGLE)
    if host == "site.api.espn.com":
        return httpx.Response(200, json=ESPN)
    if host == "asuevents.asu.edu":
        return httpx.Response(200, json=ASU_EVENTS)
    if host == "sundevilcentral.eoss.asu.edu":
        return httpx.Response(200, json=SDC)
    if host == "www.bbc.co.uk" and path == "/news/quake":
        return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})
    if any(host.endswith(h) for h in ("npr.org", "bbci.co.uk", "nytimes.com", "theguardian.com", "aljazeera.com",
                                      "pbs.org", "cbsnews.com", "abcnews.go.com", "washingtonpost.com",
                                      "nature.com", "sciencedaily.com", "arstechnica.com", "theverge.com",
                                      "espn.com", "insidehighered.com")):
        return httpx.Response(200, content=OUTLET)
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def fake_network(monkeypatch):
    monkeypatch.setattr(sources, "TRANSPORT", httpx.MockTransport(handler))
    # Fixture stories are 1-3 h old; pin "today" to a rolling 24 h so tests don't depend on the clock.
    # news_window itself is tested with fixed times in test_news.py.
    import app.service as svc
    real = svc.news_window
    monkeypatch.setattr(svc, "news_window", lambda h=None, tz=None, now=None: real(h or 24, tz, now))
    monkeypatch.setattr(svc, "_real_news_window", real, raising=False)
    for k in ("NEWSAPI_KEY", "GNEWS_API_KEY", "NEWSDATA_API_KEY", "GUARDIAN_API_KEY", "NYT_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    sources.clear_cache()
    events.clear_cache()
    service._cache.clear()
    service._index.clear()
    CALLS.clear()
    yield CALLS


def build(*a, **k):
    return asyncio.run(digest.build(*a, **k))
