"""Gemini helper: model fallback and retry on temporary overload."""

import asyncio

import httpx
import pytest

from app import llm


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, str(body)

    def json(self):
        return self._body


OK = {"candidates": [{"content": {"parts": [{"text": "[1, 2]"}]}}]}


def run(models, retries, codes, monkeypatch):
    calls = []

    async def post(self, url, **kw):
        calls.append(url)
        code = codes[min(len(calls) - 1, len(codes) - 1)]
        return Resp(code, OK if code == 200 else {})

    async def no_sleep(_):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(llm.asyncio, "sleep", no_sleep)
    return calls, lambda: asyncio.run(llm.gemini_json("k", models, "s", "u", {}, retries=retries))


def test_retries_after_every_model_is_overloaded(monkeypatch):
    calls, go = run(["m1", "m2"], retries=2, codes=[503, 503, 200], monkeypatch=monkeypatch)
    assert go() == [1, 2] and len(calls) == 3        # m1 503, m2 503, then the retry round works


def test_no_retry_by_default_and_gives_a_clear_error(monkeypatch):
    calls, go = run(["m1", "m2"], retries=0, codes=[503], monkeypatch=monkeypatch)
    with pytest.raises(RuntimeError, match="All Gemini models failed"):
        go()
    assert len(calls) == 2


def test_a_real_error_is_not_retried(monkeypatch):
    calls, go = run(["m1"], retries=2, codes=[400], monkeypatch=monkeypatch)
    with pytest.raises(RuntimeError):
        go()
    assert len(calls) == 1
