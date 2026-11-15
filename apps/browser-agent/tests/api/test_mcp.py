"""MCP (streamable-HTTP) at /mcp: discovery, calls, auth. Same data as REST."""

import json

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

TOOLS = {"get_daily_brief", "get_todo_list", "get_item_details", "mark_item_done_locally",
         "unmark_item_done", "list_courses", "get_course_items", "get_course_materials",
         "get_material_text", "sync_canvas", "get_canvas_health",
         "linkedin_session_summary", "linkedin_recent_posts", "linkedin_draft_message",
         "linkedin_research_company", "linkedin_get_research"}


def rpc(c, method, params=None, headers=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    return c.post("/mcp", json=body, headers={**H, **(headers or {})})


def call(c, name, args=None, headers=None):
    r = rpc(c, "tools/call", {"name": name, "arguments": args or {}}, headers)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return res, (json.loads(res["content"][0]["text"]) if not res.get("isError") else None)


def test_initialize(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
    assert r.status_code == 200
    assert r.json()["result"]["serverInfo"]["name"] == "canvas"


def test_tools_list(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == TOOLS
    assert all(t["description"] for t in tools)


def test_brief_matches_rest(client):
    _, brief = call(client, "get_daily_brief", {"days": 7})
    rest = client.get("/brief?days=7").json()
    assert [i["id"] for i in brief["items"]] == [i["id"] for i in rest["items"]]


def test_materials_and_text(client):
    _, mats = call(client, "get_course_materials", {"course_id": "cse310", "topic_hint": "heaps"})
    assert [m["id"] for m in mats["materials"]] == ["file-310010"]
    assert "fetch_ref" not in mats["materials"][0]
    _, text = call(client, "get_material_text", {"material_id": "file-310010"})
    assert "[page 2]" in text["text"]


def test_user_done_roundtrip(client):
    _, item = call(client, "mark_item_done_locally", {"item_id": "cse310-a3"})
    assert item["user_done"] is True
    _, item = call(client, "unmark_item_done", {"item_id": "cse310-a3"})
    assert item["in_todo"] is True


def test_errors_are_tool_errors(client):
    res, _ = call(client, "get_item_details", {"item_id": "nope"})
    assert res["isError"]
    res, _ = call(client, "get_material_text", {"material_id": "file-310099"})
    assert res["isError"] and "too_large" in res["content"][0]["text"]


def test_mcp_requires_key(make_client):
    c = make_client(canvas_api_key="s3cret")
    assert rpc(c, "tools/list").status_code == 401
    assert rpc(c, "tools/list", headers={"X-Canvas-Key": "bad"}).status_code == 401
    r = rpc(c, "tools/list", headers={"X-Canvas-Key": "s3cret"})
    assert r.status_code == 200 and len(r.json()["result"]["tools"]) == len(TOOLS)


# ---------- voice-sized answers ----------

def test_every_read_tool_has_a_short_speak_line(client):
    calls = [("get_daily_brief", {}), ("get_todo_list", {}), ("list_courses", {}),
             ("get_course_items", {"course_id": "cse310"}),
             ("get_course_materials", {"course_id": "cse310"}),
             ("get_item_details", {"item_id": "cse310-a3"}),
             ("mark_item_done_locally", {"item_id": "cse310-a3"}),
             ("unmark_item_done", {"item_id": "cse310-a3"})]
    for name, args in calls:
        _, out = call(client, name, args)
        assert out["speak"] and len(out["speak"].split()) <= 35, (name, out["speak"])


def test_brief_is_compact_and_uses_short_names(client):
    res, brief = call(client, "get_daily_brief", {"days": 7})
    assert len(res["content"][0]["text"]) < 3000  # was ~3.6k for 7 items before; stays small
    first = brief["items"][0]
    assert set(first) == {"id", "course", "title", "due", "points", "type", "source_url"}
    assert first["course"] == "CSE 310" and first["title"] == "Homework 3"
    assert "what_to_do" not in first and "notes" not in first
    _, courses = call(client, "list_courses")
    assert courses["speak"] == "You're taking CSE 310 and MAT 343."


def test_item_details_keep_steps_but_say_one_line(client):
    _, d = call(client, "get_item_details", {"item_id": "cse310-a3"})
    assert d["steps"] and d["speak"].startswith("Homework 3 for CSE 310")
    assert d["full_title"] == "Homework 3: AVL Trees"


def test_materials_list_is_capped(client):
    _, m = call(client, "get_course_materials", {"course_id": "cse310", "limit": 2})
    assert m["total"] == 5 and m["shown"] == 2 and len(m["materials"]) == 2
    assert set(m["materials"][0]) <= {"id", "title", "type", "module", "text_status", "week"}
