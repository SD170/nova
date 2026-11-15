"""Offline tests: every outbound request is answered by a fake transport."""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news import digest, outlets, sources  # noqa: E402
from news.tools import get_news_digest  # noqa: E402

NOW = datetime.now(timezone.utc)


def rss_date(hours_ago: float) -> str:
    return format_datetime(NOW - timedelta(hours=hours_ago))


def rss(items) -> bytes:
    body = "".join(
        f"<item><title>{t}{' - ' + s if s else ''}</title><link>{u}</link><pubDate>{d}</pubDate>"
        f"{f'<source url=\"https://x\">{s}</source>' if s else ''}</item>"
        for t, s, u, d in items)
    return f'<?xml version="1.0"?><rss><channel>{body}</channel></rss>'.encode()


GOOGLE = rss([
    ("Senate passes student loan relief bill", "Reuters", "https://reuters.example/a", rss_date(2)),
    ("Senate passes student loan relief bill in late vote", "AP News", "https://ap.example/a", rss_date(3)),
    ("You won't believe this loan trick", "Random Blog", "https://blog.example/x", rss_date(1)),
    ("Old news about loans", "Reuters", "https://reuters.example/old", rss_date(60)),
])
OUTLET = rss([("Earthquake strikes off coast of Japan", "", "https://outlet.example/q", rss_date(1))])
ESPN = {"articles": [{"headline": "Suns win in overtime", "description": "— Recap",
                      "published": (NOW - timedelta(hours=2)).isoformat(), "links": {"web": {"href": "https://espn.com/x"}}}]}

calls: list[str] = []


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(str(request.url))
    host = request.url.host
    if host == "news.google.com":
        return httpx.Response(200, content=GOOGLE)
    if host == "site.api.espn.com":
        return httpx.Response(200, json=ESPN)
    if any(host.endswith(h) for h in ("npr.org", "bbci.co.uk", "nytimes.com", "theguardian.com", "aljazeera.com",
                                      "pbs.org", "cbsnews.com", "abcnews.go.com", "washingtonpost.com")):
        return httpx.Response(200, content=OUTLET)
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def fake_network(monkeypatch):
    monkeypatch.setattr(sources, "TRANSPORT", httpx.MockTransport(handler))
    for k in ("NEWSAPI_KEY", "GNEWS_API_KEY", "NEWSDATA_API_KEY", "GUARDIAN_API_KEY", "NYT_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    sources.clear_cache()
    calls.clear()
    yield


def build(*a, **k):
    return asyncio.run(digest.build(*a, **k))


def test_same_story_from_two_trusted_outlets_is_merged_and_confirmed():
    d = build([{"label": "Loans", "kind": "topic"}])
    story = d["items"][0]
    assert story["outlets"] == 2 and story["confirmed"] is True
    assert {story["source"], story["also_reported_by"][0]["source"]} == {"Reuters", "AP News"}
    assert all(i["url"].startswith("https://") for i in d["items"])


def test_untrusted_sites_and_stale_stories_are_dropped():
    titles = [i["title"] for i in build([{"label": "Loans", "kind": "topic"}])["items"]]
    assert not any("trick" in t for t in titles)       # unknown blog filtered
    assert not any("Old news" in t for t in titles)    # older than 24h filtered
    loose = build([{"label": "Loans", "kind": "topic"}], trusted_only=False)["items"]
    assert any("trick" in i["title"] for i in loose)    # can be turned off


def test_section_pulls_every_outlet_feed_and_counts_them():
    d = build([{"label": "World", "kind": "section", "section": "world"}])
    assert sum("rss" in c or "feeds" in c or ".xml" in c for c in calls) == len(outlets.FEEDS["world"])
    story = d["items"][0]
    assert story["title"] == "Earthquake strikes off coast of Japan"
    assert story["outlets"] == len(outlets.FEEDS["world"])  # same story in every feed → all count


def test_whole_league_uses_espn_and_team_uses_targeted_search():
    build([{"label": "NBA", "kind": "sports", "league": "nba"},
           {"label": "Phoenix Suns", "kind": "sports", "league": "nba", "query": "Phoenix Suns"}])
    joined = " ".join(calls)
    assert "basketball/nba" in joined and "q=Phoenix+Suns" in joined


def test_failed_source_is_reported_not_fatal(monkeypatch):
    monkeypatch.setattr(sources, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(503)))
    d = build([{"label": "Loans", "kind": "topic"}])
    assert d["items"] == [] and d["sources"][0]["ok"] is False
    assert "couldn't find" in d["speak"]


def test_keyed_apis_only_called_when_key_present(monkeypatch):
    build([{"label": "World", "kind": "section", "section": "world"}])
    assert not any(h in " ".join(calls) for h in ("newsapi.org", "gnews.io", "newsdata.io", "guardianapis", "api.nytimes"))
    monkeypatch.setenv("GUARDIAN_API_KEY", "k")
    sources.clear_cache()
    build([{"label": "World", "kind": "section", "section": "world"}])
    assert any("content.guardianapis.com" in c for c in calls)


