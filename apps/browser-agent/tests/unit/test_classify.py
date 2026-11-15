import json
from pathlib import Path

import pytest

from app.classify import LLMResult, classify
from app.models import DataSource, ItemType, RawItem, SuggestedAction

CASES = json.loads((Path(__file__).parents[1] / "fixtures" / "classify_cases.json").read_text())
D = DataSource.demo


def make_raw(**fields) -> RawItem:
    return RawItem(id="x", course_id="c", url="https://canvas.asu.edu/x", **fields)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_rule_cases(case):
    item = classify(make_raw(**case["raw"]), course_code="C 100", data_source=D)
    assert item.type.value == case["expect_type"]
    assert item.classified_by.value == case["expect_by"]
    assert item.reason  # every decision explains itself


def test_actions_follow_type():
    hw = classify(make_raw(source_kind="assignment_list", title="HW"), "C", D)
    quiz = classify(make_raw(source_kind="quiz_list", title="Quiz 1"), "C", D)
    exam = classify(make_raw(source_kind="calendar_event", title="Midterm"), "C", D)
    assert hw.suggested_action == SuggestedAction.summarize_steps
    assert quiz.suggested_action == SuggestedAction.schedule_block
    assert exam.suggested_action == SuggestedAction.exam_prep


# ---------- to-do filter ----------

def test_not_submitted_work_is_in_todo():
    item = classify(make_raw(source_kind="assignment_list", title="HW", submitted=False), "C", D)
    assert item.in_todo and item.todo_reason == "Not submitted yet"


@pytest.mark.parametrize("flags,reason", [
    ({"submitted": True}, "Already submitted in Canvas"),
    ({"excused": True}, "Excused in Canvas"),
    ({"marked_complete": True}, "Marked complete in the Canvas planner"),
])
def test_done_work_is_not_in_todo(flags, reason):
    item = classify(make_raw(source_kind="quiz_list", title="Quiz 4", **flags), "C", D)
    assert not item.in_todo and item.todo_reason == reason


def test_events_are_not_todo():
    item = classify(make_raw(source_kind="calendar_event", title="TA Office Hours"), "C", D)
    assert not item.in_todo


def test_llm_can_never_put_submitted_work_back():
    llm = LLMResult(type=ItemType.quiz, confidence=0.99, reason="quiz", include_in_todo=True)
    item = classify(make_raw(source_kind="quiz_list", title="Q", submitted=True), "C", D, llm)
    assert not item.in_todo and item.todo_reason == "Already submitted in Canvas"


def test_llm_can_drop_non_work_from_todo():
    llm = LLMResult(type=ItemType.assignment, confidence=0.9,
                    reason="Optional ungraded survey", include_in_todo=False)
    item = classify(make_raw(source_kind="assignment_list", title="Survey"), "C", D, llm)
    assert not item.in_todo and "Optional ungraded survey" in item.todo_reason


# ---------- LLM merge ----------

def test_llm_decides_unknowns_and_fills_steps():
    llm = LLMResult(type=ItemType.exam, confidence=0.9, reason="says midterm next week",
                    topics=["heaps"], what_to_do=["Review lecture 10"], notes=["Bring calculator"])
    item = classify(make_raw(source_kind="announcement", title="Next week"), "C", D, llm)
    assert item.type == ItemType.exam and item.classified_by.value == "llm"
    assert item.topics == ["heaps"] and item.what_to_do == ["Review lecture 10"]
    assert item.notes == ["Bring calculator"] and item.confidence == 0.9


def test_llm_upgrades_quiz_to_exam_but_not_assignment_to_quiz():
    exam = LLMResult(type=ItemType.exam, confidence=0.9, reason="this is the midterm")
    item = classify(make_raw(source_kind="quiz_list", title="Module 6 test window"), "C", D, exam)
    assert item.type == ItemType.exam and item.classified_by.value == "llm"

    quiz = LLMResult(type=ItemType.quiz, confidence=0.9, reason="feels like a quiz")
    item = classify(make_raw(source_kind="assignment_list", title="Report"), "C", D, quiz)
    assert item.type == ItemType.assignment and item.classified_by.value == "rule"


def test_low_confidence_llm_is_ignored():
    unsure = LLMResult(type=ItemType.exam, confidence=0.4, reason="maybe", include_in_todo=False)
    item = classify(make_raw(source_kind="announcement", title="Hmm"), "C", D, unsure, threshold=0.7)
    assert item.type == ItemType.unknown and "not confident" in item.reason

    hw = classify(make_raw(source_kind="assignment_list", title="HW"), "C", D, unsure)
    assert hw.in_todo  # low-confidence LLM can't drop real work


def test_lockdown_note_from_canvas():
    item = classify(make_raw(source_kind="quiz_list", title="Q", requires_lockdown=True), "C", D)
    assert item.notes == ["Requires Respondus LockDown Browser"]
    by_title = classify(make_raw(source_kind="quiz_list",
                                 title="Quiz 5 - Requires Respondus LockDown Browser + Webcam"), "C", D)
    assert by_title.notes == ["Requires Respondus LockDown Browser"]
