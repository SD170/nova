"""GET /materials (listing) and GET /materials/{id}/text (on-demand text)."""


def test_listing_has_modules_weeks_and_no_text(client):
    mats = client.get("/materials?course_id=cse310").json()["materials"]
    by_id = {m["id"]: m for m in mats}
    assert set(by_id) == {"syllabus-cse310", "page-cse310-lecture-9", "file-310010",
                          "file-310099", "link-cse310-77"}
    page = by_id["page-cse310-lecture-9"]
    assert page["module"] == "Module 4: Balanced Trees" and page["week_start"]
    assert "text" not in page and "fetch_ref" not in page


def test_prefetched_texts_are_ready_others_not(client):
    mats = {m["id"]: m for m in client.get("/materials").json()["materials"]}
    assert mats["syllabus-cse310"]["text_status"] == "ready"
    assert mats["page-cse310-lecture-9"]["text_status"] == "ready"   # this week
    assert mats["file-310099"]["text_status"] == "too_large"
    assert mats["link-cse310-77"]["text_status"] == "link_only"


def test_topic_hint_and_this_week_filters(client):
    hits = client.get("/materials?topic_hint=heaps").json()["materials"]
    assert [m["id"] for m in hits] == ["file-310010"]
    week = {m["id"] for m in client.get("/materials?course_id=cse310&this_week=true")
            .json()["materials"]}
    assert "file-310099" not in week and "syllabus-cse310" in week


def test_text_with_page_markers_and_citation_fields(client):
    t = client.get("/materials/file-310010/text").json()
    assert t["text"].startswith("[page 1]") and t["pages"] == 2
    assert t["source_url"] and t["module"] == "Module 5: Heaps" and t["next_offset"] is None


def test_text_slices(client):
    t = client.get("/materials/page-cse310-lecture-9/text?max_chars=1000").json()
    assert t["total_chars"] == len(t["text"])  # short page = one slice


def test_text_unavailable_and_unknown(client):
    r = client.get("/materials/file-310099/text")
    assert r.status_code == 422 and r.json()["error"] == "material_text_unavailable"
    r = client.get("/materials/link-cse310-77/text")
    assert r.status_code == 422
    r = client.get("/materials/nope/text")
    assert r.status_code == 404 and r.json()["error"] == "material_not_found"


def test_materials_need_key(make_client):
    c = make_client(canvas_api_key="k")
    assert c.get("/materials").status_code == 401
    assert c.get("/materials/file-310010/text").status_code == 401
    assert c.get("/materials/file-310010/text", headers={"X-Canvas-Key": "k"}).status_code == 200
