"""Data shapes. Single source of truth for the JSON this service returns.

RawItem  = what a backend fetched from Canvas, NOT yet classified.
Item     = what the orchestrator receives (after classify.py).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SourceKind(str, Enum):
    """Which kind of Canvas object the raw item came from."""

    assignment_list = "assignment_list"
    quiz_list = "quiz_list"
    discussion = "discussion"
    announcement = "announcement"
    calendar_event = "calendar_event"
    other = "other"


class ItemType(str, Enum):
    assignment = "assignment"
    quiz = "quiz"
    exam = "exam"
    discussion = "discussion"
    event = "event"
    unknown = "unknown"


class SuggestedAction(str, Enum):
    summarize_steps = "summarize_steps"
    schedule_block = "schedule_block"
    exam_prep = "exam_prep"
    none = "none"


class ClassifiedBy(str, Enum):
    rule = "rule"
    keyword = "keyword"
    llm = "llm"
    none = "none"


class DataSource(str, Enum):
    live = "live"
    demo = "demo"


class Course(BaseModel):
    id: str
    code: str
    name: str
    term: str = ""


class RawItem(BaseModel):
    id: str
    course_id: str
    source_kind: SourceKind
    title: str
    url: str
    due_at: datetime | None = None
    points: float | None = None
    body_text: str = ""
    submission_types: list[str] = Field(default_factory=list)
    # Submission status straight from Canvas (None = not a submittable thing, e.g. an event).
    submitted: bool | None = None
    graded: bool | None = None
    excused: bool | None = None
    missing: bool | None = None
    marked_complete: bool | None = None  # student ticked it off in the Canvas planner
    requires_lockdown: bool | None = None
    # Backend-internal: Canvas assignment id used to fetch details.
    canvas_assignment_id: str | None = None
    # Filled by backends that already know them (mock data, detail pages).
    steps: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class Item(BaseModel):
    id: str
    course_id: str
    course_code: str
    type: ItemType
    title: str
    due_at: datetime | None = None
    points: float | None = None
    source_url: str
    submitted: bool | None = None
    in_todo: bool
    todo_reason: str
    what_to_do: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    suggested_action: SuggestedAction
    classified_by: ClassifiedBy
    confidence: float | None = None
    reason: str = ""
    data_source: DataSource


class Material(BaseModel):
    id: str
    course_id: str
    title: str
    type: str  # pdf | page | slides | other
    url: str
    local_path: str | None = None
    extracted_text: str | None = None


class Snapshot(BaseModel):
    synced_at: datetime
    backend: str
    data_source: DataSource
    llm_used: bool = False
    llm_error: str | None = None
    courses: list[Course]
    items: list[Item]
    materials: list[Material]


class SyncResult(BaseModel):
    synced_at: datetime
    backend: str
    data_source: DataSource
    llm_used: bool
    llm_error: str | None = None
    counts: dict[str, int]


class Health(BaseModel):
    ok: bool
    backend: str
    llm: str
    last_sync: datetime | None
    last_error: str | None = None
