"""Voice helpers: short names, spoken times, one-line speaks, email gist fallback."""

from datetime import datetime, timedelta

import pytest

from app.gist import rule_gist
from app.models import Block, Category, EmailSummary, RawEmail
from app.voice import (
    PHX,
    ago,
    cut,
    short_event_title,
    short_sender,
    short_subject,
    speak_free,
    speak_inbox,
    speak_new,
    speak_search,
    speak_sync,
    when_label,
    window_label,
)

NOW = datetime(2026, 11, 15, 10, 0, tzinfo=PHX)  # Sunday 10:00 AM


def email(**kw) -> EmailSummary:
    base = dict(id="m", from_name="Dana W", from_email="d@x.com", subject="Hello",
                snippet="", date=NOW, unread=True, category=Category.personal, important=False,
                needs_reply=False)
    base.update(kw)
    return EmailSummary(**base)


@pytest.mark.parametrize("name,addr,expected", [
    ("Amogh Ranavade via Ed Discussion", "no-reply@edstem.org", "Amogh Ranavade"),
    ('"Patient Online Services"', "x@mayo.edu", "Patient Online Services"),
    ("", "dana.whitfield@northwind.com", "Dana Whitfield"),
    ("Amex Careers", "careers@amex.com", "Amex Careers"),
    ("A Very Long Sender Name Indeed", "a@b.com", "A Very Long"),
])
def test_short_sender(name, addr, expected):
    assert short_sender(name, addr) == expected


def test_short_subject_and_cut():
    assert short_subject("Re: Fwd: Interim Demo Recording Duration") == "Interim Demo Recording Duration"
    assert short_subject("Interim Demo Recording Duration for the Fall B26 Term Project Final") \
        == "Interim Demo Recording Duration for the Fall B26 Term"
    assert cut("short", 50) == "short"
    assert not cut("one two three four five six", 12).endswith(" ")
    assert len(cut("x" * 100, 20)) <= 20


def test_event_titles_lose_the_noise():
    assert short_event_title("[BMI/BME/CEN/CSE507-494] Demo 3: 2D+3D and EHR (due)") \
        == "CSE 507 Demo 3 due"
    assert short_event_title("[CSE 540] Graded Quiz: Module 5  - Requires Respondus (due)") \
        == "CSE 540 Module 5 quiz due"
    assert short_event_title("[CSE 310] Midterm 2") == "CSE 310 Midterm 2"
    assert short_event_title("Gym") == "Gym"


def test_times_read_like_a_person():
    at = lambda days, h, m=0: (NOW + timedelta(days=days)).replace(hour=h, minute=m)
    assert when_label(at(0, 15), NOW) == "today 3 PM"
    assert when_label(at(1, 9, 30), NOW) == "tomorrow 9:30 AM"
    assert when_label(at(3, 23, 59), NOW) == "Wednesday 11:59 PM"
    assert when_label(at(9, 15), NOW) == "Nov 24 3 PM"
    assert when_label(at(1, 0), NOW, all_day=True) == "tomorrow"
    assert window_label(at(0, 14), at(0, 17), NOW) == "today 2 to 5 PM"
    assert window_label(at(1, 9), at(1, 12), NOW) == "tomorrow 9 AM to 12 PM"
    assert ago(NOW - timedelta(minutes=5), NOW) == "5 minutes ago"
    assert ago(NOW - timedelta(hours=1), NOW) == "1 hour ago"
    assert ago(NOW - timedelta(days=1, hours=2), NOW) == "yesterday"


def test_inbox_speak():
    emails = [email(subject="Interim Demo Recording Duration", from_name="Amogh Ranavade",
                    important=True, needs_reply=True),
              email(id="b", important=True), email(id="c")]
    s = speak_inbox(emails, 72)
    assert s == ("2 important out of 3. Top: Amogh Ranavade, Interim Demo Recording Duration. "
                 "1 email needs a reply.")
    assert speak_inbox([], 24) == "No mail in the last 24 hours."
    assert speak_inbox([email()], 72).startswith("1 emails, none important")


def test_new_and_search_speak():
    assert speak_new([]) == "No new mail."
    assert speak_new([email(important=True, from_name="Dana")]).startswith(
        "1 new email, 1 important: Dana, Hello")
    assert speak_new([email(), email(id="b")]) == "2 new emails."
    assert speak_search([]) == "I found nothing for that search."
    assert speak_search([email(from_name="Dana")]) == "Found 1 email. First: Dana, Hello."


def test_free_and_sync_speak():
    at = lambda h: NOW.replace(hour=h)
    assert speak_free([Block(start=at(14), end=at(17)), Block(start=at(19), end=at(22))], NOW) \
        == "You're free today 2 to 5 PM and today 7 to 10 PM."
    assert speak_free([], NOW).startswith("You have no free gaps")
    assert speak_sync({"create": 0, "update": 0, "delete": 0, "keep": 3}, [], False) \
        == "Your Nova calendar is already up to date."
    assert speak_sync({"create": 7, "update": 1, "delete": 0}, [], True) \
        == "Done. Added 7 and updated 1 on your Nova calendar."


def test_rule_gist_is_short_and_skips_quotes_and_links():
    e = RawEmail(id="1", subject="Review session", date=NOW, from_email="p@asu.edu",
                 body_text=("Review session is Monday at 6pm in BYENG 210. Bring questions. "
                            "See https://example.com/very/long/link for the slides. "
                            "Also parking is limited. Another long sentence that goes on.\n"
                            "> quoted reply that must not be included"))
    g = rule_gist(e)
    assert g.startswith("Review session is Monday at 6pm") and "http" not in g
    assert "quoted" not in g and len(g) <= 180


# ---------- demo label ----------

def test_demo_data_is_labeled_out_loud_and_live_data_is_not():
    import asyncio

    from app.voice import demo_label

    @demo_label
    async def tool(ds):
        return {"speak": "5 things due.", "data_source": ds}

    assert asyncio.run(tool("demo"))["speak"] == "Demo data. 5 things due."
    assert asyncio.run(tool("live"))["speak"] == "5 things due."
