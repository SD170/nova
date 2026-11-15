# MyASU login + Screenshot endpoint — patch for apps/browser-agent/

This is a **drop-in patch file** for Abishek's browser-agent that adds:

1. **`POST /screenshot`** — captures any Canvas/MyASU page as PNG, used as the
   witness image for cred-agent NFT credentials.
2. **`POST /myasu/login`** + **`GET /myasu/snapshot`** — surfaces GPA + term
   grades from `my.asu.edu` so credentials cover real transcript data,
   not just Canvas assignments.
3. Both are exposed as **MCP tools** so Nova's brain can call them via voice.

Everything reuses the existing Playwright CDP session from
`backends/tinyfish.py` (`backend._ctx`), the existing `X-Canvas-Key` auth,
and the existing settings (`get_settings()`). No new dependencies.

---

## What to add, in order

### 1. New file `apps/browser-agent/app/screenshot.py`

Fresh module. Captures PNG bytes from either a Canvas path or a MyASU URL.

```python
"""Page-screenshot witness capture for the credential agent.

Reuses the TinyFish Playwright context already open in backends.tinyfish.
Two code paths:
  - Canvas: pass a path like '/grades' or '/courses/12345/grades'; we
    navigate from the base canvas URL.
  - MyASU: pass a full https://my.asu.edu/... URL; same browser context,
    so cookies from a prior /myasu/login call persist.

The browser-agent backend lifecycle is already managed by main.py's
lifespan handler, so we grab a Page off the existing context rather than
opening a new session per screenshot (cheaper + preserves auth state).
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .config import Settings, get_settings

log = logging.getLogger(__name__)

router = APIRouter()


class ScreenshotIn(BaseModel):
    # Either `path` (Canvas-relative) OR `url` (full https://). Exactly one.
    path: str | None = None
    url: str | None = None
    full_page: bool = True
    # Timeout for page.goto(); wait for network-idle feel but bounded.
    timeout_ms: int = 15_000


class ScreenshotOut(BaseModel):
    png_b64: str  # verify.js + browser_client.py both read this key
    target_url: str
    bytes: int


@router.post("/screenshot", response_model=ScreenshotOut)
async def screenshot(body: ScreenshotIn, settings: Settings = Depends(get_settings)):
    # Local import — we rely on main.py having set `app.state.backend` already.
    import base64

    from fastapi import Request
    import inspect

    # Get the active backend from the lifespan state (same pattern as /sync).
    # We use inspect to peek at the calling request's app.state — or expose
    # it via a tiny helper; both are equivalent. Simplest: pull from module.
    from . import main as app_main  # avoids circular import at module load
    backend = app_main._backend_ref  # set in lifespan below
    if backend is None or getattr(backend, "_ctx", None) is None:
        raise HTTPException(503, "browser context not open yet; call /sync first")

    if (body.path is None) == (body.url is None):
        raise HTTPException(400, "pass exactly one of `path` or `url`")

    target = body.url or (settings.canvas_base_url.rstrip("/") + body.path)

    page = await backend._ctx.new_page()
    try:
        await page.goto(target, wait_until="networkidle", timeout=body.timeout_ms)
        png = await page.screenshot(full_page=body.full_page, type="png")
    except Exception as e:
        log.warning("screenshot %s failed: %s", target, e)
        raise HTTPException(502, f"navigate/screenshot failed: {e}")
    finally:
        await page.close()

    return ScreenshotOut(
        png_b64=base64.b64encode(png).decode(),
        target_url=target,
        bytes=len(png),
    )
```

### 2. New file `apps/browser-agent/app/myasu.py`

MyASU login + GPA snapshot. The DOM selectors are the **honest-first-pass**
guess from the current my.asu.edu layout; Abishek should run it against his
real account once and adjust the selectors if they don't match. Everything
lives in the SAME browser context so login cookies stick across calls.

