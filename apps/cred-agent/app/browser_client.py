"""Client for Abishek's browser-agent — Canvas-page screenshot witness.

Design: this module is DEFENSIVE. Abishek's browser-agent does not yet expose a
screenshot endpoint (his `apps/browser-agent/app/main.py` has /brief, /items,
/materials, /linkedin/* but no /screenshot). We assume the route he'll add
has one of two sane shapes:

  shape A — raw PNG stream:
      POST ${PUBLIC_CANVAS_BASE}/screenshot
      JSON body: {"path": "/grades", "full_page": true}
      Response: Content-Type: image/png, body = PNG bytes

  shape B — JSON wrapper (Playwright returns base64 natively):
      POST ${PUBLIC_CANVAS_BASE}/screenshot
      JSON body: {"path": "/grades", "full_page": true}
      Response: {"url": "/<page>", "png_b64": "<base64>"}

We accept either and return raw PNG bytes. If the route isn't live yet,
callers see a clear ScreenshotUnavailable with a hint — the mint path
catches that and continues without a witness instead of 500'ing.

Future: once his route lands, keep this file; probably just narrow it to one
shape and drop the alternate.
"""
from __future__ import annotations

import base64
import os
from typing import Optional

import httpx


class ScreenshotUnavailable(RuntimeError):
    """Signaled when the browser-agent is unreachable or hasn't shipped the
    screenshot endpoint yet. Callers should log + continue witnessless."""


def _base_url() -> str:
    base = (os.environ.get("PUBLIC_CANVAS_BASE") or "").rstrip("/")
    if not base:
        raise ScreenshotUnavailable("PUBLIC_CANVAS_BASE not set")
    return base


def _headers() -> dict[str, str]:
    key = (os.environ.get("CANVAS_API_KEY") or "").strip()
    return {"X-Canvas-Key": key} if key else {}


def _decode_body(resp: httpx.Response) -> bytes:
    ct = (resp.headers.get("content-type") or "").lower()
    if "image/png" in ct or "application/octet-stream" in ct:
        return resp.content
    # Shape B: JSON wrapper
    try:
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        raise ScreenshotUnavailable(
            f"browser-agent returned unexpected content-type {ct!r}: {e}"
        )
    b64 = data.get("png_b64") or data.get("base64") or data.get("data")
    if not b64:
        raise ScreenshotUnavailable(
            f"browser-agent JSON missing png_b64/base64/data: keys={list(data)}"
        )
    try:
        return base64.b64decode(b64)
    except Exception as e:  # noqa: BLE001
        raise ScreenshotUnavailable(f"base64 decode failed: {e}")


def capture(path: str = "/", full_page: bool = True,
            timeout: float = 20.0) -> bytes:
    """Request a screenshot of `path` from the browser-agent.

    `path` is the in-Canvas path (e.g. '/grades', '/courses/1234/grades').
    `full_page=True` gives Playwright's full-page capture.

    Returns PNG bytes. Raises ScreenshotUnavailable on any failure mode; the
    caller decides whether to fail the mint or continue witnessless.
    """
    url = f"{_base_url()}/screenshot"
    try:
        resp = httpx.post(
            url,
            json={"path": path, "full_page": full_page},
            headers=_headers(),
            timeout=timeout,
        )
    except httpx.RequestError as e:
        raise ScreenshotUnavailable(f"browser-agent unreachable at {url}: {e}")

    if resp.status_code == 404:
        raise ScreenshotUnavailable(
            f"{url} returned 404 — Abishek hasn't shipped the screenshot "
            "route yet. Add FastAPI POST /screenshot in apps/browser-agent/app/main.py."
        )
    if resp.status_code >= 400:
        raise ScreenshotUnavailable(
            f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}"
        )
    body = _decode_body(resp)
    if len(body) < 64 or body[:8] != b"\x89PNG\r\n\x1a\n":
        raise ScreenshotUnavailable(
            f"browser-agent reply does not look like PNG (first 8 = {body[:8]!r})"
        )
    return body


def try_capture(path: str = "/") -> Optional[bytes]:
    """Non-raising wrapper: returns PNG bytes on success, None otherwise."""
    try:
        return capture(path=path)
    except ScreenshotUnavailable as e:
        print(f"[browser_client] screenshot unavailable: {e}")
        return None
