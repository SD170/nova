"""Supermemory: the student's long-term memory (weak topics, preferences, goals).

Namespace = one student. The brain reads/writes through the memory_* MCP tools; this service
also saves one deterministic fact on its own: the result of every finished quiz, and reads
the weak topics back before the next quiz ("skips strong, hits weak").

API (https://supermemory.ai/docs): Bearer key, per-namespace routes:
  POST   /ns/{ns}/document            add (content, id?, metadata?, dreaming: "instant")
  POST   /ns/{ns}/search              {query, limit} -> results[{chunk|memory, metadata, similarity}]
  POST   /ns/{ns}/profile             -> profile{static[], dynamic[]}
  POST   /ns/{ns}/list/documents      recent documents
  DELETE /ns/{ns}/memories/semantic   {query}  forget by meaning
"""

import hashlib
import logging
import re
from collections import Counter
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, Field

from .models import MemoryUnavailable
from .quiz_models import Quiz
from .voice import cut, join_words

log = logging.getLogger(__name__)


class MemoryHit(BaseModel):
    text: str
    kind: str = ""
    similarity: float | None = None
    created_at: str = ""
    metadata: dict = Field(default_factory=dict)


def _text(item) -> str:
    """Profile items and search hits are strings or objects with memory/chunk/content."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("memory") or item.get("chunk") or item.get("content")
                   or item.get("text") or "")
    return ""


class MemoryClient:
    def __init__(self, api_key: str, namespace: str, base_url: str = "https://api.supermemory.ai",
                 timeout: float = 25):
        self.api_key = api_key
        self.namespace = namespace
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self.enabled:
            raise MemoryUnavailable("Memory isn't set up yet (SUPERMEMORY_API_KEY is empty).")
        url = f"{self.base}/ns/{self.namespace}{path}"
        # Telemetry: human labels per endpoint so the UI chip tells reads
        # from writes at a glance.
        from .events import track
        endpoint = path.lstrip("/").split("?", 1)[0].split("/", 1)[0] or "api"
        _tool_labels = {
            "search":   "Recall from Supermemory",
            "document": "Save fact to Supermemory",
            "profile":  "Load student profile",
            "list":     "List recent memories",
            "memories": "Forget memory (semantic delete)",
        }
        tool = _tool_labels.get(endpoint, f"Supermemory /{endpoint}")
        try:
            with track("supermemory", tool):
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(method, url, json=body if body is not None else {},
                                                headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as exc:
            raise MemoryUnavailable(f"Could not reach supermemory ({exc}).") from exc
        if resp.status_code == 401:
            raise MemoryUnavailable("Supermemory rejected the key (SUPERMEMORY_API_KEY).")
        if resp.status_code >= 400:
            raise MemoryUnavailable(f"Supermemory HTTP {resp.status_code}: {resp.text[:120]}")
        try:
            return resp.json()
        except ValueError:
            return {}

    # ---------------- write ----------------

    async def remember(self, content: str, doc_id: str | None = None, kind: str = "fact",
                       metadata: dict | None = None) -> str:
        """Fire-and-forget write. Returns the doc_id immediately — supermemory's
        'dreaming:instant' acknowledges within a few hundred ms but the
        semantic index needs ~1-2s to be queryable. The caller never needs
        to block on either; we schedule the HTTP POST on the event loop and
        return.

        If supermemory is unreachable or returns an error, we log it (via
        the events emitter so it shows up in the UI chip) but do NOT raise —
        the quiz pipeline should keep running even if memory is degraded.
        """
        doc_id = doc_id or f"{kind}_{hashlib.sha1(content.encode()).hexdigest()[:12]}"
        meta = {"kind": kind, "saved_at": datetime.now(timezone.utc).isoformat(), **(metadata or {})}
        body = {"content": content, "id": doc_id, "metadata": meta, "dreaming": "instant"}

        async def _fire() -> None:
            try:
                await self._req("POST", "/document", body)
            except MemoryUnavailable as exc:
                log.warning("supermemory remember failed (fire-and-forget): %s", exc)

        # asyncio.create_task returns a Task that runs concurrently without
        # blocking the caller. The caller gets the doc_id back right away.
        import asyncio
        asyncio.create_task(_fire())
        return doc_id

    async def forget(self, query: str) -> None:
        """Fire-and-forget semantic delete. Same non-blocking contract as
        remember() — caller never awaits the supermemory round-trip."""
        async def _fire() -> None:
            try:
                await self._req("DELETE", "/memories/semantic", {"query": query})
            except MemoryUnavailable as exc:
                log.warning("supermemory forget failed (fire-and-forget): %s", exc)
        import asyncio
        asyncio.create_task(_fire())

    # ---------------- read ----------------

    async def recall(self, query: str, limit: int = 5) -> list[MemoryHit]:
        data = await self._req("POST", "/search", {"query": query, "limit": max(1, min(limit, 10))})
        hits = []
        for r in data.get("results", []):
            text = _text(r)
            if not text:
                continue
            meta = r.get("metadata") or {}
            hits.append(MemoryHit(text=text, kind=str(meta.get("kind", "")),
                                  similarity=r.get("similarity"),
                                  created_at=str((r.get("system") or {}).get("createdAt", "")),
                                  metadata=meta))
        return hits

    async def profile(self) -> dict[str, list[str]]:
        p = (await self._req("POST", "/profile", {})).get("profile", {})
        return {"static": [t for t in map(_text, p.get("static", [])) if t],
                "dynamic": [t for t in map(_text, p.get("dynamic", [])) if t]}

    async def recent(self, limit: int = 10) -> list[dict]:
        data = await self._req("POST", f"/list/documents?limit={max(1, min(limit, 30))}", {})
        docs = data.get("documents") or data.get("results") or []
        return [{"id": d.get("id"), "text": cut(_text(d) or str(d.get("summary") or d.get("title") or ""), 220),
                 "kind": (d.get("metadata") or {}).get("kind", ""),
                 "created_at": str(d.get("createdAt") or (d.get("system") or {}).get("createdAt") or "")}
                for d in docs]

    async def weak_topics(self, course_code: str, limit: int = 3) -> list[str]:
        """Topics the student got wrong in earlier quizzes for this course, most often first."""
        hits = await self.recall(f"{course_code} quiz result weak topics", limit=10)
        counts: Counter = Counter()
        for h in hits:
            if h.kind != "quiz_result" or h.metadata.get("course") != course_code:
                continue
            for t in str(h.metadata.get("weak", "")).split("|"):
                if t.strip():
                    counts[t.strip()] += 1
            for t in str(h.metadata.get("strong", "")).split("|"):
                if t.strip():
                    counts[t.strip()] -= 1   # got it right recently: lower priority
        return [t for t, n in counts.most_common() if n > 0][:limit]


def quiz_result_text(quiz: Quiz) -> tuple[str, dict]:
    """The one fact we save when a quiz ends: readable text + metadata the loop can read back."""
    weak, strong = [], []
    for i, qu in enumerate(quiz.questions):
        bucket = strong if quiz.answers.get(i) == qu.answer else weak
        if qu.topic and qu.topic not in bucket:
            bucket.append(qu.topic)
    strong = [t for t in strong if t not in weak]
    total = len(quiz.questions)
    text = (f"Practice quiz {quiz.title}: {quiz.score} of {total} on "
            f"{datetime.now(timezone.utc):%B %d, %Y}. "
            + (f"Weak on {join_words(weak)}. " if weak else "No weak topics. ")
            + (f"Strong on {join_words(strong)}." if strong else ""))
    meta = {"course": quiz.course_code, "score": quiz.score, "total": total,
            "weak": "|".join(weak), "strong": "|".join(strong), "quiz_id": quiz.id}
    return text.strip(), meta


def speak_hits(hits: list[MemoryHit]) -> str:
    if not hits:
        return "I don't remember anything about that yet."
    lines = [cut(re.sub(r"\s+", " ", h.text), 110) for h in hits[:2]]
    return "I remember: " + " ".join(l if l.endswith(".") else l + "." for l in lines)
