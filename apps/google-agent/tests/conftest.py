"""Shared test helpers. Tests never call real Google, Gemini, TinyFish or the Canvas service."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.canvas_sync import CanvasClient
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
