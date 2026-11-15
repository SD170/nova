"""Exam prep: grounded exam facts + quiz, voice and panel modes, flashcard PDF, notifications."""

import json
import time

import pytest

from app.exam import parse_choice, quote_in_text, _norm
from app.pdfgen import build_flashcards_pdf
from app.quiz_models import Quiz, QuizQuestion
from tests.api.test_mcp import call, rpc


@pytest.fixture
def exam_client(make_client, tmp_path, fake_exam):
    c = make_client(gemini_api_key="test-key", nova_exam_dir=tmp_path / "Nova" / "Exam Prep")
    c.exam_dir = tmp_path / "Nova" / "Exam Prep"
    return c


def wait_for_pdf(c, quiz_id, seconds=6):
    end = time.time() + seconds
    while time.time() < end:
        v = c.get(f"/quiz/{quiz_id}").json()
        if v["pdf_status"] != "pending":
            return v
        time.sleep(0.1)
    return c.get(f"/quiz/{quiz_id}").json()


# ---------- helpers ----------

def test_quote_check_is_loose_about_whitespace_but_strict_about_content():
    text = _norm("Final Exam   Dec 1, 2026  Dec 4, 2026\nThe final covers all modules.")
    assert quote_in_text("Final Exam Dec 1, 2026 Dec 4, 2026", text)
    assert not quote_in_text("The midterm is on October fifth for everyone", text)
    assert not quote_in_text("too short", text)


@pytest.mark.parametrize("answer,expected", [("B", 1), ("b.", 1), ("option c", 2), ("4", 3), (0, 0),
                                              ("Hashing", 1), ("zebra", None), ("", None)])
def test_parse_choice(answer, expected):
    assert parse_choice(answer, ["Rotations", "Hashing", "Sorting", "Chaining"]) == expected


# ---------- exam facts ----------

def test_exam_info_keeps_only_dates_that_are_in_the_syllabus(exam_client):
    r = exam_client.post("/exam/info", json={"course": "CSE 540"}).json()
    assert [e["name"] for e in r["exams"]] == ["Final Exam"]       # the invented midterm is dropped
    assert r["exams"][0]["page"] == 5 and r["course_code"] == "CSE 540"
    _, m = call(exam_client, "exam_info", {"course": "cse540"})
    assert m["speak"] == "CSE 540: Final Exam, Dec 1, 2026 Dec 4, 2026. Covers all modules."


def test_exam_info_unknown_course_is_a_clear_error(exam_client):
    r = exam_client.post("/exam/info", json={"course": "ART 101"})
    assert r.status_code == 422 and "CSE 540" in r.json()["detail"]


# ---------- quiz ----------

def test_quiz_drops_ungrounded_questions_and_keeps_six(exam_client):
    v = exam_client.post("/quiz/start", json={"course": "CSE 540", "topic": "module 5"}).json()
    assert v["total"] == 6 and v["status"] == "ready" and v["course_code"] == "CSE 540"
    assert v["title"] == "CSE 540 Module 5 Quiz"
    assert all(len(q["options"]) == 4 for q in v["questions"])
    assert v["review"] is None and all(q["chosen"] is None for q in v["questions"])
    assert "answer" not in v["questions"][0]                         # answers are not leaked


def test_too_few_grounded_questions_is_a_clear_error(exam_client, fake_exam):
    fake_exam["quiz_rows"] = [dict(r) for r in fake_exam["quiz_rows"][-2:]]
    r = exam_client.post("/quiz/start", json={"course": "CSE 540"})
    assert r.status_code == 422 and "solid question" in r.json()["detail"]


def test_options_are_shuffled_but_the_right_answer_is_tracked(exam_client):
    q = exam_client.post("/quiz/start", json={"course": "CSE 540"}).json()
    full = Quiz(**json.loads(exam_client.app.state.service.exam._path(q["id"]).read_text()))
    # the correct text for 'Time to insert into a heap?' is O(log n) wherever it ended up
    ins = next(x for x in full.questions if x.q.startswith("Time to insert"))
    assert ins.options[ins.answer] == "O(log n)"


