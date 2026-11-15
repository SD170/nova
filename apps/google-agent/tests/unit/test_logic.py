"""Pure logic: email rules, Canvas -> calendar planning, free time, documents, Gmail parsing."""

import base64
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.backends.google import html_to_text, to_raw_email, walk_parts
from app.canvas_sync import desired_events, plan, to_spec, wanted
from app.classify import rule_classify
from app.documents import DocumentStore
from app.freebusy import compute_free
from app.models import Block, CalendarEvent, Category, DocumentNotFound, RawEmail
from tests.conftest import canvas_items

PHX = ZoneInfo("America/Phoenix")
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)


def email(**kw) -> RawEmail:
    base = dict(id="m1", from_name="X", from_email="x@example.com", subject="Hello",
                snippet="", date=NOW, unread=True, labels=["INBOX", "UNREAD"])
    base.update(kw)
    return RawEmail(**base)


# ---------- email rules ----------

def test_recruiter_mail_is_important_and_needs_reply():
    c = rule_classify(email(from_email="dana@northwind-labs.com",
                            subject="Software Engineer Intern: next steps?",
                            snippet="Are you available Thursday for a call?"))
    assert c.category == Category.recruiter and c.important and c.needs_reply


def test_promo_is_not_important_even_with_urgent_words():
    c = rule_classify(email(subject="Sale expires tonight!", labels=["CATEGORY_PROMOTIONS"]))
    assert c.category == Category.promo and not c.important and not c.needs_reply


def test_asu_tuition_mail_is_school_or_money_and_important():
    c = rule_classify(email(from_email="no-reply@asu.edu", subject="Payment due: tuition",
                            snippet="Your installment is due December 3."))
    assert c.category in (Category.school, Category.money) and c.important
    assert not c.needs_reply  # automated sender


def test_newsletter_and_notification_are_low_value():
    n = rule_classify(email(from_email="newsletter@x.com", subject="Weekly digest",
                            labels=["CATEGORY_UPDATES"]))
    assert n.category == Category.newsletter and not n.important
    a = rule_classify(email(from_email="no-reply@service.com", subject="Receipt",
                            labels=["CATEGORY_UPDATES"], unread=False))
    assert not a.important and not a.needs_reply


# ---------- Canvas -> calendar ----------

def test_wanted_rules():
    items = {i["id"]: i for i in canvas_items(NOW)}
    assert wanted(items["assignment-1"], NOW)
    assert wanted(items["event-9"], NOW)               # exam, even if not in to-do
    assert not wanted(items["assignment-3"], NOW)      # submitted
    assert not wanted(items["assignment-4"], NOW)      # marked done by the student
    assert not wanted(items["assignment-5"], NOW)      # already past
    assert not wanted(items["event-office"], NOW)      # plain event, not an exam


def test_spec_for_assignment_and_exam():
    items = {i["id"]: i for i in canvas_items(NOW)}
    hw = to_spec(items["assignment-1"])
    assert hw.title == "[CSE 540] Homework 4 (due)" and hw.canvas_item_id == "assignment-1"
    assert hw.end - hw.start == timedelta(minutes=30) and hw.reminders_minutes == [1440, 120]
    assert "Canvas: https://canvas/hw4" in hw.description and "Read ch. 5" in hw.description
    ex = to_spec(items["event-9"])
    assert ex.title == "[CSE 310] Midterm 2" and "AVL trees" in ex.description
    assert ex.end - ex.start == timedelta(minutes=90)


def existing_from(desired: dict) -> list[CalendarEvent]:
    return [CalendarEvent(id=f"ev-{k}", title=s.title, start=s.start, end=s.end,
                          description=s.description, calendar="nova", canvas_item_id=k)
            for k, s in desired.items()]


def test_plan_create_then_nothing_to_do():
    desired = desired_events(canvas_items(NOW), NOW)
    first = plan(desired, [], NOW)
    assert {c.action for c, _ in first} == {"create"} and len(first) == 3
    again = plan(desired, existing_from(desired), NOW)
    assert {c.action for c, _ in again} == {"keep"}


