"""REST API on the mock backend (labeled demo data). No Google, Gemini, TinyFish or Canvas."""

from datetime import datetime, timedelta, timezone

from app.models import CanvasUnavailable


def test_health_is_demo(client):
    h = client.get("/health").json()
    assert h["ok"] and h["backend"] == "mock" and h["google_login"] == "demo"
    assert h["llm"].startswith("off") and h["nova_calendar"] == "Nova"


# ---------- Gmail ----------

def test_inbox_is_classified_with_important_first(client):
    r = client.get("/gmail/inbox?hours=72").json()
    assert r["data_source"] == "demo" and r["total"] == 6
    emails = r["emails"]
    first_unimportant = next(i for i, e in enumerate(emails) if not e["important"])
    assert all(e["important"] for e in emails[:first_unimportant])
    by_id = {e["id"]: e for e in emails}
    assert by_id["m-recruiter"]["category"] == "recruiter" and by_id["m-recruiter"]["needs_reply"]
    assert by_id["m-promo"]["category"] == "promo" and not by_id["m-promo"]["important"]
    assert r["important_count"] == sum(e["important"] for e in emails)


def test_inbox_filters(client):
    only = client.get("/gmail/inbox?important_only=true").json()["emails"]
    assert only and all(e["important"] for e in only)
    cat = client.get("/gmail/inbox?category=recruiter").json()["emails"]
    assert [e["id"] for e in cat] == ["m-recruiter"]
    unread = client.get("/gmail/inbox?unread_only=true").json()["emails"]
    assert all(e["unread"] for e in unread)
    assert client.get("/gmail/inbox?hours=3").json()["total"] == 1  # only the 2h-old recruiter mail


def test_new_mail_marker_moves(client):
    first = client.get("/gmail/new").json()
    assert first["new_count"] >= 1 and first["emails"][0]["important"] or first["new_count"]
    second = client.get("/gmail/new").json()
    assert second["new_count"] == 0  # nothing arrived since the last check
    peek = client.get("/gmail/new?mark_seen=false").json()
    assert peek["new_count"] == 0


def test_search_and_read_message(client):
    found = client.get("/gmail/search", params={"q": "from:northwind"}).json()
    assert [e["id"] for e in found["emails"]] == ["m-recruiter"]
    m = client.get("/gmail/messages/m-recruiter").json()
    assert "Northwind Labs" in m["body_text"] and m["category"] == "recruiter"
    assert "untrusted" in m["notice"]
    short = client.get("/gmail/messages/m-recruiter?max_chars=500").json()
    assert len(short["body_text"]) <= 500
    assert client.get("/gmail/messages/nope").status_code == 404


def test_drafts_never_send(client):
    d = client.post("/gmail/drafts", json={"body": "Thursday works.",
                                           "reply_to_message_id": "m-recruiter"}).json()
    assert d["draft_id"] and d["data_source"] == "demo" and "Nothing was sent" in d["note"]
    new = client.post("/gmail/drafts", json={"to": "a@b.com", "subject": "Hi", "body": "Yo"})
    assert new.status_code == 200
    bad = client.post("/gmail/drafts", json={"to": "not-an-email", "subject": "Hi", "body": "Yo"})
    assert bad.status_code == 422 and bad.json()["error"] == "bad_request"
    assert client.post("/gmail/drafts", json={"body": " ", "to": "a@b.com",
                                              "subject": "s"}).status_code == 422
    assert client.post("/gmail/drafts", json={"body": "x",
                                              "reply_to_message_id": "nope"}).status_code in (404, 200)


# ---------- Calendar ----------

def test_events_free_busy_and_create(client):
    ev = client.get("/calendar/events?days_ahead=7").json()
    assert ev["data_source"] == "demo" and len(ev["events"]) == 5
    assert [e["start"] for e in ev["events"]] == sorted(e["start"] for e in ev["events"])
    fb = client.get("/calendar/free-busy?days_ahead=3").json()
    assert fb["busy"] and fb["free"]
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    made = client.post("/calendar/events", json={"title": "Study: heaps",
                                                 "start": start.isoformat()}).json()
    assert made["calendar"] == "nova" and made["title"] == "Study: heaps"
    again = client.get("/calendar/events?days_ahead=7").json()["events"]
    assert any(e["title"] == "Study: heaps" and e["calendar"] == "nova" for e in again)
    bad = client.post("/calendar/events", json={"title": "x", "start": start.isoformat(),
                                                "end": (start - timedelta(hours=1)).isoformat()})
    assert bad.status_code == 422