```python
"""MyASU GPA + term-grades snapshot.

Flow:
  1. POST /myasu/login — opens my.asu.edu, user completes SSO + MFA in
     the live Playwright viewer (TinyFish stream shows it). We wait up to
     5 min for /my-asu/ to be the current URL.
  2. GET  /myasu/snapshot — reads the current grades/transcript page and
     returns {gpa, hours, terms: [{term, courses: [{code, grade, credits}]}]}.

Storage: zero. The browser context keeps cookies; no DB. On restart the user
must /myasu/login again (fine for demo).

Selectors are best-effort guesses; rerun /myasu/snapshot and tweak if blank.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter()

MYASU_HOME = "https://my.asu.edu"
MYASU_GRADES = "https://my.asu.edu/myasu/grades"  # adjust after live test


class LoginOut(BaseModel):
    status: str                 # "logged_in" | "pending" | "failed"
    live_view_url: str | None   # TinyFish stream for the user to complete SSO
    detail: str | None = None


@router.post("/myasu/login", response_model=LoginOut)
async def myasu_login():
    from . import main as app_main
    backend = app_main._backend_ref
    if backend is None or getattr(backend, "_ctx", None) is None:
        raise HTTPException(503, "browser context not open yet")

    page = await backend._ctx.new_page()
    try:
        await page.goto(MYASU_HOME, wait_until="domcontentloaded", timeout=20_000)
        # Wait up to 5 min for the user to complete ASU SSO + Duo.
        # We detect success by URL contains '/myasu/' or by a known logged-in element.
        try:
            await page.wait_for_url(lambda u: "/myasu/" in u, timeout=300_000)
            status = "logged_in"
            detail = None
        except Exception:
            status = "pending"
            detail = "timed out waiting for /myasu/ path (SSO not completed in 5 min)"
    finally:
        await page.close()

    live_view = None
    try:
        live_view = f"{backend._session['base_url']}/stream/latest"
    except Exception:
        pass
    return LoginOut(status=status, live_view_url=live_view, detail=detail)


class Course(BaseModel):
    code: str
    name: str | None = None
    grade: str | None = None
    credits: float | None = None


class Term(BaseModel):
    term: str
    courses: list[Course]
    term_gpa: float | None = None


class Snapshot(BaseModel):
    gpa: float | None = None
    total_hours: float | None = None
    terms: list[Term]


@router.get("/myasu/snapshot", response_model=Snapshot)
async def myasu_snapshot():
    from . import main as app_main
    backend = app_main._backend_ref
    if backend is None or getattr(backend, "_ctx", None) is None:
        raise HTTPException(503, "browser context not open yet")

    page = await backend._ctx.new_page()
    try:
        await page.goto(MYASU_GRADES, wait_until="networkidle", timeout=20_000)
        if "/myasu/" not in page.url:
            raise HTTPException(401, "not logged in to MyASU — call /myasu/login first")

        # Best-effort scrape. Adjust these selectors after one live run.
        data: dict[str, Any] = await page.evaluate(
            """() => {
                const txt = (el) => (el && el.textContent || '').trim();
                const g = document.querySelector('[data-testid="cumulative-gpa"], .cumulative-gpa');
                const h = document.querySelector('[data-testid="total-hours"], .total-hours');
                const terms = [];
                document.querySelectorAll('[data-testid="term-block"], .term-block').forEach((t) => {
                    const termLabel = txt(t.querySelector('[data-testid="term-label"], .term-label'));
                    const termGpaEl = t.querySelector('[data-testid="term-gpa"], .term-gpa');
                    const courses = [];
                    t.querySelectorAll('[data-testid="course-row"], .course-row').forEach((c) => {
                        courses.push({
                            code: txt(c.querySelector('[data-testid="code"], .code')),
                            name: txt(c.querySelector('[data-testid="name"], .name')) || null,
                            grade: txt(c.querySelector('[data-testid="grade"], .grade')) || null,
                            credits: parseFloat(txt(c.querySelector('[data-testid="credits"], .credits'))) || null,
                        });
                    });
                    terms.push({
                        term: termLabel || '(unknown)',
                        term_gpa: termGpaEl ? parseFloat(txt(termGpaEl)) : null,
                        courses,
                    });
                });
                return {
                    gpa: g ? parseFloat(txt(g)) : null,
                    total_hours: h ? parseFloat(txt(h)) : null,
                    terms,
                };
            }"""
        )
    finally:
        await page.close()

    return Snapshot(**data)
```

### 3. Patch `apps/browser-agent/app/main.py`

