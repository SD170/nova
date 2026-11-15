"""MCP (streamable-HTTP) at /mcp: discovery, calls, auth. Same data as REST."""

import json

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

TOOLS = {"gmail_inbox_summary", "gmail_new_since", "gmail_search", "gmail_get_message",
         "gmail_create_draft", "calendar_list_events", "calendar_free_busy",
         "calendar_create_event", "calendar_sync_canvas", "calendar_auto_sync",
         "research_company", "save_document", "get_workspace_health",
         "news_headlines", "asu_events", "exam_info", "quiz_start", "quiz_begin",
         "quiz_answer", "quiz_status", "memory_profile", "memory_recall",
         "memory_remember", "memory_forget"}


def rpc(c, method, params=None, headers=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    return c.post("/mcp", json=body, headers={**H, **(headers or {})})


def call(c, name, args=None, headers=None):
    r = rpc(c, "tools/call", {"name": name, "arguments": args or {}}, headers)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return res, (json.loads(res["content"][0]["text"]) if not res.get("isError") else None)


def test_initialize_and_tools(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
    assert r.json()["result"]["serverInfo"]["name"] == "workspace"
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == TOOLS and all(t["description"] for t in tools)


def test_inbox_matches_rest(client):
    _, inbox = call(client, "gmail_inbox_summary", {"hours": 72})
    rest = client.get("/gmail/inbox?hours=72").json()
    assert [e["id"] for e in inbox["emails"]] == [e["id"] for e in rest["emails"]]


def test_read_gives_a_gist_not_the_body(client):
    _, msg = call(client, "gmail_get_message", {"message_id": "m-prof"})
    assert msg["speak"].startswith("Demo data. From Prof. Ramirez:") and "body_text" not in msg
    assert len(msg["speak"].split()) <= 40
    _, full = call(client, "gmail_get_message", {"message_id": "m-prof", "full": True})
    assert "AVL" in full["body_text"] and full["truncated"] is False


def test_draft_is_saved_never_sent(client):
    _, d = call(client, "gmail_create_draft", {"body": "Yes, I'll be there.",
                                              "reply_to_message_id": "m-prof"})
    assert d["draft_id"] and d["speak"] == "Demo data. Draft saved in Gmail. Nothing was sent."


def test_sync_preview_then_apply(client, fake_canvas):
    _, preview = call(client, "calendar_sync_canvas", {})
    assert preview["applied"] is False and preview["counts"]["create"] == 3
    _, done = call(client, "calendar_sync_canvas", {"apply": True})
    assert done["applied"] and done["counts"]["create"] == 3
    _, ev = call(client, "calendar_list_events", {"days_ahead": 10})
    assert sum(e["calendar"] == "nova" for e in ev["events"]) == 3


def test_create_event_and_bad_date(client):
    _, ev = call(client, "calendar_create_event",
                 {"title": "Study: AVL", "start": "2026-11-20T15:00:00-07:00"})
    assert ev["calendar"] == "nova" and ev["end"].startswith("2026-11-20T16:00")
    res, _ = call(client, "calendar_create_event", {"title": "x", "start": "tomorrow-ish"})
    assert res["isError"] and "ISO" in res["content"][0]["text"]


def test_errors_are_tool_errors(client):
    res, _ = call(client, "gmail_get_message", {"message_id": "nope"})
    assert res["isError"] and "No email with id nope" in res["content"][0]["text"]
    res, _ = call(client, "research_company", {"company": "Acme"})
    assert res["isError"] and "TINYFISH_API_KEY" in res["content"][0]["text"]


def test_doc_and_health(client):
    _, d = call(client, "save_document", {"title": "Reply", "content_markdown": "Hi"})
    assert d["format"] == "docx"
    _, h = call(client, "get_workspace_health")
    assert h["ok"] and h["backend"] == "mock"


def test_mcp_requires_key(make_client):
    c = make_client(canvas_api_key="s3cret")
    assert rpc(c, "tools/list").status_code == 401
    assert rpc(c, "tools/list", headers={"X-Canvas-Key": "bad"}).status_code == 401
    assert rpc(c, "tools/list", headers={"X-Jarvis-Key": "s3cret"}).status_code == 401  # old name
    ok = rpc(c, "tools/list", headers={"X-Canvas-Key": "s3cret"})
    assert ok.status_code == 200 and len(ok.json()["result"]["tools"]) == len(TOOLS)


# ---------- voice-sized answers ----------

def test_every_tool_has_a_short_speak_line(client, fake_canvas):
    calls = [("gmail_inbox_summary", {}), ("gmail_new_since", {}),
             ("gmail_search", {"query": "from:northwind"}),
             ("gmail_get_message", {"message_id": "m-recruiter"}),
             ("gmail_create_draft", {"body": "Thursday works.",
                                     "reply_to_message_id": "m-recruiter"}),
             ("calendar_list_events", {"days_ahead": 7}), ("calendar_free_busy", {}),
             ("calendar_sync_canvas", {}), ("calendar_sync_canvas", {"apply": True}),
             ("calendar_auto_sync", {}),
             ("save_document", {"title": "Cover letter", "content_markdown": "Hi"})]
    for name, args in calls:
        _, out = call(client, name, args)
        assert out["speak"] and len(out["speak"].split()) <= 40, (name, out["speak"])


def test_inbox_answer_is_one_short_line_and_small(client):
    res, inbox = call(client, "gmail_inbox_summary", {"hours": 72})
    assert len(res["content"][0]["text"]) < 3500   # was ~14k (20 full emails) in real use
    assert inbox["speak"].startswith("Demo data. 3 important out of 6. Top: Dana Whitfield,")
    assert "Top:" in inbox["speak"] and "need" in inbox["speak"]
    first = inbox["emails"][0]
    assert set(first) == {"id", "from", "subject", "snippet", "category", "important",
                          "needs_reply", "unread", "when"}
    assert len(first["snippet"]) <= 100


def test_sync_preview_speaks_a_question_and_apply_speaks_done(client, fake_canvas):
    _, preview = call(client, "calendar_sync_canvas", {})
    assert preview["speak"].startswith("Demo data. I'd add 3 on your Nova calendar.")
    assert preview["speak"].endswith("Want me to do it?")
    assert preview["changes"][0]["title"].startswith("CSE 540 Homework 4")
    _, done = call(client, "calendar_sync_canvas", {"apply": True})
    assert done["speak"] == "Demo data. Done. Added 3 on your Nova calendar."
    _, again = call(client, "calendar_sync_canvas", {"apply": True})
    assert again["speak"] == "Demo data. Your Nova calendar is already up to date."


def test_free_time_is_spoken_in_plain_words(client):
    _, fb = call(client, "calendar_free_busy", {"days_ahead": 2})
    assert fb["speak"].startswith("Demo data. You're free ") and " to " in fb["speak"]


# ---------- news + ASU events (Amrita's service, proxied) ----------

def test_news_headlines_one_short_line(client, fake_news):
    res, out = call(client, "news_headlines", {"topics": "world", "count": 3})
    assert out["speak"] == ("Top story: Judge temporarily blocks Trump from moving ahead on "
                            "Washington public golf course, confirmed by 2 outlets. "
                            "2 more if you want them.")
    assert len(out["speak"].split()) <= 35 and out["count"] == 3
    assert out["stories"][0]["url"] == "https://npr.org/a" and out["stories"][0]["source"] == "NPR"
    assert fake_news["calls"][0] == ("/news", {"topics": "world", "since_hours": 24,
                                               "per_topic": 3, "live": "false"})
    assert len(res["content"][0]["text"]) < 2000


def test_asu_events_speak(client, fake_news):
    _, out = call(client, "asu_events", {"days": 7, "query": "career"})
    assert out["speak"] == "2 ASU events this week. Next: Career Fair, Tuesday 10 AM."
    assert out["total"] == 2 and out["events"][0]["location"] == "Memorial Union, Tempe"
    assert fake_news["calls"][0][1]["query"] == "career"


def test_news_service_down_is_a_clear_tool_error(client, fake_news):
    from app.models import NewsUnavailable
    fake_news["error"] = NewsUnavailable("Could not reach the news service at http://localhost:9004")
    res, _ = call(client, "news_headlines", {})
    assert res["isError"] and "news service" in res["content"][0]["text"]


def test_ongoing_events_say_happening_now_and_ended_ones_are_dropped(client, fake_news,
                                                                       monkeypatch):
    from datetime import datetime, timedelta, timezone
    import tests.conftest as c
    now = datetime.now(timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setitem(c.EVENTS, "items", [
        {"id": "old", "title": "Ended yesterday", "starts_at": iso(now - timedelta(days=2)),
         "ends_at": iso(now - timedelta(days=1)), "url": "u"},
        {"id": "now", "title": "SunHacks 9.0", "starts_at": iso(now - timedelta(hours=5)),
         "ends_at": iso(now + timedelta(hours=5)), "url": "u"},
        {"id": "later", "title": "Career Fair", "starts_at": iso(now + timedelta(days=2)),
         "ends_at": iso(now + timedelta(days=2, hours=3)), "url": "u"}])
    _, out = call(client, "asu_events", {})
    assert [e["id"] for e in out["events"]] == ["now", "later"]
    assert out["speak"] == "2 ASU events this week. Now: SunHacks 9.0."