def test_logistics_questions_are_filtered_out(exam_client, fake_exam):
    from tests.conftest import GOOD_QUESTIONS, _q
    video = _q("What is the runtime of the intro video?", ["1", "2", "3", "4"], 0,
               "each parent is less than or equal to its children")
    fake_exam["quiz_rows"] = [video] + GOOD_QUESTIONS
    v = exam_client.post("/quiz/start", json={"course": "CSE 540"}).json()
    assert v["total"] == 6 and all("runtime" not in q["q"] for q in v["questions"])


# ---------- voice, one by one ----------

def test_voice_quiz_one_by_one_then_score(exam_client):
    _, started = call(exam_client, "quiz_start", {"course": "CSE 540", "topic": "module 5"})
    assert started["speak"] == "Quiz ready: 6 questions on module 5. Voice or side panel?"
    qid = started["quiz_id"]
    _, first = call(exam_client, "quiz_begin", {"quiz_id": qid, "mode": "voice"})
    assert first["speak"].startswith("Question 1. ") and "A, " in first["speak"]
    assert len(first["speak"]) <= 240                                # fits Nova's spoken cap

    full = Quiz(**json.loads(exam_client.app.state.service.exam._path(qid).read_text()))
    last = None
    for i, qu in enumerate(full.questions):
        right = "ABCD"[qu.answer]
        wrong = "ABCD"[(qu.answer + 1) % 4]
        _, last = call(exam_client, "quiz_answer", {"quiz_id": qid, "answer": right if i < 4 else wrong})
        if i < 5:
            assert last["done"] is False and last["speak"].startswith(f"Question {i + 2}.")
            assert "correct" not in last["speak"].lower()            # no per-question reveal
    assert last["done"] is True and last["score"] == 4 and last["total"] == 6
    assert last["speak"].startswith("You got 4 out of 6.") and "Weak on" in last["speak"]
    _, st = call(exam_client, "quiz_status", {"quiz_id": qid})
    assert st["status"] == "done" and "4 out of 6" in st["speak"]


def test_unclear_voice_answer_asks_again(exam_client):
    _, s = call(exam_client, "quiz_start", {"course": "CSE 540"})
    call(exam_client, "quiz_begin", {"quiz_id": s["quiz_id"]})
    res, _ = call(exam_client, "quiz_answer", {"quiz_id": s["quiz_id"], "answer": "banana"})
    assert res["isError"] and "Answer A, B, C or D" in res["content"][0]["text"]


# ---------- panel mode ----------

def test_panel_quiz_answers_by_index_then_finish_counts_unanswered_as_wrong(exam_client):
    qid = exam_client.post("/quiz/start", json={"course": "CSE 540"}).json()["id"]
    v = exam_client.post(f"/quiz/{qid}/begin", json={"mode": "panel"}).json()
    assert v["mode"] == "panel" and v["status"] == "in_progress"
    full = Quiz(**json.loads(exam_client.app.state.service.exam._path(qid).read_text()))
    for i in (2, 0):   # any order
        v = exam_client.post(f"/quiz/{qid}/answer", json={"choice": "ABCD"[full.questions[i].answer], "index": i}).json()
    assert v["answered"] == 2 and v["status"] == "in_progress" and v["review"] is None
    done = exam_client.post(f"/quiz/{qid}/finish").json()
    assert done["status"] == "done" and done["score"] == 2
    assert [r["correct"] for r in done["review"]] == [True, False, True, False, False, False]
    assert done["review"][1]["explanation"] and done["review"][0]["source"]


def test_unknown_quiz_is_404(exam_client):
    r = exam_client.get("/quiz/abcdef123456")
    assert r.status_code == 404 and r.json()["error"] == "quiz_not_found"
    assert exam_client.get("/quiz/latest").status_code == 404


# ---------- PDF + notifications ----------

def test_pdf_is_made_in_the_background_saved_and_announced(exam_client):
    qid = exam_client.post("/quiz/start", json={"course": "CSE 540", "topic": "module 5"}).json()["id"]
    v = wait_for_pdf(exam_client, qid)
    assert v["pdf_status"] == "saved" and v["saved_path"].endswith("CSE-540-Module-5-Quiz-cards.pdf")
    saved = exam_client.exam_dir.glob("*.pdf")
    files = list(saved)
    assert len(files) == 1 and files[0].read_bytes()[:4] == b"%PDF" and files[0].stat().st_size < 60_000

    events = exam_client.get("/panel/feed").json()["events"]
    assert [e["kind"] for e in events] == ["quiz_ready", "pdf_saved"]
    pdf = events[1]
    assert pdf["data"]["filename"].endswith(".pdf") and pdf["data"]["saved_path"] == v["saved_path"]
    got = exam_client.get(f"/files/{pdf['data']['document_id']}")     # the app downloads this copy
    assert got.status_code == 200 and got.content[:4] == b"%PDF"
    assert exam_client.get("/panel/feed?since=2").json()["events"] == []   # polling with the last id