def test_espn_summary_dash_trimmed():
    d = build([{"label": "NBA", "kind": "sports", "league": "nba"}])
    assert d["items"][0]["summary"] == "Recap"


def test_tool_signature_matches_voice_mock_tools():
    out = get_news_digest({"topics": ["world", "student loans"]})
    assert out["speak"] and out["items"][0]["url"] and "outlets" in out["items"][0]


def test_api_endpoints():
    import server
    c = TestClient(server.app)
    h = c.get("/news/health").json()
    assert h["ok"] and "world" in h["outlet_feeds"] and h["keyed_sources"]["nyt"] is False
    assert c.get("/news/interests").json()["demo"] is True
    r = c.post("/news/digest", json={"interests": [{"label": "World", "kind": "section", "section": "world"}]})
    assert r.status_code == 200 and r.json()["window_hours"] == 24
    r = c.get("/news/digest", params={"topics": "world, student loans"})
    kinds = {i["label"]: i["kind"] for i in r.json()["interests"]}
    assert kinds == {"World": "section", "student loans": "topic"}
    r = c.post("/news/tools", json={"message": {"type": "tool-calls", "toolCallList": [
        {"id": "t1", "function": {"name": "get_news_digest", "arguments": json.dumps({"topics": ["world"]})}}]}})
    res = r.json()["results"][0]
    assert res["toolCallId"] == "t1" and res["result"]["speak"]
    assert c.get("/").status_code == 200


# ───────────────────────── push notifications ─────────────────────────
from news import push  # noqa: E402

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BPk", "auth": "xx"}}


@pytest.fixture
def push_store(tmp_path, monkeypatch):
    monkeypatch.setattr(push, "SUBS_FILE", tmp_path / "subs.json")
    monkeypatch.setattr(push, "KEY_FILE", tmp_path / "vapid.pem")
    sent: list[dict] = []

    async def fake_send(subscription, data):
        sent.append(data)
    monkeypatch.setattr(push, "send", fake_send)
    return sent


def test_vapid_key_is_generated_locally(push_store):
    key = push.public_key()
    assert len(key) > 80 and push.KEY_FILE.exists()
    assert push.public_key() == key  # stable across calls


def test_subscribe_stores_preferences_and_rejects_junk(push_store):
    info = push.upsert(SUB, {"interests": [{"label": "World", "kind": "section", "section": "world"}], "tz_offset_min": 420})
    assert info["interests"] == 1 and push.count() == 1
    with pytest.raises(ValueError):
        push.upsert({"endpoint": "http://not-https"}, {})
    assert push.remove(SUB["endpoint"]) and push.count() == 0


def test_quiet_hours_respect_local_time():
    rec = {"tz_offset_min": 420, "quiet_start": 22, "quiet_end": 7}  # Arizona (UTC-7)
    assert push.in_quiet_hours(rec, datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc))       # 11pm AZ
    assert not push.in_quiet_hours(rec, datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc))  # 11am AZ


def test_first_check_sends_one_welcome_then_only_new_confirmed(push_store):
    push.upsert(SUB, {"interests": [{"label": "Loans", "kind": "topic"}], "quiet_start": 0, "quiet_end": 0})
    sid = push.sub_id(SUB["endpoint"])
    n = asyncio.run(push.check_one(sid, push.get(SUB["endpoint"])))
    assert n == 1 and "Confirmed by 2 outlets" in push_store[0]["body"]
    assert push_store[0]["url"].startswith("https://")
    sources.clear_cache()
    n2 = asyncio.run(push.check_one(sid, push.get(SUB["endpoint"])))
    assert n2 == 0  # nothing new → no repeat alert


def test_expired_subscription_is_removed(push_store, monkeypatch):
    push.upsert(SUB, {"interests": [{"label": "Loans", "kind": "topic"}], "quiet_start": 0, "quiet_end": 0})

    async def gone(subscription, data):
        raise push.Gone()
    monkeypatch.setattr(push, "send", gone)
    asyncio.run(push.check_one(push.sub_id(SUB["endpoint"]), push.get(SUB["endpoint"]), force=True))
    assert push.count() == 0


def test_push_endpoints(push_store):
    import server
    c = TestClient(server.app)
    assert len(c.get("/push/public-key").json()["publicKey"]) > 80
    assert c.get("/sw.js").headers["content-type"].startswith("text/javascript")
    assert "Jarvis" in c.get("/manifest.webmanifest").text
    r = c.post("/push/subscribe", json={"subscription": SUB, "interests": [{"label": "Loans", "kind": "topic"}]})
    assert r.status_code == 200 and r.json()["ok"]
    assert c.post("/push/test", json={"endpoint": SUB["endpoint"]}).json()["ok"]
    assert c.post("/push/unsubscribe", json={"endpoint": SUB["endpoint"]}).json()["ok"]
    assert c.post("/push/test", json={"endpoint": SUB["endpoint"]}).status_code == 404
