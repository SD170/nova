"""Thin emitter that POSTs sponsor-track API activity to the bridge's /events_push.

Copy-pasted from apps/cred-agent/app/events.py — kept in each service so
there's no cross-package dependency. Dependency-free (stdlib only).

Usage in google-agent / browser-agent:

    from .events import track

    with track("gemini", "generateContent", note=self.model):
        resp = await httpx.AsyncClient().post(GEMINI_URL, json=...)

    with track("supermemory", "semantic search", note=query[:40]):
        hits = await self.client.post(f"/ns/{ns}/search", ...)

The emitter spawns a daemon thread per POST so telemetry never blocks
the real call. Errors (including bridge down) are swallowed.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request


_BRIDGE = os.environ.get("BRIDGE_URL") or "http://127.0.0.1:8000"


def _post(payload: dict[str, object]) -> None:
    try:
        req = urllib.request.Request(
            f"{_BRIDGE}/events_push",
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json",
                     "user-agent": "svc-events/0.1"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2.0).read()
    except Exception:  # noqa: BLE001
        pass


def emit(provider: str, tool: str, status: str = "ok",
         ms: int | None = None, note: str | None = None) -> None:
    payload: dict[str, object] = {
        "provider": provider, "tool": tool, "status": status,
    }
    if ms is not None:
        payload["ms"] = ms
    if note:
        payload["note"] = note[:120]
    threading.Thread(target=_post, args=(payload,), daemon=True).start()


class track:
    """Context manager: emit 'start' on enter, 'ok'/'error' + ms on exit.

    Supports both sync and async bodies — the only requirement is that
    the block runs inside this `with` scope. For async code, use:

        with track("gemini", "generateContent"):
            await client.post(...)
    """
    def __init__(self, provider: str, tool: str, note: str | None = None):
        self.provider = provider
        self.tool = tool
        self.note = note
        self._t0 = 0.0

    def __enter__(self) -> "track":
        self._t0 = time.time()
        emit(self.provider, self.tool, status="start", note=self.note)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        ms = int((time.time() - self._t0) * 1000)
        if exc is None:
            emit(self.provider, self.tool, status="ok", ms=ms, note=self.note)
        else:
            emit(self.provider, self.tool, status="error", ms=ms,
                 note=f"{type(exc).__name__}: {exc}"[:120])