Expose the routers + stash the backend reference so the new endpoints can
reach the open Playwright context.

```diff
@@ imports
+from . import myasu, screenshot
@@
 app = FastAPI(..., lifespan=lifespan)
+# Both screenshot + myasu routers reach the Playwright context by reading
+# `app_main._backend_ref` set in the lifespan. Exposing them here so FastAPI
+# serves /screenshot and /myasu/* with the same auth guard as everything else.
+app.include_router(screenshot.router, dependencies=protected)
+app.include_router(myasu.router,       dependencies=protected)
@@
+# Set by the lifespan below; screenshot.py + myasu.py read it.
+_backend_ref = None
@@
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     ...
     backend = get_backend(settings)
+    global _backend_ref
+    _backend_ref = backend
     await backend.open_session()
     ...
     yield
     await backend.close_session()
+    _backend_ref = None
```

### 4. Patch `apps/browser-agent/app/mcp_server.py` — MCP tools

```diff
+    @mcp.tool(description=(
+        "Capture a full-page PNG screenshot of a Canvas path or any MyASU URL "
+        "using the live Playwright session. Returns base64 PNG. Used by the "
+        "credential agent as a witness image when minting NFTs."
+    ))
+    async def capture_screenshot(path: str | None = None,
+                                  url: str | None = None,
+                                  full_page: bool = True) -> dict:
+        from . import screenshot as _s
+        return (await _s.screenshot(
+            _s.ScreenshotIn(path=path, url=url, full_page=full_page),
+            settings=get_settings(),
+        )).model_dump()
+
+    @mcp.tool(description=(
+        "Open my.asu.edu in the live browser so the student can complete SSO. "
+        "Returns the TinyFish live-view URL — the student clicks that, finishes "
+        "ASU login + Duo, then calls get_myasu_snapshot to read the grades."
+    ))
+    async def myasu_login() -> dict:
+        from . import myasu as _m
+        return (await _m.myasu_login()).model_dump()
+
+    @mcp.tool(description=(
+        "Read the student's MyASU grades + cumulative GPA. Must have called "
+        "myasu_login first within the same server session so cookies are warm."
+    ))
+    async def get_myasu_snapshot() -> dict:
+        from . import myasu as _m
+        return (await _m.myasu_snapshot()).model_dump()
```

---

## How to apply (Abishek, you)

```bash
cd apps/browser-agent
# 1) drop in the two new files from this doc
$EDITOR app/screenshot.py
$EDITOR app/myasu.py

# 2) apply the main.py + mcp_server.py diffs above

# 3) restart
pkill -f "uvicorn app.main:app --port 9001"
.venv/bin/uvicorn app.main:app --port 9001
```

Quick smoke:

```bash
curl -sS http://127.0.0.1:9001/health   # should still be 200

# screenshot test (Canvas path)
curl -sS -X POST http://127.0.0.1:9001/screenshot \
    -H "X-Canvas-Key: $CANVAS_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"path": "/grades"}' | jq '.bytes, .target_url'

# MyASU login (returns a live_view URL; click it, finish SSO, re-run snapshot)
curl -sS -X POST http://127.0.0.1:9001/myasu/login \
    -H "X-Canvas-Key: $CANVAS_API_KEY"

curl -sS http://127.0.0.1:9001/myasu/snapshot \
    -H "X-Canvas-Key: $CANVAS_API_KEY" | jq
```

## Honest caveats

- **MyASU selectors are guesses.** We don't have your my.asu.edu HTML
  structure in the repo. Run `/myasu/snapshot` once and if it returns
  empty terms[], inspect the DOM and tighten the selectors.
- **Playwright context is shared.** Opening MyASU in the same context used
  for Canvas means tabs can interfere. `page.close()` after each call
  prevents the worst of it; keep each call short.
- **5-minute SSO wait is blocking.** The /myasu/login call holds a
  connection open until SSO finishes. If you want non-blocking, we can
  switch to a background task + a /myasu/status poll — ask when you
  want it.
- **TinyFish live view** URL is already public; confirm you're okay
  surfacing it to Nova (it shows your browser in real time during SSO).

Once this ships, cred-agent's `browser_client.try_capture("/grades")`
will succeed and the mint will embed a real PNG witness.