def test_canvas_sync_preview_apply_and_idempotent(client, fake_canvas):
    preview = client.post("/calendar/sync-canvas").json()
    assert preview["applied"] is False and preview["counts"]["create"] == 3
    assert "Preview only" in preview["note"]
    assert client.get("/calendar/events?days_ahead=10").json()["events"][0]["calendar"] == "primary"
    assert not [e for e in client.get("/calendar/events?days_ahead=10").json()["events"]
                if e["calendar"] == "nova"]  # preview changed nothing

    done = client.post("/calendar/sync-canvas?apply=true").json()
    assert done["applied"] and done["counts"]["create"] == 3
    nova = [e for e in client.get("/calendar/events?days_ahead=10").json()["events"]
            if e["calendar"] == "nova"]
    assert {e["canvas_item_id"] for e in nova} == {"assignment-1", "quiz-2", "event-9"}
    assert "Canvas: https://canvas/hw4" in next(
        e for e in nova if e["canvas_item_id"] == "assignment-1")["description"]

    again = client.post("/calendar/sync-canvas?apply=true").json()
    assert again["counts"] == {"create": 0, "update": 0, "delete": 0, "keep": 3}
    assert again["changes"] == []  # keeps are not listed


def test_canvas_sync_follows_canvas_changes(client, fake_canvas):
    client.post("/calendar/sync-canvas?apply=true")
    items = fake_canvas["items"]
    items[0]["submitted"] = True                      # student submitted HW4
    items[1]["due_at"] = (datetime.fromisoformat(items[1]["due_at"]) + timedelta(days=1)
                          ).isoformat()               # quiz moved a day later
    r = client.post("/calendar/sync-canvas?apply=true").json()
    actions = {c["canvas_item_id"]: c["action"] for c in r["changes"]}
    assert actions == {"assignment-1": "delete", "quiz-2": "update"}
    nova = {e["canvas_item_id"] for e in client.get("/calendar/events?days_ahead=10").json()["events"]
            if e["calendar"] == "nova"}
    assert nova == {"quiz-2", "event-9"}


def test_canvas_down_is_a_clear_502(client, fake_canvas):
    fake_canvas["error"] = CanvasUnavailable("Could not reach the Canvas service")
    r = client.post("/calendar/sync-canvas")
    assert r.status_code == 502 and r.json()["error"] == "canvas_unavailable"


def test_auto_sync_switch(client, fake_canvas):
    assert client.get("/calendar/auto-sync").json()["enabled"] is False
    on = client.post("/calendar/auto-sync", json={"enabled": True}).json()
    assert on["enabled"] and on["last_result"]["create"] == 3 and on["last_error"] is None
    assert client.get("/health").json()["auto_sync"] is True
    off = client.post("/calendar/auto-sync", json={"enabled": False}).json()
    assert off["enabled"] is False


# ---------- research + documents ----------

def test_research_needs_a_tinyfish_key(client):
    r = client.post("/research/company", json={"company": "Northwind Labs"})
    assert r.status_code == 503 and "TINYFISH_API_KEY" in r.json()["detail"]
    assert client.post("/research/company", json={"company": " "}).status_code in (422, 503)


def test_save_and_download_document(client):
    d = client.post("/documents", json={"title": "Cover letter", "format": "docx",
                                        "content_markdown": "# Dear Dana\n\nHello **there**."}).json()
    assert d["filename"] == "Cover-letter.docx" and d["download_url"].endswith(f"/files/{d['id']}")
    got = client.get(f"/files/{d['id']}")
    assert got.status_code == 200 and got.content[:2] == b"PK"  # a .docx is a zip
    assert "attachment" in got.headers["content-disposition"]
    assert client.get("/files/000000000000").status_code == 404
    md = client.post("/documents", json={"title": "Notes", "format": "md",
                                         "content_markdown": "# hi"}).json()
    assert client.get(f"/files/{md['id']}").text == "# hi"


# ---------- auth ----------

def test_key_is_required_when_set(make_client):
    c = make_client(canvas_api_key="s3cret")
    assert c.get("/health").status_code == 200           # health stays open
    assert c.get("/gmail/inbox").status_code == 401
    assert c.get("/gmail/inbox", headers={"X-Canvas-Key": "bad"}).status_code == 401
    assert c.get("/gmail/inbox", headers={"X-Canvas-Key": "s3cret"}).status_code == 200
    assert c.get("/files/000000000000").status_code == 401


# ---------- news ----------

def test_news_rest_routes(client, fake_news):
    n = client.get("/news/headlines?topics=top&count=2").json()
    assert n["count"] == 2 and n["stories"][0]["title"].startswith("Judge temporarily")
    e = client.get("/news/asu-events?days=7").json()
    assert e["total"] == 2 and e["events"][1]["title"] == "Robotics club meeting"
    from app.models import NewsUnavailable
    fake_news["error"] = NewsUnavailable("down")
    r = client.get("/news/headlines")
    assert r.status_code == 502 and r.json()["error"] == "news_unavailable"