def test_notifications_stay_meaningful(exam_client):
    """Only: quiz ready, PDF saved, (panel opened), score. Nothing per answer."""
    qid = exam_client.post("/quiz/start", json={"course": "CSE 540"}).json()["id"]
    wait_for_pdf(exam_client, qid)
    exam_client.post(f"/quiz/{qid}/begin", json={"mode": "panel"})
    for i in range(6):
        exam_client.post(f"/quiz/{qid}/answer", json={"choice": "A", "index": i})
    kinds = [e["kind"] for e in exam_client.get("/panel/feed").json()["events"]]
    assert kinds == ["quiz_ready", "pdf_saved", "quiz_panel", "quiz_score"]


def test_flashcard_pdf_is_small_and_handles_odd_characters():
    qs = [QuizQuestion(q="What is the ≤ bound — for α?", options=["a & b", "<tag>", "c", "d"],
                       answer=0, explanation="Because ≈ equal.", topic="bounds",
                       source_title="Slides.pdf", page=3) for _ in range(6)]
    from datetime import datetime, timezone
    quiz = Quiz(id="x", course_id="1", course_code="CSE 540", title="CSE 540 Test Quiz",
                created_at=datetime.now(timezone.utc), questions=qs)
    data = build_flashcards_pdf(quiz)
    assert data[:4] == b"%PDF" and 2_000 < len(data) < 40_000


def test_quiz_tools_are_listed_and_need_the_key(make_client, fake_exam):
    c = make_client(canvas_api_key="k", gemini_api_key="t")
    assert rpc(c, "tools/list").status_code == 401
    assert c.post("/quiz/start", json={"course": "CSE 540"}).status_code == 401


# ---------- fast Vapi tool for the voice quiz ----------

def vapi(c, name, **args):
    body = {"message": {"call": {"id": "call-1"},
                        "toolCalls": [{"id": "tc-9", "function": {"name": name, "arguments": args}}]}}
    r = c.post("/vapi/quiz", json=body)
    assert r.status_code == 200
    out = r.json()["results"]
    assert out[0]["toolCallId"] == "tc-9"
    return out[0]["result"]


def test_vapi_quiz_tool_answers_fast_and_stays_in_the_quiz(exam_client):
    assert "no quiz in progress" in vapi(exam_client, "quiz_answer", answer="A")
    qid = exam_client.post("/quiz/start", json={"course": "CSE 540"}).json()["id"]
    exam_client.post(f"/quiz/{qid}/begin", json={"mode": "voice"})
    assert vapi(exam_client, "quiz_repeat").startswith("Question 1. ")
    assert vapi(exam_client, "quiz_answer", answer="A").startswith("Question 2. ")
    assert vapi(exam_client, "quiz_repeat").startswith("Question 2. ")
    assert "Answer A, B, C or D" in vapi(exam_client, "quiz_answer", answer="banana")
    last = ""
    for _ in range(5):   # question 1 is already answered above: five more finish the six
        last = vapi(exam_client, "quiz_answer", answer="B")
    assert last.startswith(("You got", "Perfect"))
    assert "no quiz in progress" in vapi(exam_client, "quiz_answer", answer="A")   # finished


def test_vapi_quiz_accepts_string_arguments_and_needs_the_key(make_client, fake_exam):
    c = make_client(canvas_api_key="k", gemini_api_key="t")
    body = {"message": {"toolCalls": [{"id": "x", "function": {"name": "quiz_answer",
                                                                 "arguments": '{"answer": "A"}'}}]}}
    assert c.post("/vapi/quiz", json=body).status_code == 401
    ok = c.post("/vapi/quiz", json=body, headers={"X-Canvas-Key": "k"})
    assert ok.status_code == 200 and "no quiz in progress" in ok.json()["results"][0]["result"]
