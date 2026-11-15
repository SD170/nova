"""Voice-sized answers: short codes, short titles, spoken due dates, one-line speak."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Item, ItemType
from app.voice import (
    PHX,
    compact_item,
    due_label,
    join_words,
    short_course,
    short_title,
    speak_courses,
    speak_item,
    speak_todo,
)

NOW = datetime(2026, 11, 15, 10, 0, tzinfo=PHX)  # Sunday


@pytest.mark.parametrize("code,expected", [
    ("BMI/BME/CEN/CSE507-494", "CSE 507"),
    ("CSE 540", "CSE 540"),
    ("MAT343", "MAT 343"),
    ("Some Odd Course Name", "Some Odd Cou"),
])
def test_short_course(code, expected):
    assert short_course(code) == expected


@pytest.mark.parametrize("title,expected", [
    ("Graded Quiz: Module 5  - Requires Respondus LockDown Browser + Webcam", "Module 5 quiz"),
    ("Graded Discussion Prompt: Module 5 - Navigating Resources", "Module 5 discussion"),
    ("Assignment 3: More Challenging Answer Set Programming", "Assignment 3"),
    ("Course Project- HC:  Milestone 1 - Individual Progress Report", "Milestone 1"),
    ("Demo 3: 2D+3D and EHR", "Demo 3"),
    ("Presentation (covering all your solutions and accomplishments)", "Presentation"),
    ("Full Warm-up Report", "Full Warm-up Report"),
    ("HW 4: Hash tables", "HW 4"),
    ("Midterm 2", "Midterm 2"),
])
def test_short_title(title, expected):
    assert short_title(title) == expected


def test_short_title_never_long():
    assert len(short_title("An extremely long assignment name " * 6)) <= 40


def test_due_label_reads_like_a_person():
    def at(days, hour=23, minute=59):
        return (NOW + timedelta(days=days)).replace(hour=hour, minute=minute)

    assert due_label(at(0), NOW) == "today 11:59 PM"
    assert due_label(at(1, 9, 5), NOW) == "tomorrow 9:05 AM"
    assert due_label(at(3), NOW) == "Wednesday 11:59 PM"
    assert due_label(at(13), NOW) == "Nov 28"
    assert due_label(at(-2), NOW) == "overdue since Nov 13"
    assert due_label(None, NOW) == "no due date"
    # a UTC timestamp is converted to Phoenix time (06:59 UTC = 11:59 PM the day before)
    utc = datetime(2026, 11, 16, 6, 59, tzinfo=ZoneInfo("UTC"))
    assert due_label(utc, NOW) == "today 11:59 PM"


def item(title, code, due, points=None, steps=None, id="a-1"):
    return Item(id=id, course_id="c", course_code=code, type=ItemType.assignment, title=title,
                due_at=due, points=points, source_url="https://x", in_todo=True, todo_reason="",
                what_to_do=steps or [], suggested_action="none", classified_by="rule",
                data_source="demo")


def test_speak_todo_is_one_short_line():
    items = [item("Assignment 3: More Challenging Answer Set Programming", "CSE 579",
                  NOW.replace(hour=23, minute=59)),
             item("Demo 3: 2D+3D and EHR", "BMI/BME/CEN/CSE507-494", NOW + timedelta(days=5),
                  id="a-2")]
    s = speak_todo(items, 7, NOW)
    assert s == ("2 things due this week, 1 today. First: Assignment 3 for CSE 579, "
                 "today 11:59 PM.")
    assert len(s.split()) <= 25
    assert speak_todo([], 7, NOW) == "Nothing due this week."
    assert speak_todo(items[:1], 3, NOW).startswith("1 thing due in the next 3 days")


def test_speak_item_and_compact():
    i = item("Homework 4: Hash Tables", "CSE 310", NOW + timedelta(days=1), 50,
             ["Read chapter 5 and the lecture notes on chaining", "Submit a zip"])
    assert speak_item(i, NOW) == ("Homework 4 for CSE 310, due tomorrow 10:00 AM, 50 points. "
                                  "First step: Read chapter 5 and the lecture notes on chaining.")
    c = compact_item(i, NOW)
    assert c["course"] == "CSE 310" and c["title"] == "Homework 4" and c["points"] == 50
    assert "what_to_do" not in c and "notes" not in c


def test_courses_and_join():
    assert join_words(["a", "b", "c"]) == "a, b and c"
    assert join_words(["a", "b"]) == "a and b"
    assert join_words(["a"]) == "a"

    class C:
        def __init__(self, code):
            self.code = code

    assert speak_courses([C("CSE 579"), C("BMI/BME/CEN/CSE507-494"), C("CSE 540")]) == \
        "You're taking CSE 579, CSE 507 and CSE 540."
