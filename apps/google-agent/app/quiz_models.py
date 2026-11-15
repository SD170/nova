"""Exam prep data shapes: exam facts, quiz questions, quiz sessions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .models import DocumentResult


class ExamFact(BaseModel):
    name: str                      # "Final Exam"
    date_text: str                 # exactly as written: "Dec 1, 2026 - Dec 4, 2026"
    date_iso: str = ""             # first day, YYYY-MM-DD, only when the text makes it clear
    topics: list[str] = Field(default_factory=list)
    source_title: str = ""
    page: int | None = None
    quote: str = ""                # copied from the source (verified to be in it)


class ExamInfo(BaseModel):
    course_code: str
    exams: list[ExamFact]
    note: str = ""                 # e.g. "No exam dates found in the syllabus."
    sources: list[str] = Field(default_factory=list)
    data_source: str = "live"


class QuizQuestion(BaseModel):
    q: str                         # <= ~80 chars so it can be spoken in one breath
    options: list[str]             # exactly 4, each <= ~24 chars
    answer: int                    # index of the correct option (0-3)
    explanation: str = ""
    topic: str = ""
    source_title: str = ""
    source_quote: str = ""         # verified to appear in the material
    page: int | None = None


class Quiz(BaseModel):
    id: str
    course_id: str
    course_code: str
    title: str
    topics: list[str] = Field(default_factory=list)
    created_at: datetime
    questions: list[QuizQuestion]
    status: Literal["ready", "in_progress", "done"] = "ready"
    mode: Literal["voice", "panel"] | None = None
    answers: dict[int, int] = Field(default_factory=dict)   # question index -> chosen option
    score: int | None = None
    pdf: DocumentResult | None = None
    pdf_status: Literal["pending", "saved", "failed"] = "pending"
    saved_path: str | None = None
    data_source: str = "live"


class QuizView(BaseModel):
    """What the side panel sees: no answers or explanations until the quiz is done."""

    id: str
    course_code: str
    title: str
    status: str
    mode: str | None
    total: int
    answered: int
    questions: list[dict]
    score: int | None = None
    review: list[dict] | None = None   # only when done: per question correct/chosen/explanation
    pdf_status: str = "pending"
    saved_path: str | None = None
    data_source: str = "live"


class FeedEvent(BaseModel):
    id: int
    at: datetime
    kind: str                      # quiz_ready | pdf_saved | quiz_panel | quiz_score | ...
    title: str
    detail: str = ""
    data: dict = Field(default_factory=dict)
