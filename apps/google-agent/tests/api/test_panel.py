"""Side panel backend: one summary for every tab, each section independent, CORS for the app."""

import pytest

from app.models import NewsUnavailable
from tests.api.test_exam import wait_for_pdf


@pytest.fixture
def pc(make_client, tmp_path, fake_exam, fake_panel, fake_news, fake_memory):
    return make_client(gemini_api_key="t", supermemory_api_key="k", nova_exam_dir=tmp_path / "Nova")


def test_summary_has_every_tab_with_short_display_ready_data(pc):
    s = pc.get("/panel/summary").json()
    assert s["data_source"] == "demo"                      # mock backend
    for tab in ("today", "mail", "courses", "news", "linkedin", "memory"):
        assert s[tab]["ok"] is True, (tab, s[tab])
    due = s["today"]["due"][0]
    assert due["course"] == "CSE 507" and due["title"] == "Module 5 quiz" and due["due"].startswith("tomorrow")
    assert s["today"]["count"] == 1 and s["today"]["events"]            # calendar events too
    assert s["mail"]["important_count"] >= 1 and len(s["mail"]["emails"]) <= 6
    assert [c["code"] for c in s["courses"]["courses"]] == ["CSE 540", "CSE 507"]
    assert s["news"]["stories"][0]["source"] == "NPR"
    assert s["linkedin"]["people"][0]["name"] == "Avi Chawla" and s["linkedin"]["posts_seen"] == 25
    assert s["memory"]["enabled"] and s["memory"]["facts"] == ["Prefers short spoken answers"]
    assert s["saved"] == [] and s["quiz"] is None


def test_one_broken_source_does_not_blank_the_panel(pc, fake_news):
    fake_news["error"] = NewsUnavailable("Could not reach the news service")
    s = pc.get("/panel/summary").json()
    assert s["news"]["ok"] is False and "news service" in s["news"]["error"]
    assert s["today"]["ok"] and s["mail"]["ok"] and s["memory"]["ok"]


def test_saved_files_and_latest_quiz_show_up_after_a_quiz(pc):
    qid = pc.post("/quiz/start", json={"course": "CSE 540", "topic": "module 5"}).json()["id"]
    v = wait_for_pdf(pc, qid)
    pc.post("/exam/info", json={"course": "CSE 540"})
    s = pc.get("/panel/summary").json()
    f = s["saved"][0]
    assert f["kind"] == "quiz_cards" and f["course"] == "CSE 540" and f["format"] == "pdf"
    assert f["saved_path"] == v["saved_path"] and f["download_url"].endswith(f["id"])
    assert s["quiz"]["id"] == qid and s["quiz"]["total"] == 6 and s["quiz"]["review"] is None
    exam = next(c["exam"] for c in s["courses"]["courses"] if c["code"] == "CSE 540")
    assert exam == {"name": "Final Exam", "date": "Dec 1, 2026 Dec 4, 2026"}   # from the cache


def test_memory_tab_says_it_is_off_without_a_key(make_client, tmp_path, fake_exam, fake_panel, fake_news):
    c = make_client(gemini_api_key="t", supermemory_api_key="", nova_exam_dir=tmp_path / "N")
    assert c.get("/panel/summary").json()["memory"] == {"ok": True, "enabled": False, "facts": [], "recent": []}


def test_summary_needs_the_key(make_client):
    c = make_client(canvas_api_key="k")
    assert c.get("/panel/summary").status_code == 401


def test_cors_allows_the_app_and_nothing_else(make_client):
    c = make_client()
    ok = c.options("/panel/summary", headers={"Origin": "http://localhost:5173",
                                              "Access-Control-Request-Method": "GET",
                                              "Access-Control-Request-Headers": "x-canvas-key"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-canvas-key" in ok.headers["access-control-allow-headers"].lower()
    electron = c.options("/panel/summary", headers={"Origin": "null", "Access-Control-Request-Method": "GET"})
    assert electron.headers.get("access-control-allow-origin") == "null"
    evil = c.options("/panel/summary", headers={"Origin": "https://evil.example",
                                                "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in evil.headers
