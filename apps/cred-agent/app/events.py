"""Thin emitter that POSTs sponsor-track API activity to the bridge's /events_push.

Why a per-service emitter: Hermes is a subprocess with no back-channel, and
teammate services (google-agent, browser-agent) run on different ports. The
bridge is the fan-out point for the Electron UI's left-side activity chip.

We keep this file dependency-free (stdlib urllib only) so importing from
anywhere in cred-agent is safe — no httpx event loop concerns.
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
    """Fire-and-forget POST. Swallow all errors — activity reporting must
    never take down a real call. Timeout tight (2s) so a dead bridge
    doesn't stall the mint pipeline."""
    try:
        req = urllib.request.Request(
            f"{_BRIDGE}/events_push",
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json",
                     "user-agent": "cred-agent-events/0.1"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2.0).read()
    except Exception:  # noqa: BLE001 — telemetry must never crash the caller
        pass


def emit(provider: str, tool: str, status: str = "ok",
         ms: int | None = None, note: str | None = None) -> None:
    """Non-blocking emit. Spawns a daemon thread so the caller returns
    immediately even if the bridge is slow."""
    payload: dict[str, object] = {
        "provider": provider, "tool": tool, "status": status,
    }
    if ms is not None:
        payload["ms"] = ms
    if note:
        payload["note"] = note[:120]
    t = threading.Thread(target=_post, args=(payload,), daemon=True)
    t.start()


class track:
    """Context manager: emit 'start' on enter, 'ok'/'error' + ms on exit.

    Usage:
        with track("solana", "memo program tx"):
            tx = solana_memo.post_memo(...)

    On exception: emits status='error' with the exception's str as note.
    Keep the tool name short — it renders as a toast.
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
