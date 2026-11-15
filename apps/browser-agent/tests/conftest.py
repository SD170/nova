"""Shared test helpers. Tests never call real TinyFish, Canvas or Gemini."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def make_client(tmp_path):
    """Factory: make_client(browser_backend="tinyfish", ...) -> TestClient."""
    clients = []

    def _make(**overrides) -> TestClient:
        overrides.setdefault("gemini_api_key", "")  # never hit Gemini from tests
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
    """API client on the mock backend (labeled demo data)."""
    return make_client()
