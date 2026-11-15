"""In-memory per-session state. Nothing is written to disk.

Cleared on server restart or by DELETE /api/health/session/{id} ("Clear my data").
Health data stays here and is never shared with other Jarvis modules.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .after_visit import AfterVisitPlan
from .documents import Document


@dataclass
class Reminder:
    id: str
    title: str
    dueDate: Optional[str]
    sourceCardId: Optional[str]
    createdAt: str
    userApproved: bool = True
    note: str = "Saved in Jarvis Care for this session only. No phone or calendar notification is sent."

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class HealthNote:
    id: str
    createdAt: str
    userText: str
    sleep: Optional[str] = None
    energy: Optional[str] = None
    stress: Optional[str] = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class PlannedVisit:
    id: str
    start: str
    end: str
    label: str
    demo: bool = True
    note: str = "Demo — no real appointment booked. This is a planned time on your own schedule."

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Session:
    id: str
    docs: dict[str, Document] = field(default_factory=dict)
    after_visit_id: Optional[str] = None
    bill_id: Optional[str] = None
    eob_id: Optional[str] = None
    plan: Optional[AfterVisitPlan] = None
    notes: list[HealthNote] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    reminders: list[Reminder] = field(default_factory=list)
    visits: list[PlannedVisit] = field(default_factory=list)
    bill_questions: list[str] = field(default_factory=list)
    pending: Optional[dict[str, Any]] = None
    last_spoken: str = ""
    last_slots: list[dict] = field(default_factory=list)

    def add_reminder(self, title: str, due: Optional[str], source: Optional[str]) -> Reminder:
        r = Reminder(
            id=f"rem-{uuid.uuid4().hex[:8]}", title=title, dueDate=due,
            sourceCardId=source, createdAt=datetime.now().isoformat(timespec="seconds"),
        )
        self.reminders.append(r)
        return r

    def add_note(self, text: str, sleep=None, energy=None, stress=None) -> HealthNote:
        n = HealthNote(
            id=f"note-{uuid.uuid4().hex[:8]}", createdAt=datetime.now().isoformat(timespec="seconds"),
            userText=text.strip(), sleep=sleep, energy=energy, stress=stress,
        )
        self.notes.append(n)
        return n


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session:
        sid = (session_id or "default")[:64]
        with self._lock:
            if sid not in self._sessions:
                self._sessions[sid] = Session(id=sid)
            return self._sessions[sid]

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


STORE = SessionStore()
