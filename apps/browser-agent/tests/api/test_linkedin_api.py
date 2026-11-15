"""LinkedIn REST + MCP: observe -> summary -> draft, auth, errors."""

import json
from pathlib import Path

from tests.api.test_mcp import call

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures" / "linkedin_observe.json").read_text())


def test_observe_summary_draft_flow(client):
    r = client.post("/linkedin/observe", json=FIXTURE)
    assert r.status_code == 200
    assert r.json() == {"new_posts": 4, "updated_posts": 0, "engagements_recorded": 5,
                        "total_posts": 4}

    posts = client.get("/linkedin/posts?engaged_only=true").json()["posts"]
    assert {p["id"] for p in posts} == {"urn:li:activity:1001", "urn:li:activity:1002"}

    s = client.get("/linkedin/summary").json()
    assert {p["name"] for p in s["people"]} == {"Priya Raman", "Marcus Lee"}

    d = client.post("/linkedin/draft", json={"post_id": "urn:li:activity:1001"}).json()
    assert d["source"] == "template" and d["comments"] and d["dm"]   # tests have no Gemini key


def test_draft_unknown_post_404(client):
    r = client.post("/linkedin/draft", json={"post_id": "nope"})
    assert r.status_code == 404 and r.json()["error"] == "post_not_found"


def test_bad_engagement_kind_422(client):
    r = client.post("/linkedin/observe", json={"engagements": [{"post_id": "x", "kind": "spam"}]})
    assert r.status_code == 422


def test_clear_session(client):
    client.post("/linkedin/observe", json=FIXTURE)
    assert client.delete("/linkedin/session").json()["total_posts"] == 0
    assert client.get("/linkedin/summary").json()["posts_seen"] == 0


def test_linkedin_requires_key(make_client):
    c = make_client(canvas_api_key="s3cret")
    assert c.post("/linkedin/observe", json=FIXTURE).status_code == 401
    ok = c.post("/linkedin/observe", json=FIXTURE, headers={"X-Canvas-Key": "s3cret"})
    assert ok.status_code == 200


def test_mcp_linkedin_tools(client):
    client.post("/linkedin/observe", json=FIXTURE)
    _, s = call(client, "linkedin_session_summary", {"max_people": 1})
    assert len(s["people"]) == 1
    _, recent = call(client, "linkedin_recent_posts", {"engaged_only": True})
    assert len(recent["posts"]) == 2
    _, d = call(client, "linkedin_draft_message",
                {"post_id": "urn:li:activity:1002", "kind": "comment"})
    assert d["comments"] and d["dm"] is None
    res, _ = call(client, "linkedin_draft_message", {"post_id": "nope"})
    assert res["isError"]


def test_activity_cards_and_research_endpoints(client):
    client.post("/linkedin/observe", json={**FIXTURE, "on_screen": ["urn:li:activity:1002"]})
    act = client.get("/linkedin/activity").json()
    assert act["on_screen"] == ["urn:li:activity:1002"]
    assert {a["kind"] for a in act["activity"]} == {"liked", "expanded", "read"}

    card = client.post("/linkedin/cards/draft", json={"kind": "comment"}).json()
    assert card["status"] == "done" and card["drafts"]["author_name"] == "Marcus Lee"
    assert client.post("/linkedin/cards/draft", json={"person": "zzz"}).status_code == 404

    r = client.post("/linkedin/research", json={"company": "Ramp"})
    assert r.status_code == 202 and r.json()["status"] == "working"
    cards = client.get("/linkedin/cards").json()["cards"]
    assert cards[0]["kind"] == "research" and cards[1]["kind"] == "draft"


def test_mcp_voice_tools(client):
    client.post("/linkedin/observe", json=FIXTURE)
    _, d = call(client, "linkedin_draft_message", {"person": "Priya", "kind": "comment"})
    assert d["speak"].startswith("I put two comment options for Priya's post") and d["comments"]
    _, s = call(client, "linkedin_session_summary")
    assert "Worth reaching out to" in s["speak"]
    _, r = call(client, "linkedin_research_company", {"company": "Ramp"})
    assert "Ramp" in r["speak"]
    _, g = call(client, "linkedin_get_research")
    assert g["status"] in ("working", "failed")     # tests have no TinyFish key
