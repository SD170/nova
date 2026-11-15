"""Supermemory: memory tools for the brain, auto-saved quiz results, and the weak-topic loop."""

import json

import pytest

from app.memory import quiz_result_text
from app.models import MemoryUnavailable
from app.quiz_models import Quiz
from tests.api.test_exam import wait_for_pdf
from tests.api.test_mcp import call


@pytest.fixture
def mem_client(make_client, tmp_path, fake_exam, fake_memory):
    return make_client(gemini_api_key="t", supermemory_api_key="k", nova_exam_dir=tmp_path / "Nova")


def full_quiz(c, qid) -> Quiz:
    return Quiz(**json.loads(c.app.state.service.exam._path(qid).read_text()))


# ---------- memory tools ----------

def test_remember_then_recall_then_forget(mem_client, fake_memory):
    _, saved = call(mem_client, "memory_remember", {"fact": "Abishek prefers studying in the evening"})
    assert saved["speak"] == "Got it, I'll remember that."
    _, r = call(mem_client, "memory_recall", {"query": "when does he study in the evening"})
    assert r["speak"] == "I remember: Abishek prefers studying in the evening." and len(r["results"]) == 1
    call(mem_client, "memory_forget", {"query": "studying evening"})
    _, r = call(mem_client, "memory_recall", {"query": "studying evening"})
    assert r["speak"] == "I don't remember anything about that yet."


def test_profile_speaks_a_few_facts(mem_client):
    _, p = call(mem_client, "memory_profile")
    assert p["speak"] == "I know: Prefers short spoken answers." and p["static"] == ["Prefers short spoken answers"]


def test_a_too_short_fact_is_refused(mem_client):
    res, _ = call(mem_client, "memory_remember", {"fact": "yes"})
    assert res["isError"]


def test_memory_without_a_key_says_so():
    from app.memory import MemoryClient
    import asyncio
    with pytest.raises(MemoryUnavailable, match="SUPERMEMORY_API_KEY"):
        asyncio.run(MemoryClient("", "ns")._req("POST", "/search", {}))


def test_memory_errors_are_clear_tool_errors(mem_client, fake_memory):
    fake_memory["error"] = "Supermemory rejected the key (SUPERMEMORY_API_KEY)."
    res, _ = call(mem_client, "memory_recall", {"query": "anything"})
    assert res["isError"] and "rejected the key" in res["content"][0]["text"]
    assert mem_client.get("/memory/profile").status_code == 503


def test_rest_routes_for_the_memory_tab(mem_client):
    mem_client.post("/memory/remember", json={"fact": "Wants an AI internship next summer"})
    assert "AI internship" in mem_client.get("/memory/recall", params={"q": "internship"}).json()["results"][0]["text"]
    assert mem_client.get("/memory/profile").json()["static"] == ["Prefers short spoken answers"]
    assert mem_client.get("/memory/recent").json()["recent"][0]["text"].startswith("Wants an AI")


# ---------- quiz result is saved automatically ----------

def finish_quiz(c, wrong_first=2):
    qid = c.post("/quiz/start", json={"course": "CSE 540", "topic": "module 5"}).json()["id"]
    wait_for_pdf(c, qid)
    c.post(f"/quiz/{qid}/begin", json={"mode": "panel"})
    q = full_quiz(c, qid)
    for i, qu in enumerate(q.questions):
        pick = (qu.answer + 1) % 4 if i < wrong_first else qu.answer
        c.post(f"/quiz/{qid}/answer", json={"choice": "ABCD"[pick], "index": i})
    return qid, q


def test_finished_quiz_is_saved_to_memory_with_weak_and_strong_topics(mem_client, fake_memory):
    qid, q = finish_quiz(mem_client)
    doc = next(d for d in fake_memory["docs"] if d["id"] == f"quiz_{qid}")
    assert doc["metadata"]["kind"] == "quiz_result" and doc["metadata"]["course"] == "CSE 540"
    assert doc["metadata"]["score"] == 4 and doc["metadata"]["total"] == 6
    wrong_topics = {q.questions[0].topic, q.questions[1].topic}
    assert set(doc["metadata"]["weak"].split("|")) == wrong_topics
    assert "Weak on" in doc["content"] and "4 of 6" in doc["content"]
    kinds = [e["kind"] for e in mem_client.get("/panel/feed").json()["events"]]
    assert kinds == ["quiz_ready", "pdf_saved", "quiz_panel", "quiz_score", "memory"]
    memory_event = mem_client.get("/panel/feed").json()["events"][-1]
    assert memory_event["data"]["quiet"] is True        # panel shows it, but no toast


def test_next_quiz_leans_on_the_weak_topics(mem_client, fake_exam):
    qid, q = finish_quiz(mem_client)
    weak = q.questions[0].topic
    mem_client.post("/quiz/start", json={"course": "CSE 540", "topic": "module 5"})
    assert f"weak on: " in fake_exam["last_user_text"] and weak in fake_exam["last_user_text"]


def test_first_quiz_has_no_weak_hint(mem_client, fake_exam):
    mem_client.post("/quiz/start", json={"course": "CSE 540", "topic": "module 5"})
    assert "weak on" not in fake_exam["last_user_text"]


def test_a_memory_failure_never_breaks_the_quiz(mem_client, fake_memory):
    fake_memory["error"] = "Could not reach supermemory (boom)."
    qid, _ = finish_quiz(mem_client)
    assert mem_client.get(f"/quiz/{qid}").json()["status"] == "done"      # quiz still completes
    assert mem_client.get(f"/quiz/{qid}").json()["score"] == 4


def test_no_key_no_memory_calls(make_client, tmp_path, fake_exam, fake_memory):
    c = make_client(gemini_api_key="t", supermemory_api_key="", nova_exam_dir=tmp_path / "N")
    finish_quiz(c)
    assert fake_memory["calls"] == []                                     # memory simply stays off


def test_quiz_result_text_unit():
    from datetime import datetime, timezone
    from app.quiz_models import QuizQuestion
    qs = [QuizQuestion(q="q", options=list("abcd"), answer=0, topic=t) for t in ("heaps", "avl", "heaps")]
    quiz = Quiz(id="z", course_id="1", course_code="CSE 310", title="CSE 310 Heaps Quiz",
                created_at=datetime.now(timezone.utc), questions=qs, answers={0: 1, 1: 0, 2: 0}, score=2)
    text, meta = quiz_result_text(quiz)
    assert meta["weak"] == "heaps" and meta["strong"] == "avl" and meta["course"] == "CSE 310"
    assert "2 of 3" in text and "Weak on heaps" in text
