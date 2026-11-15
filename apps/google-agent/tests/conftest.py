"""Shared test helpers. Tests never call real Google, Gemini, TinyFish or the Canvas service."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.canvas_sync import CanvasClient
from app.models import NewsUnavailable
from app.news import NewsClient
from app.config import Settings
from app.main import create_app


@pytest.fixture
def make_client(tmp_path):
    """Factory: make_client(canvas_api_key="k", ...) -> TestClient on the mock backend."""
    clients = []

    def _make(**overrides) -> TestClient:
        overrides.setdefault("gemini_api_key", "")
        overrides.setdefault("tinyfish_api_key", "")
        settings = Settings(_env_file=None, data_dir=tmp_path, **overrides)
        c = TestClient(create_app(settings))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def canvas_items(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)

    def iso(days: float) -> str:
        return (now + timedelta(days=days)).isoformat()

    return [
        {"id": "assignment-1", "course_code": "CSE 540", "type": "assignment",
         "title": "Homework 4", "due_at": iso(2), "points": 50, "in_todo": True,
         "submitted": False, "user_done": False, "source_url": "https://canvas/hw4",
         "what_to_do": ["Read ch. 5", "Submit a zip"], "topics": []},
        {"id": "quiz-2", "course_code": "CSE 507", "type": "quiz", "title": "Quiz 3",
         "due_at": iso(3), "points": 10, "in_todo": True, "submitted": False,
         "user_done": False, "source_url": "https://canvas/q3"},
        {"id": "event-9", "course_code": "CSE 310", "type": "exam", "title": "Midterm 2",
         "due_at": iso(6), "in_todo": False, "submitted": None, "user_done": False,
         "source_url": "https://canvas/cal", "topics": ["AVL trees", "heaps"]},
        {"id": "assignment-3", "course_code": "CSE 579", "type": "assignment",
         "title": "Already submitted", "due_at": iso(1), "in_todo": False, "submitted": True,
         "user_done": False},
        {"id": "assignment-4", "course_code": "CSE 579", "type": "assignment",
         "title": "Marked done by me", "due_at": iso(4), "in_todo": False, "submitted": False,
         "user_done": True},
        {"id": "assignment-5", "course_code": "CSE 579", "type": "assignment",
         "title": "Already past", "due_at": iso(-2), "in_todo": True, "submitted": False,
         "user_done": False},
        {"id": "event-office", "course_code": "CSE 310", "type": "event", "title": "Office hours",
         "due_at": iso(2), "in_todo": False, "submitted": None, "user_done": False},
    ]


@pytest.fixture
def fake_canvas(monkeypatch):
    """Canvas service stand-in: returns a mutable list the test can edit."""
    state = {"items": canvas_items(), "error": None}

    async def items(self, days=30):
        if state["error"]:
            raise state["error"]
        return state["items"], {"data_source": "demo", "synced_at": "2026-11-15T08:00:00Z"}

    monkeypatch.setattr(CanvasClient, "items", items)
    return state


NEWS = {"generated_at": "2026-11-15T10:40:14Z", "data_source": "live", "items": [
    {"id": "n1", "title": "Judge temporarily blocks Trump from moving ahead on Washington public "
                          "golf course redevelopment", "url": "https://npr.org/a", "source": "NPR",
     "topic": "Top stories", "outlets": 2, "confirmed": True,
     "published_at": "2026-11-15T04:28:45Z"},
    {"id": "n2", "title": "Fed holds rates", "url": "https://bbc.com/b", "source": "BBC",
     "topic": "Top stories", "outlets": 1, "confirmed": False,
     "published_at": "2026-11-15T06:00:00Z"},
    {"id": "n3", "title": "Suns win in overtime", "url": "https://espn.com/c", "source": "ESPN",
     "topic": "Top stories", "outlets": 1, "confirmed": False,
     "published_at": "2026-11-15T07:00:00Z"}]}
EVENTS = {"data_source": "live", "items": [
    {"id": "e1", "title": "Career Fair", "starts_at": "2026-11-17T17:00:00Z",
     "when_text": "Tue, Nov 17, 10:00 AM", "location": "Memorial Union, Tempe", "host": "ASU Career",
     "cost": "FREE", "url": "https://asu/e1"},
    {"id": "e2", "title": "Robotics club meeting", "starts_at": "2026-11-18T01:00:00Z",
     "when_text": "Tue 6 PM", "location": "BYENG 210", "host": "Robotics", "cost": "FREE",
     "url": "https://asu/e2"}]}


@pytest.fixture
def fake_news(monkeypatch):
    """Amrita's news service stand-in. state['error'] makes it fail like a down service."""
    state = {"error": None, "calls": []}

    async def _get(self, path, params):
        state["calls"].append((path, params))
        if state["error"]:
            raise state["error"]
        return NEWS if path == "/news" else EVENTS

    monkeypatch.setattr(NewsClient, "_get", _get)
    return state