def test_plan_update_when_due_date_moves_and_delete_when_submitted():
    desired = desired_events(canvas_items(NOW), NOW)
    existing = existing_from(desired)
    moved = {k: v.model_copy() for k, v in desired.items()}
    moved["assignment-1"] = desired["assignment-1"].model_copy(
        update={"start": desired["assignment-1"].start + timedelta(days=1),
                "end": desired["assignment-1"].end + timedelta(days=1)})
    del moved["quiz-2"]  # student submitted the quiz
    result = {c.canvas_item_id: (c.action, eid) for c, eid in plan(moved, existing, NOW)}
    assert result["assignment-1"] == ("update", "ev-assignment-1")
    assert result["quiz-2"] == ("delete", "ev-quiz-2")
    assert result["event-9"][0] == "keep"


def test_plan_leaves_past_events_alone():
    past = CalendarEvent(id="old", title="old", start=NOW - timedelta(days=3),
                         end=NOW - timedelta(days=3) + timedelta(minutes=30),
                         calendar="nova", canvas_item_id="assignment-old")
    assert plan({}, [past], NOW) == []


# ---------- free time ----------

def test_free_gaps_between_busy_blocks():
    day = datetime(2026, 11, 16, 0, 0, tzinfo=PHX)
    busy = [Block(start=day.replace(hour=10), end=day.replace(hour=11)),
            Block(start=day.replace(hour=10, minute=30), end=day.replace(hour=12)),  # overlaps
            Block(start=day.replace(hour=20), end=day.replace(hour=21, minute=45))]
    free = compute_free(busy, day, day.replace(hour=23, minute=59), PHX)
    spans = [(b.start.hour, b.end.hour) for b in free]
    assert spans == [(8, 10), (12, 20)]  # 21:45-22:00 is shorter than 30 minutes


def test_free_time_never_starts_in_the_past():
    start = datetime(2026, 11, 16, 15, 0, tzinfo=PHX)
    free = compute_free([], start, start.replace(hour=23, minute=59), PHX)
    assert free[0].start == start and free[0].end.hour == 22


# ---------- documents ----------

def test_document_roundtrip(tmp_path):
    store = DocumentStore(tmp_path, "https://nova.example/")
    r = store.save("Cover Letter: Northwind", "# Dear Dana\n\nI am **excited**.\n- one\n- two",
                   "docx")
    assert r.download_url == f"https://nova.example/files/{r.id}"
    assert r.filename == "Cover-Letter-Northwind.docx" and r.size_bytes > 1000
    path, meta = store.get(r.id)
    assert path.exists() and meta.title == "Cover Letter: Northwind"
    with pytest.raises(DocumentNotFound):
        store.get("../../etc/passwd")
    with pytest.raises(ValueError):
        store.save("x", "  ", "docx")


# ---------- Gmail parsing ----------

def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def test_html_to_text():
    out = html_to_text("<style>x{}</style><p>Hello&nbsp;<b>world</b></p><p>Bye</p>")
    assert "Hello" in out and "world" in out and "Bye" in out and "x{}" not in out


def test_parse_gmail_message_with_attachment():
    msg = {"id": "g1", "threadId": "t1", "snippet": "Hi &amp; welcome", "internalDate": "1790000000000",
           "labelIds": ["INBOX", "UNREAD"],
           "payload": {"mimeType": "multipart/mixed",
                       "headers": [{"name": "From", "value": "Dana W <dana@x.com>"},
                                   {"name": "Subject", "value": "Hi"},
                                   {"name": "Message-ID", "value": "<abc@x.com>"}],
                       "parts": [
                           {"mimeType": "text/plain", "body": {"data": b64("Hello there")}},
                           {"mimeType": "application/pdf", "filename": "cv.pdf",
                            "body": {"attachmentId": "a1", "size": 1234}}]}}
    e = to_raw_email(msg, with_body=True)
    assert e.from_email == "dana@x.com" and e.from_name == "Dana W" and e.unread
    assert e.snippet == "Hi & welcome" and e.body_text == "Hello there"
    assert e.attachments[0].filename == "cv.pdf" and e.has_attachments
    assert e.message_id_header == "<abc@x.com>"
    plain, _, atts = walk_parts(msg["payload"])
    assert plain == "Hello there" and len(atts) == 1
