"""Screenshot witness capture for the credential agent.

Uses the TinyFish Playwright CDP session that backends/tinyfish.py already
owns. Two shapes supported:
  - path=/some/canvas/path     → prepends canvas_base_url
  - url=https://my.asu.edu/... → uses as-is (MyASU + external)

If `selector` is provided, we `element.screenshot()` only that DOM node
(exactly what we want for MyASU grades: #schedule-grade-details).
Otherwise `page.screenshot(full_page=True)`.

Response is {png_b64, target_url, selector, bytes} — the cred-agent's
browser_client.py already decodes png_b64.
"""
from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .config import Settings, get_settings

log = logging.getLogger(__name__)
router = APIRouter()


class ScreenshotIn(BaseModel):
    # Exactly one of path / url.
    path: str | None = None
    url: str | None = None
    # If set, crop to this DOM selector (e.g. "#schedule-grade-details").
    selector: str | None = None
    full_page: bool = True
    timeout_ms: int = 20_000


class ScreenshotOut(BaseModel):
    png_b64: str
    target_url: str
    selector: str | None = None
    bytes: int


async def _take(req_body: ScreenshotIn, settings: Settings,
                request: Request) -> ScreenshotOut:
    svc = request.app.state.service
    if (req_body.path is None) == (req_body.url is None):
        raise HTTPException(400, "pass exactly one of `path` or `url`")

    target = req_body.url or (settings.canvas_base_url.rstrip("/") + req_body.path)
    # Open browser on-demand so screenshots don't require a prior /sync.
    opened_here = False
    if getattr(svc.backend, "_ctx", None) is None:
        try:
            await svc.backend.open_session()
            opened_here = True
        except Exception as e:
            raise HTTPException(503, f"could not open browser: {e}")
    ctx = getattr(svc.backend, "_ctx", None)
    if ctx is None:
        raise HTTPException(503, "open_session didn't leave a context")
    try:
        page = await ctx.new_page()
        try:
            await page.goto(target, wait_until="networkidle",
                              timeout=req_body.timeout_ms)
            if req_body.selector:
                handle = await page.wait_for_selector(
                    req_body.selector, timeout=req_body.timeout_ms, state="attached"
                )
                if handle is None:
                    raise HTTPException(
                        404, f"selector not found: {req_body.selector!r} on {target}"
                    )
                await handle.scroll_into_view_if_needed()
                png = await handle.screenshot(type="png")
            else:
                png = await page.screenshot(full_page=req_body.full_page, type="png")
        except HTTPException:
            raise
        except Exception as e:
            log.warning("screenshot %s failed: %s", target, e)
            raise HTTPException(502, f"navigate/screenshot failed: {e}")
        finally:
            await page.close()
    finally:
        if opened_here:
            try:
                await svc.backend.close_session()
            except Exception:
                pass
    return ScreenshotOut(
        png_b64=base64.b64encode(png).decode(),
        target_url=target,
        selector=req_body.selector,
        bytes=len(png),
    )


@router.post("/screenshot", response_model=ScreenshotOut)
async def screenshot(body: ScreenshotIn,
                     request: Request,
                     settings: Settings = Depends(get_settings)):
    return await _take(body, settings, request)
