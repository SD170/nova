import json
import tempfile
from pathlib import Path

import pytest

from app.backends.mock import MockBackend
from app.cache import SnapshotCache
from app.classify import LLMResult
from app.config import Settings
from app.llm import item_payload, parse_results
from app.models import ItemType, RawItem
from app.service import BrowserAgentService


def test_parse_results_and_skip_bad_rows():
    text = json.dumps([
        {"id": "a", "type": "exam", "include_in_todo": True, "reason": "midterm",
         "confidence": 0.9, "topics": ["heaps"], "what_to_do": [str(i) for i in range(9)]},
        {"id": "b", "type": "not-a-type", "include_in_todo": True, "reason": "x", "confidence": 1},
    ])
    out = parse_results(text)
    assert set(out) == {"a"}
    assert out["a"].type == ItemType.exam and len(out["a"].what_to_do) == 5


def test_payload_trims_instructions():
    raw = RawItem(id="i", course_id="c", source_kind="assignment_list", title="T",
                  url="https://x", body_text="y" * 10_000, submitted=False)
    p = item_payload(raw, "CSE 579")
    assert p["course"] == "CSE 579" and p["submitted"] is False and len(p["instructions"]) == 2500


class FakeLLM:
    def __init__(self, fail=False):
        self.fail, self.seen = fail, []

    async def classify_batch(self, items):
        if self.fail:
            raise RuntimeError("Gemini HTTP 503")
        self.seen = [r.id for r, _ in items]
        return {"cse310-n1": LLMResult(type=ItemType.event, confidence=0.95,
                                       reason="Office hours change, no work", include_in_todo=False)}


def run_sync(llm):
    import asyncio
    with tempfile.TemporaryDirectory() as tmp:
        s = Settings(_env_file=None, data_dir=Path(tmp))
        svc = BrowserAgentService(s, MockBackend(), SnapshotCache(s.snapshot_path, 30), llm)
        return asyncio.run(svc.sync())


def test_sync_uses_one_batched_llm_call_for_open_items_only():
    llm = FakeLLM()
    snap = run_sync(llm)
    assert snap.llm_used and snap.llm_error is None
    submitted = {i.id for i in snap.items if i.submitted}
    assert submitted == {"cse310-a2", "mat343-c7"}
    assert set(llm.seen) == {i.id for i in snap.items} - submitted  # ONE call, done work skipped
    ann = next(i for i in snap.items if i.id == "cse310-n1")
    assert ann.type == ItemType.event and ann.classified_by.value == "llm"


def test_gemini_falls_back_to_next_model(monkeypatch):
    import asyncio
    from app.llm import GeminiClassifier

    calls = []

    async def fake_call(self, model, items):
        calls.append(model)
        if model == "slow-model":
            raise RuntimeError("Gemini HTTP 503: high demand")
        return {"x": LLMResult(type=ItemType.quiz, confidence=1, reason="ok")}

    monkeypatch.setattr(GeminiClassifier, "_call", fake_call)
    g = GeminiClassifier("k", ["slow-model", "fast-model"])
    raw = RawItem(id="x", course_id="c", source_kind="quiz_list", title="Q", url="https://x")
    out = asyncio.run(g.classify_batch([(raw, "C")]))
    assert calls == ["slow-model", "fast-model"] and g.last_model == "fast-model" and "x" in out


def test_llm_failure_falls_back_to_rules():
    snap = run_sync(FakeLLM(fail=True))
    assert not snap.llm_used and "503" in snap.llm_error
    assert any(i.in_todo for i in snap.items)  # rules still produced a to-do list
