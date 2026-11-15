from datetime import datetime, timezone

def test_health_before_sync(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "backend": "mock", "llm": "off (rules only)",
                        "last_sync": None, "last_error": None}


def test_sync_counts(client):
    r = client.post("/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "mock" and body["data_source"] == "demo"
    assert body["llm_used"] is False
    c = body["counts"]
    assert c["courses"] == 2 and c["items"] == 8 and c["materials"] == 3
    assert c["assignment"] == 4 and c["quiz"] == 2 and c["exam"] == 1 and c["unknown"] == 1
    assert c["submitted"] == 2  # HW2 (past) + Weekly Check-in 7


def test_courses(client):
    r = client.get("/courses")
    assert r.status_code == 200
    assert [c["code"] for c in r.json()["courses"]] == ["CSE 310", "MAT 343"]


def test_todo_list_excludes_submitted_and_events(client):
    body = client.get("/items/next?days=7").json()
    items = body["items"]
    assert body["data_source"] == "demo"
    assert all(i["in_todo"] and not i["submitted"] for i in items)
    titles = {i["title"] for i in items}
    assert "Weekly Check-in 7" not in titles  # submitted -> gone
    assert "Homework 2: Heaps" not in titles  # past due -> gone
    dues = [datetime.fromisoformat(i["due_at"]) for i in items]
    assert dues == sorted(dues) and all(d >= datetime.now(timezone.utc) for d in dues)
    by_title = {i["title"]: i for i in items}
    assert by_title["Homework 3: AVL Trees"]["what_to_do"]
    assert by_title["Quiz 5: Eigenvalues"]["suggested_action"] == "schedule_block"
    exam = by_title["Midterm 2"]
    assert exam["type"] == "exam" and exam["suggested_action"] == "exam_prep"
    assert exam["topics"] == ["AVL trees", "heaps", "hashing"]


def test_include_done_shows_submitted_with_reason(client):
    items = client.get("/items/next?days=7&include_done=true").json()["items"]
    checkin = next(i for i in items if i["title"] == "Weekly Check-in 7")
    assert checkin["submitted"] is True and checkin["in_todo"] is False
    assert checkin["todo_reason"] == "Already submitted in Canvas"


def test_items_next_window(client):
    two_days = client.get("/items/next?days=2").json()["items"]
    assert {i["title"] for i in two_days} <= {"Homework 3: AVL Trees"}
    assert client.get("/items/next?days=0").status_code == 422


def test_items_filter_by_course(client):
    items = client.get("/items?course_id=mat343").json()["items"]
    assert items and all(i["course_id"] == "mat343" for i in items)
    assert client.get("/items?course_id=nope").json()["items"] == []


def test_materials(client):
    mats = client.get("/materials?course_id=cse310").json()["materials"]
    assert [m["title"] for m in mats] == ["Lecture 9 - AVL Trees", "Lecture 10 - Heaps"]
    assert all(m["extracted_text"] for m in mats)


def test_cache_reused_within_ttl(client):
    first = client.get("/items/next").json()["synced_at"]
    second = client.get("/courses").json()["synced_at"]
    assert first == second
    assert client.get("/health").json()["last_sync"] is not None


def test_tinyfish_without_keys_fails_cleanly(make_client):
    c = make_client(browser_backend="tinyfish", tinyfish_api_key="", tinyfish_profile_id="")
    r = c.post("/sync")
    assert r.status_code == 502 and "TINYFISH_API_KEY" in r.json()["detail"]
    assert c.get("/health").json()["ok"] is False
