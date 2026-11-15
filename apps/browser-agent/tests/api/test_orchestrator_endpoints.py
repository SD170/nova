"""Endpoints Saswata's orchestrator asked for: /brief, /items/{id}, user-done, auth."""


def test_brief_bundles_todo_courses_and_age(client):
    b = client.get("/brief?days=7").json()
    assert b["data_source"] == "demo" and b["sync_in_progress"] is False
    assert 0 <= b["last_sync_age_minutes"] < 1
    assert [c["code"] for c in b["courses"]] == ["CSE 310", "MAT 343"]
    assert b["items"] and all(i["in_todo"] for i in b["items"])
    assert "Weekly Check-in 7" not in {i["title"] for i in b["items"]}  # submitted


def test_item_detail_and_404(client):
    item = client.get("/items/cse310-a3").json()
    assert item["title"] == "Homework 3: AVL Trees" and item["what_to_do"]
    r = client.get("/items/nope")
    assert r.status_code == 404 and r.json()["error"] == "item_not_found"


def test_items_next_still_routes_before_item_id(client):
    assert "items" in client.get("/items/next").json()


def test_user_done_removes_from_todo_and_survives_resync(client):
    r = client.post("/items/cse310-a3/user-done")
    assert r.status_code == 200
    body = r.json()
    assert body["in_todo"] is False and body["user_done"] is True
    assert "Marked done by student" in body["todo_reason"]
    todo = {i["id"] for i in client.get("/items/next").json()["items"]}
    assert "cse310-a3" not in todo

    client.post("/sync")  # Canvas (mock) still says "not submitted"
    todo = {i["id"] for i in client.get("/items/next").json()["items"]}
    assert "cse310-a3" not in todo  # override survives the sync
    assert client.get("/items/cse310-a3").json()["user_done"] is True


def test_undo_user_done(client):
    client.post("/items/cse310-a3/user-done")
    r = client.delete("/items/cse310-a3/user-done")
    assert r.json()["in_todo"] is True and r.json()["user_done"] is False
    client.post("/sync")
    assert "cse310-a3" in {i["id"] for i in client.get("/items/next").json()["items"]}


def test_user_done_on_submitted_item_is_a_no_op(client):
    client.get("/courses")  # first sync
    r = client.post("/items/mat343-c7/user-done")  # already submitted in Canvas
    assert r.json()["user_done"] is False and r.json()["todo_reason"] == "Already submitted in Canvas"


def test_user_done_before_any_sync_loads_canvas_first(client):
    r = client.post("/items/cse310-a3/user-done")
    assert r.status_code == 200 and r.json()["user_done"] is True


def test_user_done_unknown_item(client):
    client.get("/courses")
    assert client.post("/items/nope/user-done").status_code == 404


def test_api_key_required_when_set(make_client):
    c = make_client(browser_agent_api_key="s3cret")
    assert c.get("/health").status_code == 200  # health stays open
    assert c.get("/docs").status_code == 200  # docs stay open for judges
    assert c.get("/brief").status_code == 401
    assert c.get("/brief", headers={"X-Jarvis-Key": "wrong"}).status_code == 401
    assert c.get("/brief", headers={"X-Jarvis-Key": "s3cret"}).status_code == 200
    assert c.post("/sync").status_code == 401


def test_no_api_key_means_open_for_local_dev(client):
    assert client.get("/brief").status_code == 200
