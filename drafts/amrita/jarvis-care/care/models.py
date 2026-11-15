"""Jarvis Care data contract (mirrors context/jarvis-care-build-brief.md section 5).

Field names are camelCase on the wire so the UI, the orchestrator and the
brief all read the same JSON.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal[
    "health.checkin",
    "health.visitPrep",
    "health.parseAfterVisit",
    "health.compareBill",
    "health.planAppointment",
    "health.reminder",
    "health.accessibility",
    "health.help",
]

DISCLAIMER = (
    "Jarvis Care helps organize healthcare information and questions. It does not "
    "provide medical advice or verify coverage. Confirm important details with your "
    "provider or insurer."
)


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Preferences(_Wire):
    simpleLanguage: bool = True
    speak: bool = True
    locale: str = "en-US"
    # Current UI values, so relative requests ("bigger", "slower") can be resolved.
    textScale: float = 1.0
    speechRate: float = 1.0


class TimeWindow(_Wire):
    start: str
    end: str


class PermittedContext(_Wire):
    availability: Optional[list[TimeWindow]] = None
    useDemoSchedule: bool = False


class JarvisCareRequest(_Wire):
    requestId: str = "req"
    sessionId: str = "default"
    source: Literal["voice", "text", "upload", "ui"] = "text"
    utterance: Optional[str] = None
    intent: Optional[Intent] = None
    documentIds: Optional[list[str]] = None
    preferences: Preferences = Field(default_factory=Preferences)
    permittedContext: Optional[PermittedContext] = None


class Evidence(_Wire):
    docId: str
    filename: str
    page: Optional[int] = None
    excerpt: str
    verified: bool = True  # excerpt is an exact substring of the extracted text


class Card(_Wire):
    id: str
    kind: Literal["task", "question", "billFlag", "appointmentOption", "info"]
    title: str
    description: str
    status: Optional[Literal["suggested", "needsConfirmation", "ready", "done"]] = None
    evidence: Optional[list[Evidence]] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Action(_Wire):
    id: str
    label: str
    kind: Literal[
        "saveReminder", "copyQuestions", "openCalendar", "confirmAppointment", "edit",
        # UI-local actions (no external effect, applied immediately):
        "setPreferences", "openPage", "useSample",
    ]
    requiresConfirmation: bool
    payload: Optional[dict[str, Any]] = None


class JarvisCareResponse(_Wire):
    requestId: str
    intent: str
    replyText: str
    spokenSummary: str
    cards: list[Card] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    clarification: Optional[str] = None
    disclaimer: Optional[str] = DISCLAIMER
    isMock: bool = True
    # Which engine produced this reply, so the UI never presents rules as AI:
    engine: Literal["rules"] = "rules"
