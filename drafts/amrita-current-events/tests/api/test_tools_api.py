"""Every tool endpoint, the tool-call routes, auth, and the page/push routes."""
import json

import pytest
from fastapi.testclient import TestClient

from app import main, push
from app.config import Settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(push, "SUBS_FILE", tmp_path / "subs.json")
    monkeypatch.setattr(push, "KEY_FILE", tmp_path / "vapid.pem")

    async def fake_send(subscription, data):
        return None
    monkeypatch.setattr(push, "send", fake_send)
    return TestClient(main.app)


def test_health_lists_tools(client):
    h = client.get("/health").json()
    assert h["ok"] and h["tools"] == ["get_available_topics", "fetch_news", "fetch_asu_events",
                                      "get_news_item", "dedupe_news", "get_news_health"]


def test_get_available_topics(client):
    t = client.get("/topics").json()
    assert {s["id"] for s in t["sections"]} >= {"world", "politics", "tech", "sports"}
    assert "NPR" in next(s for s in t["sections"] if s["id"] == "world")["outlets"]


def test_fetch_news_returns_links_for_comma_topics(client):
    r = client.get("/news", params={"topics": "world, student loans"}).json()
    assert r["topics"] == ["World", "student loans"]
    assert r["count"] == len(r["links"]) == len(r["items"]) > 0
    assert all(link.startswith("https://") for link in r["links"])
    assert r["speak"]


def test_news_candidates_contract_alias(client):
    r = client.get("/news/candidates", params={"topics": "world", "since": "24h"})
    assert r.status_code == 200 and r.json()["since_hours"] == 24


def test_get_news_item_with_article_text_and_404(client):
    items = client.get("/news", params={"topics": "world"}).json()["items"]
    d = client.get(f"/news/item/{items[0]['id']}").json()
    assert d["text_available"] and "earthquake" in d["text"].lower() and "Menu" not in d["text"]
    assert client.get("/news/item/nope").status_code == 404


def test_dedupe_endpoint(client):
    r = client.post("/news/dedupe", json=[{"id": "a", "title": "Fed raises interest rates again", "source": "NPR"},
                                          {"id": "b", "title": "Fed raises interest rates again, citing inflation", "source": "BBC News"}])
    assert r.json()["clusters"][0]["confirmed"] is True


def test_fetch_asu_events_endpoint(client):
    r = client.get("/events", params={"days": 7, "query": "career"}).json()
    assert r["count"] == 1 and r["links"] == ["https://asuevents.asu.edu/event/career-fair"]


def test_tools_listing_and_generic_call(client):
    names = [t["function"]["name"] for t in client.get("/tools").json()["tools"]]
    assert "fetch_news" in names and "fetch_asu_events" in names
    r = client.post("/tools/call", json={"name": "fetch_news", "arguments": {"topics": "world"}}).json()
    assert r["name"] == "fetch_news" and r["result"]["links"]
    assert client.post("/tools/call", json={"name": "fetch_news", "arguments": "{\"topics\": \"world\"}"}).status_code == 200
    assert client.post("/tools/call", json={"name": "fetch_news", "arguments": {}}).status_code == 422
    assert client.post("/tools/call", json={"name": "nope"}).status_code == 404


def test_vapi_webhook(client):
    r = client.post("/tools/vapi", json={"message": {"type": "tool-calls", "toolCallList": [
        {"id": "t1", "function": {"name": "fetch_asu_events", "arguments": json.dumps({"days": 7})}},
        {"id": "t2", "function": {"name": "nope", "arguments": {}}}]}}).json()
    assert r["results"][0]["toolCallId"] == "t1" and r["results"][0]["result"]["count"] == 2
    assert "error" in r["results"][1]["result"]


def test_auth_required_when_key_set(client, monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(api_key="secret"))
    assert client.get("/news", params={"topics": "world"}).status_code == 401
    assert client.get("/news", params={"topics": "world"}, headers={"X-Jarvis-Key": "secret"}).status_code == 200
    assert client.get("/health").status_code == 200   # health stays open
    assert client.get("/").status_code == 200         # student page stays open


def test_page_and_push_routes(client):
    assert client.get("/").status_code == 200
    assert client.get("/sw.js").headers["content-type"].startswith("text/javascript")
    assert len(client.get("/push/public-key").json()["publicKey"]) > 80
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BPk", "auth": "xx"}}
    body = {"subscription": sub, "interests": [{"label": "World", "kind": "section", "section": "world"}]}
    assert client.post("/push/subscribe", json=body).json()["ok"]
    assert client.post("/push/test", json={"endpoint": sub["endpoint"]}).json()["ok"]
    assert client.post("/push/unsubscribe", json={"endpoint": sub["endpoint"]}).json()["ok"]
