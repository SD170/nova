"""Offline tests: every outbound request is answered by a fake transport."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news import digest, sources  # noqa: E402
from news.tools import get_news_digest  # noqa: E402

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Senate passes student loan bill - The Daily</title><link>https://example.com/a</link>
<pubDate>Sat, 14 Nov 2026 18:00:00 GMT</pubDate><source url="https://example.com">The Daily</source></item>
<item><title>Senate passes student loan bill - Other Paper</title><link>https://example.com/dup</link>
<pubDate>Sat, 14 Nov 2026 17:00:00 GMT</pubDate><source url="https://other.com">Other Paper</source></item>
</channel></rss>"""
ESPN = {"articles": [{"headline": "Suns win in overtime", "description": "Recap",
                      "published": "2026-11-14T20:00:00Z", "links": {"web": {"href": "https://espn.com/x"}}}]}
HN = {"hits": [{"title": "New sorting algorithm", "url": "https://hn.example/s", "created_at_i": 1794700000, "objectID": "1"}]}

calls: list[str] = []


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(str(request.url))
    host = request.url.host
    if host == "news.google.com":
        return httpx.Response(200, content=RSS.encode())
    if host == "site.api.espn.com":
        return httpx.Response(200, json=ESPN)
    if host == "hn.algolia.com":
        return httpx.Response(200, json=HN)
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def fake_network(monkeypatch):
    monkeypatch.setattr(sources, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    sources.clear_cache()
    calls.clear()
    yield


def test_google_rss_strips_publisher_and_parses_date():
    items = asyncio.run(sources.google_news("politics", "Politics"))
    assert items[0].title == "Senate passes student loan bill"
    assert items[0].source == "The Daily"
    assert items[0].published_at == "2026-11-14T18:00:00Z"
    assert items[0].url == "https://example.com/a"


def test_digest_dedupes_and_every_item_has_a_source_url():
    d = asyncio.run(digest.build([{"label": "Politics", "kind": "topic"}]))
    titles = [i["title"] for i in d["items"]]
    assert titles.count("Senate passes student loan bill") == 1
    assert all(i["url"].startswith("https://") for i in d["items"])
    assert "Politics" in d["speak"]


def test_routes_each_interest_kind_to_the_right_source():
    asyncio.run(digest.build([
        {"label": "NBA", "kind": "sports", "league": "nba"},
        {"label": "Phoenix Suns", "kind": "sports", "league": "nba", "query": "Phoenix Suns"},
        {"label": "Tech", "kind": "tech"},
        {"label": "World", "kind": "topic", "section": "WORLD"},
    ]))
    joined = " ".join(calls)
    assert "site.api.espn.com" in joined and "basketball/nba" in joined
    assert "q=Phoenix+Suns" in joined                    # team → targeted search, not the whole league
    assert "hn.algolia.com" in joined
    assert "headlines/section/topic/WORLD" in joined


def test_failed_source_is_reported_not_fatal(monkeypatch):
    monkeypatch.setattr(sources, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(503)))
    d = asyncio.run(digest.build([{"label": "World", "kind": "topic"}]))
    assert d["items"] == []
    assert d["sources"][0]["ok"] is False
    assert "couldn't find" in d["speak"]


def test_newsapi_only_used_with_key(monkeypatch):
    asyncio.run(digest.build([{"label": "AI", "kind": "topic"}]))
    assert not any("newsapi.org" in c for c in calls)


def test_since_counts_new_items():
    d = asyncio.run(digest.build([{"label": "Politics", "kind": "topic"}], since="2026-11-14T17:30:00Z"))
    assert d["new_count"] == 1


def test_tool_signature_matches_voice_mock_tools():
    out = get_news_digest({"topics": ["Phoenix Suns"]})
    assert out["speak"] and out["items"][0]["url"]


def test_api_endpoints():
    import server
    c = TestClient(server.app)
    assert c.get("/news/health").json()["ok"] is True
    assert c.get("/news/interests").json()["demo"] is True
    r = c.post("/news/digest", json={"interests": [{"label": "Tech", "kind": "tech"}]})
    assert r.status_code == 200 and r.json()["items"][0]["source"] == "Hacker News"
    r = c.get("/news/digest", params={"topics": "politics, climate"})
    assert {i["label"] for i in r.json()["interests"]} == {"politics", "climate"}
    r = c.post("/news/tools", json={"message": {"type": "tool-calls", "toolCallList": [
        {"id": "t1", "function": {"name": "get_news_digest", "arguments": json.dumps({"topics": ["NBA"]})}}]}})
    res = r.json()["results"][0]
    assert res["toolCallId"] == "t1" and res["result"]["speak"]
    assert c.get("/").status_code == 200