# ---------------- exam prep fakes ----------------

SYLLABUS = ("[page 1]\nCSE 540 Syllabus. Grading and policies.\n\n[page 5]\n"
            "Important dates\nFinal Exam  Dec 1, 2026 Dec 4, 2026\nThe final covers all modules. "
            + "Filler text about attendance and academic integrity. " * 8)
SLIDES = ("[page 1]\nA binary min-heap is a complete binary tree where each parent is less than or "
          "equal to its children.\n\n[page 2]\nInsert bubbles up and extract-min bubbles down; "
          "both operations take O(log n) time. Building a heap from n items takes O(n) time.\n\n"
          "[page 3]\nAn AVL tree rebalances itself with single or double rotations after an insert, "
          "keeping search time at O(log n). Hash tables resolve collisions by chaining or by open "
          "addressing with probing. " * 2)
TEXTS = {"syl": SYLLABUS, "f1": SLIDES}


def _q(q, opts, ans, quote, topic="heaps", page=1):
    return {"q": q, "options": opts, "answer": ans, "explanation": "From the slides.",
            "topic": topic, "source_title": "Module 5 Slides.pdf", "source_quote": quote, "page": page}


GOOD_QUESTIONS = [
    _q("In a min-heap, a parent is what vs its children?", ["Smaller or equal", "Larger", "Random", "Equal only"], 0, "each parent is less than or equal to its children"),
    _q("Time to insert into a heap?", ["O(1)", "O(log n)", "O(n)", "O(n^2)"], 1, "both operations take O(log n) time"),
    _q("Time to build a heap from n items?", ["O(n)", "O(n log n)", "O(log n)", "O(1)"], 0, "Building a heap from n items takes O(n) time"),
    _q("What rebalances an AVL tree?", ["Rotations", "Hashing", "Sorting", "Chaining"], 0, "rebalances itself with single or double rotations", "AVL trees", 3),
    _q("AVL search time is?", ["O(n)", "O(log n)", "O(1)", "O(n^2)"], 1, "keeping search time at O(log n)", "AVL trees", 3),
    _q("A way to handle hash collisions?", ["Chaining", "Rotation", "Heapify", "Bubbling"], 0, "resolve collisions by chaining or by open addressing", "hashing", 3),
]
BAD_QUESTIONS = [
    _q("Invented question?", ["a", "b", "c", "d"], 0, "this sentence is not in the course material at all"),   # dropped: no quote
    {"q": "Only three options?", "options": ["a", "b", "c"], "answer": 0, "source_title": "x",
     "source_quote": "each parent is less than or equal to its children"},                              # dropped: 3 options
]


