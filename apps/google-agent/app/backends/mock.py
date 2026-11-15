"""Demo backend: a fake inbox + calendar, no network, no login.

Everything is labeled data_source=demo, never presented as the student's real account.
Dates are relative to "now" so there is always something recent.
"""

import itertools
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..models import (
    Block,
    CalendarEvent,
    DataSource,
    DraftResult,
    EventSpec,
    MessageNotFound,
    RawEmail,
)
from .base import WorkspaceBackend


def _ago(hours: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _emails() -> list[RawEmail]:
    return [
        RawEmail(
            id="m-recruiter", thread_id="t-recruiter", from_name="Dana Whitfield",
            from_email="dana.whitfield@northwind-labs.com", to="you@example.com",
            subject="Software Engineer Intern, AI Platform: next steps?",
            snippet="Hi! I'm a recruiter at Northwind Labs. We loved your Student Jarvis demo "
                    "and would like to set up a 30-minute call this week. Are you available "
                    "Thursday?",
            date=_ago(2), unread=True, labels=["INBOX", "UNREAD", "IMPORTANT", "CATEGORY_PERSONAL"],
            message_id_header="<recruiter-1@northwind-labs.com>",
            body_text=("Hi!\n\nI'm Dana, a recruiter at Northwind Labs. We build an AI "
                       "platform that helps logistics teams plan routes with language models. "
                       "We loved your Student Jarvis demo at SunHacks and would like to talk "
                       "about our Software Engineer Intern role (summer 2027, Tempe/remote).\n\n"
                       "Are you available for a 30-minute call on Thursday or Friday?\n\n"
                       "Best,\nDana Whitfield\nNorthwind Labs"),
        ),
        RawEmail(
            id="m-tuition", thread_id="t-tuition", from_name="ASU Student Business Services",
            from_email="no-reply@asu.edu", to="you@example.com",
            subject="Payment due: tuition installment December 3",
            snippet="Your second tuition installment of $2,850.00 is due December 3. "
                    "Pay in My ASU to avoid a late fee.",
            date=_ago(5), unread=True, labels=["INBOX", "UNREAD", "CATEGORY_UPDATES"],
            body_text="Your second tuition installment of $2,850.00 is due December 3, 2026. "
                      "Log in to My ASU and pay under Finances to avoid a late fee.",
        ),
        RawEmail(
            id="m-prof", thread_id="t-prof", from_name="Prof. Ramirez",
            from_email="ramirez@asu.edu", to="you@example.com",
            subject="CSE 310 midterm review session",
            snippet="Review session for Midterm 2 is Monday 6pm in BYENG 210. Bring questions "
                    "on AVL trees and heaps. Can you confirm if you're coming?",
            date=_ago(9), unread=False, labels=["INBOX", "IMPORTANT", "CATEGORY_PERSONAL"],
            body_text="Review session for Midterm 2 is Monday at 6pm in BYENG 210. Bring "
                      "questions on AVL trees and heaps. Can you confirm if you're coming?",
        ),
        RawEmail(
            id="m-canvas", thread_id="t-canvas", from_name="Canvas",
            from_email="notifications@instructure.com", to="you@example.com",
            subject="New grade: Homework 2: Heaps",
            snippet="Your grade for Homework 2: Heaps has been posted: 48/50.",
            date=_ago(20), unread=False, labels=["INBOX", "CATEGORY_UPDATES"],
            body_text="Your grade for Homework 2: Heaps has been posted: 48/50.",
        ),
        RawEmail(
            id="m-news", thread_id="t-news", from_name="The Pragmatic Engineer",
            from_email="newsletter@pragmaticengineer.com", to="you@example.com",
            subject="This week: how AI teams ship faster",
            snippet="A digest of this week's engineering stories. Unsubscribe any time.",
            date=_ago(30), unread=True, labels=["INBOX", "UNREAD", "CATEGORY_UPDATES"],
            body_text="A digest of this week's engineering stories.",
        ),
        RawEmail(
            id="m-promo", thread_id="t-promo", from_name="Campus Bookstore",
            from_email="deals@campusbookstore.example", to="you@example.com",
            subject="40% off everything this weekend!",
            snippet="Hoodies, notebooks and more. Today only.",
            date=_ago(40), unread=True, labels=["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"],
            body_text="Hoodies, notebooks and more. Today only.",
        ),
    ]


class MockBackend(WorkspaceBackend):
    name = "mock"
    data_source = DataSource.demo

    def __init__(self, tz: str = "America/Phoenix"):
        self.tz = ZoneInfo(tz)
        self.emails = {e.id: e for e in _emails()}
        self.nova: dict[str, CalendarEvent] = {}
        self.drafts: list[DraftResult] = []
        self._ids = itertools.count(1)

    async def login_status(self) -> str:
        return "demo"

    async def account(self) -> str:
        return "demo@example.com (demo data)"

    # ---- Gmail ----
    async def search_messages(self, query: str, max_results: int) -> list[RawEmail]:
        after = re.search(r"after:(\d+)", query)
        unread = "is:unread" in query
        frm = re.search(r"from:(\S+)", query)
        words = [w.lower() for w in re.sub(
            r"(after|before|from|in|is|label|newer_than):\S+", " ", query).split() if len(w) > 2]
        found = []
        for e in self.emails.values():
            if after and e.date.timestamp() < int(after.group(1)):
                continue
            if unread and not e.unread:
                continue
            if frm and frm.group(1).lower() not in e.from_email.lower():
                continue
            hay = f"{e.subject} {e.snippet} {e.from_name} {e.from_email} {e.body_text}".lower()
            if words and not all(w in hay for w in words):
                continue
            found.append(e.model_copy(update={"body_text": None}))
        found.sort(key=lambda e: e.date, reverse=True)
        return found[:max_results]

    async def get_message(self, message_id: str) -> RawEmail:
        if message_id not in self.emails:
            raise MessageNotFound(message_id)
        return self.emails[message_id].model_copy()

    async def create_draft(self, to, subject, body, reply_to_message_id) -> DraftResult:
        d = DraftResult(
            draft_id=f"draft-{next(self._ids)}", thread_id="", to=to, subject=subject, body=body,
            in_reply_to=reply_to_message_id, gmail_url="https://mail.google.com/mail/u/0/#drafts",
            data_source=DataSource.demo,
            note="DEMO: saved in the demo drafts list only. Nothing was sent.")
        self.drafts.append(d)
        return d

    # ---- Calendar ----
    def _at(self, days: int, hour: int, minute: int = 0) -> datetime:
        d = datetime.now(self.tz) + timedelta(days=days)
        return d.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _primary(self) -> list[CalendarEvent]:
        spec = [("CSE 310 lecture", 1, 10, 50), ("Gym", 1, 17, 60), ("Team standup", 2, 9, 30),
                ("CSE 310 lecture", 3, 10, 50), ("Hackathon sync", 3, 14, 60)]
        return [CalendarEvent(id=f"p{i}", title=t, start=self._at(d, h),
                              end=self._at(d, h) + timedelta(minutes=m), calendar="primary")
                for i, (t, d, h, m) in enumerate(spec)]

    async def list_events(self, start, end) -> list[CalendarEvent]:
        return [e for e in self._primary() if e.end >= start and e.start <= end]

    async def free_busy(self, start, end) -> list[Block]:
        return [Block(start=e.start, end=e.end) for e in await self.list_events(start, end)]

    async def list_nova_events(self, start, end) -> list[CalendarEvent]:
        return [e for e in self.nova.values() if e.end >= start and e.start <= end]

    def _event(self, event_id: str, spec: EventSpec) -> CalendarEvent:
        return CalendarEvent(id=event_id, title=spec.title, start=spec.start, end=spec.end,
                             description=spec.description, location=spec.location,
                             calendar="nova", canvas_item_id=spec.canvas_item_id,
                             html_link=f"https://calendar.google.com/calendar/event?eid={event_id}")

    async def create_nova_event(self, spec: EventSpec) -> CalendarEvent:
        ev = self._event(f"nova-{next(self._ids)}", spec)
        self.nova[ev.id] = ev
        return ev

    async def update_nova_event(self, event_id: str, spec: EventSpec) -> CalendarEvent:
        ev = self._event(event_id, spec)
        self.nova[event_id] = ev
        return ev

    async def delete_nova_event(self, event_id: str) -> None:
        self.nova.pop(event_id, None)
