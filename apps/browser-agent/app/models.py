"""Data shapes. Single source of truth for the JSON this service returns.

RawItem  = what a backend fetched from Canvas, NOT yet classified.
Item     = what the orchestrator receives (after classify.py).
"""

from datetime import date, datetime
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
    user_done: bool = False  # student said "I did this" (POST /items/{id}/user-done)
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


class MaterialType(str, Enum):
    pdf = "pdf"            # PDF file -> text with [page N] markers
    page = "page"          # Canvas wiki page (HTML -> text)
    syllabus = "syllabus"  # the course syllabus (often lists exam dates + topics)
    file = "file"          # other file (txt -> text; pptx/docx/... listed as link only)
    link = "link"          # external URL: listed, never followed


class TextStatus(str, Enum):
    ready = "ready"              # text cached: GET /materials/{id}/text is instant
    not_fetched = "not_fetched"  # text extracted on first request (~2-10 s)
    too_large = "too_large"      # file over MATERIALS_MAX_MB (e.g. whole textbooks)
    unsupported = "unsupported"  # file type we can't read (pptx, docx, images...)
    link_only = "link_only"      # external link: url only
    locked = "locked"            # Canvas has it locked for the student
    error = "error"              # last extraction failed


class Material(BaseModel):
    """One study item from a course's Modules (plus Files tab + syllabus).
    The listing never carries the text; fetch it with GET /materials/{id}/text."""

    id: str                  # file-123 | page-<course>-<slug> | syllabus-<course> | link-<course>-<item>
    course_id: str
    course_code: str = ""
    title: str
    type: MaterialType
    url: str                 # Canvas page for the student / citation
    module: str | None = None            # "(11/11 - 11/17) Module 5: Mining"
    module_position: int | None = None   # order of the module in the course
    position: int | None = None          # order inside the module
    week_start: date | None = None       # parsed from the module name, if it has dates
    week_end: date | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    updated_at: datetime | None = None
    text_status: TextStatus = TextStatus.not_fetched
    fetch_ref: str | None = None         # internal: Canvas API path used to get the content


class MaterialText(BaseModel):
    """GET /materials/{id}/text. PDFs keep [page N] markers for citations.
    Long texts come in slices: call again with offset=next_offset."""

    material_id: str
    course_id: str
    course_code: str = ""
    title: str
    type: MaterialType
    module: str | None = None
    source_url: str
    fetched_at: datetime
    pages: int | None = None
    total_chars: int
    offset: int
    next_offset: int | None   # None = this is the end
    text: str


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
    sync_in_progress: bool = False
    last_error: str | None = None


class Brief(BaseModel):
    """GET /brief — one bundled call for 'good morning / what's due'."""

    synced_at: datetime
    last_sync_age_minutes: float
    sync_in_progress: bool
    data_source: DataSource
    items: list[Item]       # to-do only, soonest first
    courses: list[Course]   # current courses only


class ItemNotFound(Exception):
    pass


class NoSnapshot(Exception):
    """No data yet: call POST /sync first."""


class MaterialNotFound(Exception):
    pass


class MaterialTextUnavailable(Exception):
    """Material exists but has no readable text (too large, link, unsupported...)."""