@pytest.fixture
def fake_exam(monkeypatch):
    """Canvas materials + Gemini stand-ins for exam prep. state['quiz_rows'] / ['exam_rows'] are editable."""
    import app.exam as exam_mod

    state = {"quiz_rows": GOOD_QUESTIONS + BAD_QUESTIONS, "exam_rows": [
        {"name": "Final Exam", "date_text": "Dec 1, 2026 Dec 4, 2026", "topics": ["all modules"],
         "source_title": "CSE 540 Syllabus", "page": 5, "quote": "Final Exam Dec 1, 2026 Dec 4, 2026"},
        {"name": "Midterm", "date_text": "Oct 5", "topics": [], "source_title": "CSE 540 Syllabus",
         "quote": "the midterm is on October fifth for everyone"}],   # invented: must be dropped
        "calls": []}

    async def courses(self):
        return [{"id": "c540", "code": "CSE 540", "name": "Engineering Blockchain Applications"},
                {"id": "c507", "code": "BMI/BME/CEN/CSE507-494", "name": "Medical Imaging"}], {"data_source": "live"}

    async def materials(self, course_id, topic_hint=None, this_week=False):
        mats = [{"id": "syl", "type": "syllabus", "title": "CSE 540 Syllabus", "module": None, "text_status": "ready"},
                {"id": "f1", "type": "pdf", "title": "Module 5 Slides.pdf", "module": "Module 5", "text_status": "ready"},
                {"id": "lnk", "type": "link", "title": "A link", "module": "Module 5", "text_status": "link_only"}]
        return mats, {"data_source": "live"}

    async def material_text(self, material_id, max_chars=12_000):
        return {"text": TEXTS[material_id][:max_chars]}

    async def fake_gemini(api_key, models, system, user_text, schema, timeout=30, temperature=0, retries=0):
        state["calls"].append(system[:20])
        state["last_user_text"] = user_text
        return state["exam_rows"] if system.startswith("From the syllabus") else state["quiz_rows"]

    monkeypatch.setattr(CanvasClient, "courses", courses)
    monkeypatch.setattr(CanvasClient, "materials", materials)
    monkeypatch.setattr(CanvasClient, "material_text", material_text)
    monkeypatch.setattr(exam_mod, "gemini_json", fake_gemini)
    return state


# ---------------- supermemory fake ----------------

@pytest.fixture
def fake_memory(monkeypatch):
    """Supermemory stand-in (no network). state['docs'] holds what was saved."""
    from app.memory import MemoryClient

    state = {"docs": [], "static": ["Prefers short spoken answers"], "error": None, "calls": []}

    def words(t):
        return {w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in t).split() if len(w) > 2}

    async def _req(self, method, path, body=None):
        from app.models import MemoryUnavailable
        state["calls"].append((method, path))
        if state["error"]:
            raise MemoryUnavailable(state["error"])
        body = body or {}
        if method == "POST" and path == "/document":
            state["docs"] = [d for d in state["docs"] if d["id"] != body["id"]]
            state["docs"].append({"id": body["id"], "content": body["content"], "metadata": body.get("metadata", {})})
            return {"id": body["id"], "status": "queued"}
        if method == "POST" and path == "/search":
            q = words(body["query"])
            scored = sorted(((len(q & words(d["content"] + " " + str(d["metadata"]))), d) for d in state["docs"]),
                            key=lambda x: -x[0])
            return {"results": [{"chunk": d["content"], "metadata": d["metadata"], "similarity": 0.8,
                                 "system": {"createdAt": "2026-11-15T12:00:00Z"}}
                                for n, d in scored if n > 0][: body.get("limit", 5)]}
        if method == "POST" and path == "/profile":
            return {"profile": {"static": state["static"], "dynamic": []}}
        if method == "DELETE" and path == "/memories/semantic":
            q = words(body["query"])
            state["docs"] = [d for d in state["docs"] if not (q & words(d["content"]))]
            return {}
        if method == "POST" and path.startswith("/list/documents"):
            return {"documents": [{"id": d["id"], "summary": d["content"], "metadata": d["metadata"]}
                                  for d in state["docs"]]}
        return {}

    monkeypatch.setattr(MemoryClient, "_req", _req)
    return state
