"""Canvas JSON -> RawItem conversion, using made-up items shaped exactly like
real /api/v1/planner/items responses (no real student data in the repo)."""

from app.backends.tinyfish import apply_assignment_detail, html_to_text, planner_item_to_raw
from app.models import SourceKind

BASE = "https://canvas.asu.edu"


def planner(ptype, pid, title, submissions, **plannable):
    return {
        "plannable_type": ptype, "plannable_id": pid, "course_id": 111,
        "html_url": f"/courses/111/{ptype}s/{pid}",
        "plannable": {"id": pid, "title": title, **plannable},
        "submissions": submissions, "planner_override": None,
    }


SUBMITTED = {"submitted": True, "excused": False, "graded": True, "missing": False}
OPEN = {"submitted": False, "excused": False, "graded": False, "missing": False}


def test_submitted_quiz():
    it = planner("quiz", 5, "Graded Quiz: Module 4", SUBMITTED, assignment_id=900,
                 due_at="2026-11-16T06:59:59Z", points_possible=24.0)
    raw = planner_item_to_raw(it, BASE)
    assert raw.source_kind == SourceKind.quiz_list
    assert raw.submitted is True and raw.graded is True
    assert raw.canvas_assignment_id == "900"
    assert raw.due_at.isoformat() == "2026-11-16T06:59:59+00:00"
    assert raw.url == BASE + it["html_url"]  # relative Canvas links become absolute
    assert raw.id == "quiz-5" and raw.course_id == "111"


def test_open_assignment_uses_own_id_for_details():
    it = planner("assignment", 77, " Assignment 3 ", OPEN, due_at="2026-11-16T06:59:59Z",
                 points_possible=40.0)
    raw = planner_item_to_raw(it, BASE)
    assert raw.title == "Assignment 3" and raw.submitted is False
    assert raw.canvas_assignment_id == "77" and raw.points == 40.0


def test_calendar_event_has_no_submission():
    it = planner("calendar_event", 3, "TA Office Hours", False,
                 start_at="2026-11-18T16:00:00Z", description="<p>Room <b>210</b></p>")
    it["html_url"] = "https://canvas.asu.edu/calendar?event_id=3"
    raw = planner_item_to_raw(it, BASE)
    assert raw.source_kind == SourceKind.calendar_event
    assert raw.submitted is None and raw.canvas_assignment_id is None
    assert raw.body_text == "Room 210"
    assert raw.url == "https://canvas.asu.edu/calendar?event_id=3"


def test_marked_complete_and_unsupported_types():
    it = planner("discussion_topic", 9, "Graded Discussion", OPEN, assignment_id=55)
    it["planner_override"] = {"marked_complete": True}
    raw = planner_item_to_raw(it, BASE)
    assert raw.source_kind == SourceKind.discussion and raw.marked_complete is True
    assert planner_item_to_raw(planner("planner_note", 1, "note", False), BASE) is None


def test_detail_merge():
    raw = planner_item_to_raw(planner("quiz", 5, "Q", OPEN, assignment_id=900), BASE)
    out = apply_assignment_detail(raw, {
        "description": "<ol><li>Read ch. 5</li><li>Submit &amp; relax</li></ol>",
        "submission_types": ["online_quiz"], "require_lockdown_browser": True,
        "points_possible": 10})
    assert out.submission_types == ["online_quiz"] and out.requires_lockdown is True
    assert "- Read ch. 5" in out.body_text and "Submit & relax" in out.body_text
    assert out.points == 10


def test_friendly_course_code():
    from app.backends.tinyfish import friendly_code
    assert friendly_code({"course_code": "2026FallC-T-CSE579-73246",
                          "name": "CSE 579: Knowledge Representation (2026 Fall C)"}) == "CSE 579"
    assert friendly_code({"course_code": "DEV-2024", "name": "Career Dev Course"}) == "DEV-2024"


def test_html_to_text_handles_empty():
    assert html_to_text(None) == "" and html_to_text("") == ""
