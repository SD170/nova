# Abishek — context + notes

Owner: Abishek (GitHub: Abishek1801)
Role: **Browser agent — real Canvas data via TinyFish, item classification, and the to-do list**
Code: `apps/browser-agent/` (FastAPI, port **9001** from `shared.env`) — merged to `main`.

## Status (Nov 14, night)

- ✅ **Working on real ASU Canvas.** One sync ≈ 7 s for Canvas + ≈ 5–25 s for Gemini. Answers are instant from cache.
- ✅ **To-do list = only work not submitted yet.** Submitted / excused / marked-complete items never appear (hard rule).
- ✅ **Gemini** writes "what to do" steps, topics and notes for each open item.
- ✅ **Saswata's TODOs 1, 2, 3, 5 done:** `/brief`, `/items/{id}`, `/items/{id}/user-done` (+ undo), public Cloudflare URL with a shared-secret header. Reads never block on a sync any more.
- ✅ **Course materials (TODO 4) done:** real lists for all 3 courses (269 materials: syllabus, linked syllabus PDFs, lecture PDFs, Canvas pages, links) + plain text on demand with `[page N]` markers.
- ✅ **MCP (TODO 6) done:** same service also at `/mcp` (streamable-HTTP), 11 tools, same `X-Jarvis-Key`. REST unchanged.
- ⏳ **Not built yet:** exam dates from announcements, grades.
- There is **no Canvas API token** for ASU accounts. All Canvas data comes through a TinyFish browser that is logged in as the student.

## Decisions (locked)

1. **TinyFish** provides the logged-in browser. We do **not** use TinyFish's AI agent (TinyAgent) for Canvas — tested: 1–2 min per page, text dates, and TinyFish's safety check blocked reading Canvas JSON. Instead our code reads Canvas's own JSON inside the TinyFish browser: ~7 s, exact dates, exact submitted flags.
2. **Separate service, two faces:** REST (`/brief`, `/items/...`) and MCP (`/mcp`) over the same code, port 9001. No shared Python imports.
3. **Only the orchestrator writes to supermemory.** The browser agent just returns data.
4. **Classification is explainable:** every item has `classified_by` + `reason`, and the to-do filter is a hard rule the LLM cannot override.
5. **Read-only:** only GET requests to Canvas. Never submits, posts, clicks or starts a quiz.
6. **LLM = Gemini** (`gemini-3.5-flash`, falls back to `gemini-3.5-flash-lite`). Without a key the service still works with rules only.
7. **Plan B (local Chrome + AgentQL) dropped.** If ever needed, the same JSON code can point Playwright at a local Chrome instead.
8. **Materials: this service extracts the text** (only it has the logged-in browser). Amrita gets plain text + page markers and does chunking/embedding herself.
9. **Materials are listed every sync, text is fetched on demand** (CSE 507 alone has 424 MB of PDFs). Pre-fetched each sync: syllabus + syllabus-linked PDFs + modules dated this/next week. Files over 25 MB (whole textbooks) are `too_large`; `.zip/.rar`, images, video are skipped; external links are listed, never followed.

## The flow — one sync, step by step

```
Orchestrator (Saswata) ──HTTP──> apps/browser-agent :9001
                                   │
   any read (/brief, /items/next, ...):
     snapshot fresh (< 30 min)       → answer instantly
     snapshot stale                  → answer instantly with it AND refresh in the background
                                       (/brief shows sync_in_progress=true while it runs)
     no snapshot yet (first run)     → wait for one sync
   POST /sync                        → sync now and wait
                                   │
                                   ▼
 1. TinyFish: open a cloud browser from the saved Browser Context Profile
    ("Jarvis - ASU Canvas", already logged in — Duo was done once, by hand)        ~1 s
 2. Playwright connects to that browser (CDP)                                        ~0.5 s
 3. Read Canvas JSON with the browser's logged-in cookies (read-only):              ~2–5 s
      /api/v1/planner/items     → everything due, ALL courses, one call,
                                  incl. submitted / excused / marked-complete flags
      /api/v1/courses           → course names (current = has work due; ASU leaves term dates empty)
      /api/v1/courses/:id/assignments/:id → instructions, submission types, LockDown flag (parallel)
 3b. Materials list (all courses in parallel)                                         ~7 s
      /api/v1/courses/:id/modules?include[]=items  → files, pages, links + module name/dates
      /api/v1/courses/:id/files                    → extra files (403 in CSE 540/579 = skipped)
      /api/v1/courses/:id?include[]=syllabus_body  → syllabus + PDFs linked from it
 3c. Pre-extract text: syllabus + this/next week's modules (≤ 12 per course, ≤ 60 s;
      cached in data/materials/, so later syncs only fetch new/changed files)
 4. Close the browser WITHOUT saving (the saved login is untouched)
 5. Gemini: ONE batched call with only the OPEN items (not submitted work,
    not office hours) → type check, steps, topics, notes                             ~5–25 s
 6. classify each item: rules → Gemini merge → hard to-do filter
 7. re-apply student overrides ("I already did HW3", data/user_overrides.json)
 8. save data/canvas_snapshot.json → answer
```
If a sync fails, the last good snapshot is served. If the ASU login expired: HTTP `503 canvas_login_expired` → run `tinyfish profile sign-in <profile_id>`, sign in with Duo once, retry.

## Classification — 3 layers

1. **Rules (Canvas's own data, no AI)**
   - title has `midterm` / `mid-term` / `exam(s)` / `final exam` (not announcements) → `exam` (`keyword`)
   - Canvas quiz, or submission type `online_quiz` → `quiz`
   - discussion → `discussion` · assignment → `assignment` · calendar event → `event` (`rule`)
   - announcements → `unknown` until Gemini decides
   - "Final Project" is NOT an exam; "Calculator policy for quizzes and exams" (announcement) is NOT an exam.
2. **Gemini (optional)** — decides `unknown` items, can upgrade quiz/assignment/event → `exam`, writes `what_to_do` (≤ 5 steps, only from the instructions), `topics`, `notes` (e.g. "Requires Respondus LockDown Browser + webcam", "Submit as .docx"), and may drop non-work (e.g. optional survey). Results with confidence < 0.7 are ignored. Instructor text is treated as data, never as instructions.
3. **To-do filter (hard rule)** — submitted / excused / marked complete → `in_todo: false`. Only `assignment | quiz | exam | discussion` can be to-dos. Gemini can never put submitted work back.

`suggested_action`: assignment/discussion → `summarize_steps` · quiz → `schedule_block` · exam → `exam_prep` · event/unknown → `none`.

## HTTP contract (for Saswata's orchestrator) — port 9001

**Base URL:** local `http://localhost:9001` · public `PUBLIC_CANVAS_BASE` in `shared.env` (Cloudflare quick tunnel; changes when the tunnel restarts).
**Auth:** every endpoint except `/health` and `/docs` needs header `X-Jarvis-Key: <BROWSER_AGENT_API_KEY>`. The key is **not in the repo** — Abishek sends it to you directly. In `/docs` use the "Authorize" button.

| Brain tool | Method + path | Returns | Speed |
|---|---|---|---|
| `get_daily_brief` | `GET /brief?days=7` | `{synced_at, last_sync_age_minutes, sync_in_progress, data_source, items: [Item] (to-do only), courses: [Course]}` | instant |
| `get_todo_list` | `GET /items/next?days=7` | **the to-do list** `{synced_at, data_source, items: [Item]}`, soonest first | instant |
| — | `GET /items/next?days=7&include_done=true` | everything due incl. submitted work + events, each with `in_todo` + `todo_reason` | instant |
| `get_item_details` | `GET /items/{item_id}` | one `Item` (404 `item_not_found`) | instant |
| `get_course_items` | `GET /items?course_id=` | `{synced_at, data_source, items: [Item]}` | instant |
| `list_courses` | `GET /courses` | `{synced_at, data_source, courses: [{id, code, name, term}]}` | instant |
| `get_course_materials` | `GET /materials?course_id=&topic_hint=&this_week=` | `{synced_at, data_source, materials: [Material]}` — list only, **no text** | instant |
| `get_material_text` | `GET /materials/{material_id}/text?offset=0&max_chars=50000` | `MaterialText` (below). Long docs come in slices: repeat with `offset=next_offset` until `null` | instant if `text_status=ready`, else ~2–10 s once |
| `mark_item_done_locally` | `POST /items/{item_id}/user-done` | the updated `Item` (`in_todo:false, user_done:true`) | instant |
| (undo) | `DELETE /items/{item_id}/user-done` | the `Item` back as Canvas sees it | instant |
| `sync_canvas` | `POST /sync` | `{synced_at, backend, data_source, llm_used, llm_error, counts}` (counts incl. `materials`, `materials_with_text`) | 15–45 s |
| `get_canvas_health` | `GET /health` | `{ok, backend, llm, last_sync, sync_in_progress, last_error}` | instant |

Errors: `401` missing/wrong `X-Jarvis-Key` · `404 item_not_found` / `material_not_found` · `422 material_text_unavailable` (too large / link / unsupported — use its `url`) · `503 canvas_login_expired` (Abishek re-signs in) · `502` backend failure (see `detail`).
**Reads never block on Canvas:** if the cache is stale they return the old data immediately and refresh in the background, so the brain never waits ~30 s mid-conversation. Only the very first call after a fresh start waits for one sync.

**`user-done` semantics (differs slightly from the original TODO 3, on purpose):** Canvas is never written to. The override is stored in `data/user_overrides.json` and **survives re-syncs** (otherwise HW3 would pop back into the to-do list every 30 min while Canvas still says "not submitted"). It is dropped automatically when Canvas shows the item submitted/excused/complete, or when the due date passes. Marking an item that is already done in Canvas is a no-op. The brain should still write "student says HW3 done" to supermemory.

### Item (real example, trimmed)
```json
{
  "id": "assignment-7796330",
  "course_id": "273189",
  "course_code": "CSE 579",
  "type": "assignment",
  "title": "Assignment 3: More Challenging Answer Set Programming",
  "due_at": "2026-11-16T06:59:59Z",
  "points": 40.0,
  "source_url": "https://canvas.asu.edu/courses/273189/assignments/7796330",
  "submitted": false,
  "user_done": false,
  "in_todo": true,
  "todo_reason": "Not submitted yet",
  "what_to_do": ["Use template pa3.docx and name file pa3.docx",
                 "Show input program, command line as text, and clingo output screenshot for each problem"],
  "topics": ["Answer Set Programming", "clingo"],
  "notes": ["Submit as .docx"],
  "suggested_action": "summarize_steps",
  "classified_by": "rule",
  "confidence": null,
  "reason": "Canvas type: assignment",
  "data_source": "live"
}
```
- `type`: `assignment | quiz | exam | discussion | event | unknown`
- `due_at` is UTC ISO-8601 (convert to America/Phoenix for display).
- `data_source`: `live` (real Canvas) or `demo` (mock) — demo is always labeled, never shown as live.

### Material + MaterialText (real example, trimmed)
```json
{"id": "page-266933-required-reading-and-summaries-module-5", "course_id": "266933", "course_code": "CSE 540",
 "title": "Required Reading and Summaries: Module 5", "type": "page",
 "url": "https://canvas.asu.edu/courses/266933/modules/items/...",
 "module": "(11/11 - 11/17) Module 5: Mining", "module_position": 7, "position": 3,
 "week_start": "2026-11-11", "week_end": "2026-11-17",
 "content_type": null, "size_bytes": null, "updated_at": null, "text_status": "ready"}
```
- `id`: `syllabus-<course>` · `file-<id>` · `page-<course>-<slug>` · `link-<course>-<item>`
- `type`: `syllabus | pdf | page | file | link`. Files linked from the syllabus have `module: "Syllabus"` (e.g. "CSE 540 …_Syllabus.pdf" — exam dates live there).
- `text_status`: `ready` (cached, instant) · `not_fetched` (fetched on first text call) · `too_large` · `unsupported` (pptx/docx…) · `link_only` · `locked` · `error`.
- `week_start/week_end` only when the module name has dates (CSE 540 yes; CSE 507/579 no → null).
- `topic_hint` = loose match on title + module words (`heaps`, `module 5`). `this_week=true` = modules dated today..+7 days + syllabus.

`GET /materials/{id}/text` → `{material_id, course_id, course_code, title, type, module, source_url, fetched_at, pages, total_chars, offset, next_offset, text}`. PDF text has `[page N]` markers → cite `source_url` + page. Text is never committed (cached in gitignored `data/materials/`).

### MCP — same tools at `/mcp` (streamable-HTTP)
URL `${PUBLIC_CANVAS_BASE}/mcp`, header `X-Jarvis-Key` (401 without). Tools (args → same JSON as REST):
`get_daily_brief(days)` · `get_todo_list(days, include_done)` · `get_item_details(item_id)` · `mark_item_done_locally(item_id)` · `unmark_item_done(item_id)` · `list_courses()` · `get_course_items(course_id, include_done)` · `get_course_materials(course_id, topic_hint?, this_week?)` · `get_material_text(material_id, offset=0, max_chars=20000)` · `sync_canvas()` · `get_canvas_health()`.
Errors come back as MCP tool errors with a readable message (e.g. "too_large … use the url"). Tested through the tunnel with the official MCP Python client: reads ≈ 0.1 s.

### Demo data without keys
`BROWSER_BACKEND=mock` serves labeled fake courses (CSE 310, MAT 343). Static copy: `apps/browser-agent/mocks/canvas_snapshot.json`.

## What each file does (`apps/browser-agent/`)

| File | Responsibility |
|---|---|
| `app/main.py` | HTTP routes, `X-Jarvis-Key` auth, error mapping (401, 404, 503 login expired, 502). No logic. |
| `app/service.py` | One sync: `start_sync → courses → items → details (parallel) → end_sync → Gemini batch → classify → overrides → save`. Reads: fresh → instant, stale → instant + background refresh. Also `/brief`, item lookup, user-done/undo, to-do query. |
| `app/overrides.py` | Student "I already did it" overrides in `data/user_overrides.json`; re-applied after each sync, auto-pruned when Canvas catches up or the due date passes. |
| `app/backends/base.py` | Contract every backend follows + `CanvasLoginExpired`. |
| `app/backends/tinyfish.py` | Opens the TinyFish profile browser, connects Playwright, reads Canvas JSON, converts it to `RawItem`s, lists materials, downloads one material's text, closes the browser. |
| `app/backends/mock.py` | Labeled demo data, no keys. |
| `app/classify.py` | Rules → Gemini merge → hard to-do filter → `Item`. |
| `app/llm.py` | Gemini classifier: one batched call, structured JSON output, model fallback, safe prompt. |
| `app/models.py` | All JSON shapes: `RawItem`, `Item`, `Course`, `Material`, `Snapshot`, `SyncResult`, `Health`, `Brief`. |
| `app/cache.py` | `data/canvas_snapshot.json` (gitignored) + freshness check. |
| `app/config.py` | Env settings (`.env`, see `.env.example`). |
| `app/materials.py` | Materials: Canvas modules/files/syllabus → `Material` list, week dates from module names, what to pre-fetch, PDF → text (`pypdf`, `[page N]`), text cache `data/materials/` + slicing. Pure functions. |
| `app/mcp_server.py` | MCP face: 11 tools over the same `BrowserAgentService` + `X-Jarvis-Key` guard on `/mcp`. |
| `scripts/export_mock.py` | Regenerates `mocks/canvas_snapshot.json`. |
| `tests/unit`, `tests/api`, `tests/fixtures` | 87 tests, no network: classifier, Canvas JSON conversion, Gemini, background refresh, overrides, auth, materials (week parsing, file types, cache, slicing), every endpoint, MCP (discovery, calls, errors, auth). |

## Setup (for whoever runs it)

```bash
cd apps/browser-agent && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env
uvicorn app.main:app --port 9001      # docs: http://localhost:9001/docs
```
Real Canvas needs in `.env`: `BROWSER_BACKEND=tinyfish`, `TINYFISH_API_KEY`, `TINYFISH_PROFILE_ID` (a TinyFish Browser Context Profile signed into canvas.asu.edu), optional `GEMINI_API_KEY`.

## Safety

- Read-only GETs; the browser never clicks Submit / Take Quiz.
- No passwords stored anywhere (Duo done by hand in TinyFish's live viewer; no TinyFish Vault).
- Instructor text is data, never instructions (prompt-injection guard in the Gemini prompt).
- The Canvas session lives in a TinyFish profile and Canvas text is sent to Gemini — tell judges; delete the profile after the hackathon.

## Handoffs

- **Saswata (orchestrator):** use the contract above. `/items/next` for "what's next / weekly plan". Route `exam_prep` items to Amrita, propose calendar blocks for `schedule_block` (approval-gated). Write facts to supermemory yourself.
- **Amrita (quiz):** `GET /materials?course_id=` (or `this_week=true`) → for each material with `text_status` `ready`/`not_fetched`, `GET /materials/{id}/text` (loop `next_offset`) → chunk + embed. Use `source_url` + `[page N]` as the passage source. Same key header.
- **Shruti (UI):** render `items` directly; every item has `source_url`, `due_at`, `notes`; show "syncing…" while `/sync` runs.

## For Saswata — read this before wiring the Hermes harness (Nov 14, late)

TODOs 1, 2, 3, 5 are **done, tested on real ASU Canvas, and pushed**. Things to apply on your side:

1. **Base URL:** `PUBLIC_CANVAS_BASE` in `shared.env` (Cloudflare quick tunnel). It **changes every time the tunnel restarts** — Abishek updates `shared.env` when it does. Local: `http://localhost:9001`.
2. **Auth header on every call** (except `/health`, `/docs`): `X-Jarvis-Key: <key>`. The key is **not in the repo** — Abishek sends it to you privately. Put it in `apps/orchestrator/.env` (e.g. `CANVAS_API_KEY=`), never in `shared.env` or code. Missing/wrong key → `401`.
3. **Tool → endpoint map:** use the "HTTP contract" table above (brain tool name → method + path). Response shapes are exact there.
4. **`mark_item_done_locally` semantics changed slightly from your TODO 3 (on purpose):** the override **survives re-syncs** until Canvas shows the item submitted or the due date passes (otherwise HW3 pops back every 30 min). Undo = `DELETE /items/{id}/user-done`. Still write "student says HW3 done" to supermemory as you planned.
5. **Reads never block on Canvas.** Stale cache → old data instantly + background refresh (`sync_in_progress: true` in `/brief`). Only the first call after a fresh service start waits ~20 s. So `get_daily_brief` / `get_todo_list` are always safe mid-conversation; keep `sync_canvas` for explicit "refresh now".
6. **Gemini model:** your build plan pins **Gemini 2.5 Flash** — with a new API key Google returns *404 "no longer available to new users"*. Use **`gemini-3.5-flash`** (≈5 s) or `gemini-3.5-flash-lite` (≈1 s). On Nov 14, `gemini-3.7-flash` / `gemini-3.8-flash` hung > 2 min and `gemini-flash-latest` returned 503. Add a fallback model + a ~30 s timeout.
7. **Port mismatch to settle with Amrita:** your diagram says materials/quiz on `:9003`, `shared.env` says `RETRIEVAL_QUIZ_PORT=9002`.
8. **Error handling in the brain:** `503 canvas_login_expired` → tell the user "Canvas login expired, Abishek needs to re-sign in" (don't retry in a loop). `404 item_not_found` → item ids come from `/brief` or `/items/next` (format `assignment-7796330`, `quiz-2062789`, `discussion_topic-…`).
9. **Materials done (TODO 4):** list + text, see contract. **New tool `get_material_text(material_id, offset, max_chars)`** (asked for by exam prep / Amrita: the list alone has no text) and two optional args on `get_course_materials`: `topic_hint`, `this_week`. Shout if you want different names.
10. **MCP done (TODO 6), at `/mcp`.** Your config snippet works as is (`url: ${PUBLIC_CANVAS_BASE}/mcp`, header `X-Jarvis-Key`). Three things differ from your sketch, on purpose: (a) uses the `mcp` **1.x** SDK (`mcp>=1.20,<2`) — 2.x renamed `FastMCP`; (b) auth is an ASGI guard on `/mcp` (a mounted sub-app skips FastAPI's `Depends`, so your sketch would have left `/mcp` open); (c) host check off (requests come via the Cloudflare host), key check does the protecting. `json_response` + stateless mode.
11. **Exam prep flow (your side):** `get_course_materials(course_id, this_week=true)` → syllabus + current module; `get_material_text` on the syllabus/syllabus PDF for exam dates & coverage, then on the module files. Don't invent coverage — every claim cites `source_url`.

## TODO from Saswata (orchestrator) — unblocks voice demo

System design is locked (`context/saswata.md` → "System design — LOCKED"). Your service stays stateless; brain owns supermemory. Four endpoint-level todos + one infra todo. All in your existing cache / Snapshot shape, no architectural change.

Format: each item is a copy-pasteable instruction. Mark `[x]` when done.

### [x] TODO 1 — add `GET /brief?days=7` endpoint — DONE (also returns `data_source`; `sync_in_progress` is real)

Single bundled call for voice "good morning / what's due" and the Daily Pulse cron. Saves 2-3 round trips per common prompt.

```python
class BriefResponse(BaseModel):
    synced_at: datetime
    last_sync_age_minutes: float
    sync_in_progress: bool = False
    items: list[Item]        # to-do only, soonest first
    courses: list[Course]    # current-term only

@app.get("/brief", response_model=BriefResponse)
async def brief(request: Request, days: int = Query(7, ge=1, le=60)):
    snap = await snapshot_or_502(request)
    items = BrowserAgentService.next_items(snap, days, include_done=False)
    age_min = (datetime.now(timezone.utc) - snap.synced_at).total_seconds() / 60
    return BriefResponse(items=items, courses=snap.courses, synced_at=snap.synced_at,
                        last_sync_age_minutes=round(age_min, 1))
```

Brain calls this as `get_daily_brief`. This becomes the single most-called tool in the system.

### [x] TODO 2 — add `GET /items/{item_id}` endpoint — DONE

For "tell me more about HW3" — full details from cached snapshot.

```python
@app.get("/items/{item_id}", response_model=Item)
async def item_detail(request: Request, item_id: str):
    snap = await snapshot_or_502(request)
    for i in snap.items:
        if i.id == item_id:
            return i
    raise HTTPException(status_code=404, detail=f"item {item_id} not found")
```

Brain calls this as `get_item_details`.

### [x] TODO 3 — add `POST /items/{item_id}/user-done` endpoint — DONE (override survives re-syncs until Canvas catches up; `DELETE` = undo; see contract above)

Student says "I already did HW3." We flag locally until next sync overwrites. Canvas remains untouched.

Semantics:
- Does NOT write to Canvas. Read-only service stays read-only.
- Flags `in_todo=false`, `todo_reason="Marked done by student (override; next Canvas sync will reconcile)"`.
- Next `POST /sync` wipes it. Canvas truth wins when fresh.
- Brain writes "student says X done at <ts>" to supermemory so it survives the resync.

```python
# routes
@app.post("/items/{item_id}/user-done", response_model=Item)
async def mark_user_done(request: Request, item_id: str):
    return await request.app.state.service.mark_user_done(item_id)

# BrowserAgentService
async def mark_user_done(self, item_id: str) -> Item:
    async with self._lock:
        snap = self.cache.load()
        if snap is None:
            raise HTTPException(503, "no snapshot yet; call /sync first")
        for idx, i in enumerate(snap.items):
            if i.id == item_id:
                snap.items[idx] = i.model_copy(update={
                    "in_todo": False,
                    "todo_reason": "Marked done by student (override; next Canvas sync will reconcile)",
                })
                self.cache.save(snap)
                return snap.items[idx]
        raise HTTPException(404, f"item {item_id} not found")
```

Brain calls this as `mark_item_done_locally`.

### [x] TODO 4 — materials pipeline — DONE (list + on-demand text + pre-fetch; see contract → Material)

Already your top priority. Minimal first cut unblocks Amrita even without PDF extraction:

- `TinyFishBackend.fetch_materials(course)` reads `/api/v1/courses/{id}/files` + `/api/v1/courses/{id}/modules` (same JSON pattern as planner/items).
- Return `Material` with `id`, `course_id`, `title`, `type`, `url`.
- Text extraction (your step 1's `pypdf` pass) can land in a second commit — Amrita can validate her embedding pipeline off URLs first.

### [x] TODO 5 — expose your service over Cloudflare tunnel — DONE (URL in `shared.env` → `PUBLIC_CANVAS_BASE`; needs `X-Jarvis-Key` header)

Saswata already did this for `apps/voice/` — follow the exact same pattern so your `:9001` service is reachable from anywhere (orchestrator / phone / judge laptop during demo), not just localhost.

Steps:
1. `brew install cloudflared` if not already installed (`which cloudflared` to check).
2. Start the Canvas service on port 9001: `cd apps/browser-agent && uvicorn app.main:app --port 9001`
3. In a second terminal: `cloudflared tunnel --no-autoupdate --url http://localhost:9001`
4. Cloudflared prints a public URL like `https://xxx-yyy-zzz.trycloudflare.com` — copy it.
5. Verify from anywhere: `curl https://xxx-yyy-zzz.trycloudflare.com/health` → should return 200.
6. Add to `shared.env` at repo root (edit directly, commit):
   ```
   # Canvas service — Abishek, apps/browser-agent on port 9001
   PUBLIC_CANVAS_BASE=https://xxx-yyy-zzz.trycloudflare.com
   ```
7. Update if cloudflared restarts and gives a new URL (quick tunnels are ephemeral).

Why this matters:
- Orchestrator (Saswata, `apps/orchestrator`) can call your service from a different machine / deployed Hermes profile.
- Judges can hit `/docs` live on your Cloudflare URL during the demo — "here's the real Canvas service" moment.
- Daily Pulse cron running on Maritime can reach it.

Notes:
- Quick-tunnel URL changes every cloudflared restart. Pin a named tunnel only if we have time (not blocking).
- Zero auth on the tunnel for now — service is read-only + no PII beyond the signed-in Canvas account. Fine for 24h hackathon window. **Delete tunnel after the event.**

### [x] TODO 6 — expose the service as an MCP server (streamable-HTTP) — DONE (`/mcp`, 11 tools; see "For Saswata" #10 for the 3 differences from this sketch)

Reverses the earlier "HTTP, not MCP for sub-agents" decision. Trade: ~2-3h of restructuring vs cleaner Hermes config + standard MCP discovery. Non-functional improvement, same end-to-end latency.

**Goal:** Hermes (and any future MCP client — Claude Code, Cursor, etc.) can discover your Canvas tools via one URL instead of a hand-rolled custom-tools block in the Shruti Hermes profile.

**What to build:** mount an MCP server at `/mcp` on the same FastAPI app (port 9001). Keep the existing REST endpoints alive — the UI uses them, tests use them, nothing else changes. MCP becomes a second face over the same `BrowserAgentService`.

**Transport:** streamable-HTTP (not stdio). Matches how Vapi's and supermemory's MCPs work; works with the tunnel; Hermes's native MCP client supports it.

**Recommended library:** `mcp` (the official Python SDK, already published by Anthropic). Use `FastMCP` — it has a FastAPI integration, you can mount it on the existing app without a second process.

```bash
pip install "mcp[cli]"
# (or whatever your requirements.txt lives as — uv/poetry/pip, keep consistent)
```

**Code sketch:**

```python
# apps/browser-agent/app/mcp_server.py  (new file)
from mcp.server.fastmcp import FastMCP
from .service import BrowserAgentService
from .models import Item, Course

def build_mcp(svc: BrowserAgentService) -> FastMCP:
    mcp = FastMCP("canvas", stateless_http=True)   # streamable-HTTP mode

    @mcp.tool(description="Student's to-do list + courses in one call, instant from cache.")
    async def get_daily_brief(days: int = 7) -> dict:
        await svc.get_snapshot()
        brief = await svc.brief(days)
        return brief.model_dump(mode="json")

    @mcp.tool(description="Upcoming to-do items (not submitted), soonest first.")
    async def get_todo_list(days: int = 7, include_done: bool = False) -> dict:
        snap = await svc.get_snapshot()
        items = BrowserAgentService.next_items(snap, days, include_done)
        return {"synced_at": snap.synced_at.isoformat(),
                "data_source": snap.data_source.value,
                "items": [i.model_dump(mode="json") for i in items]}

    @mcp.tool(description="Full details for one Canvas item by id.")
    async def get_item_details(item_id: str) -> dict:
        await svc.get_snapshot()
        item = await svc.get_item(item_id)
        return item.model_dump(mode="json")

    @mcp.tool(description="Student marks an item done locally (Canvas unchanged).")
    async def mark_item_done_locally(item_id: str) -> dict:
        item = await svc.mark_user_done(item_id)
        return item.model_dump(mode="json")

    @mcp.tool(description="Undo mark-done (student didn't actually finish it).")
    async def unmark_item_done(item_id: str) -> dict:
        item = await svc.undo_user_done(item_id)
        return item.model_dump(mode="json")

    @mcp.tool(description="List current-term courses (ones with work due).")
    async def list_courses() -> dict:
        snap = await svc.get_snapshot()
        return {"synced_at": snap.synced_at.isoformat(),
                "courses": [c.model_dump(mode="json") for c in snap.courses]}

    @mcp.tool(description="Items for one course (include_done to see submitted work too).")
    async def get_course_items(course_id: str, include_done: bool = True) -> dict:
        snap = await svc.get_snapshot()
        items = [i for i in snap.items if i.course_id == course_id]
        if not include_done:
            items = [i for i in items if i.in_todo]
        return {"synced_at": snap.synced_at.isoformat(),
                "items": [i.model_dump(mode="json") for i in items]}

    @mcp.tool(description="Course materials for Amrita's quiz engine — may be empty until TODO 4 lands.")
    async def get_course_materials(course_id: str) -> dict:
        snap = await svc.get_snapshot()
        mats = [m for m in snap.materials if m.course_id == course_id]
        return {"materials": [m.model_dump(mode="json") for m in mats]}

    @mcp.tool(description="Force a fresh Canvas pull (10-35s). Explicit user ask only.")
    async def sync_canvas() -> dict:
        snap = await svc.sync()
        return svc.sync_result(snap).model_dump(mode="json")

    @mcp.tool(description="Service health + last-sync age + sync-in-progress flag.")
    async def get_canvas_health() -> dict:
        return {"ok": svc.last_error is None,
                "backend": svc.backend.name,
                "last_sync": svc.last_sync().isoformat() if svc.last_sync() else None,
                "sync_in_progress": svc.sync_in_progress,
                "last_error": svc.last_error}

    return mcp
```

Then mount it on the existing app in `main.py`:

```python
# in create_app(), after app = FastAPI(...)
from .mcp_server import build_mcp
# svc is created in lifespan; mount the MCP after the service is available
# (FastMCP supports attaching to a FastAPI app via its ASGI sub-app)
mcp = build_mcp(app.state.service)        # wire inside lifespan startup
app.mount("/mcp", mcp.streamable_http_app())
```

Register auth on the MCP route too — same `X-Jarvis-Key` header dependency as the REST routes. Don't ship an open MCP on a public tunnel.

**Hermes side (Saswata handles this, not you — reference only):**

```yaml
# ~/.hermes/profiles/shruti/config.yaml
mcp_servers:
  canvas:
    url: ${PUBLIC_CANVAS_BASE}/mcp
    headers:
      X-Jarvis-Key: ${CANVAS_API_KEY}
    timeout: 30
```

After this, Hermes's tool registry auto-discovers tools as `mcp_canvas_get_daily_brief`, `mcp_canvas_get_todo_list`, etc. No custom-tools YAML block needed.

**Testing checklist (so you know it works before telling Saswata):**

1. `curl -X POST $BASE/mcp -H "X-Jarvis-Key: $KEY" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"0.0.1"}}}'` — should return a server-info response.
2. `curl -X POST $BASE/mcp ... -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'` — should return the 10 tool names above.
3. `curl -X POST $BASE/mcp ... -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_daily_brief","arguments":{"days":7}}}'` — should return the real brief.
4. Hitting `/mcp` without the `X-Jarvis-Key` header → 401, same as the REST side.
5. Existing REST tests still pass (`pytest`) — MCP is additive, REST stays untouched.

**Scope guardrails — what NOT to do:**

- Don't remove the REST endpoints. UI, tests, and existing integrations use them. MCP is additive.
- Don't expose `POST /sync` without auth on MCP either — it's expensive.
- Don't add new tools we haven't agreed on. The 10 tools above mirror the catalog in `context/saswata.md`. If you want to add one, ping Saswata first.
- Don't change the response shapes. MCP returns the same Pydantic-shaped JSON that REST does — Hermes handles both the same way.

**Priority:** between TODO 4 (materials — unblocks Amrita) and B/C (exam prep, grades). Materials is still higher priority because Amrita is blocked today; MCP conversion is a quality improvement, not a blocker.

### Non-goals — explicitly NOT asked

- No supermemory writes from your service. Brain owns that.
- No streaming responses. Cached calls are 20ms.
- No per-user auth.
- No Canvas writes.

### Orchestrator's tool catalog pointing at your service (reference, don't implement this — Saswata does)

| Tool name (brain) | Endpoint (you) | TODO# |
|---|---|---|
| `get_todo_list(days)` | `GET /items/next?days=` | existing |
| `get_daily_brief(days)` | `GET /brief?days=` | **TODO 1** |
| `get_item_details(item_id)` | `GET /items/{item_id}` | **TODO 2** |
| `get_course_items(course_id, include_done)` | `GET /items?course_id=` | existing |
| `list_courses()` | `GET /courses` | existing |
| `get_course_materials(course_id, topic_hint?, this_week?)` | `GET /materials?course_id=` | **TODO 4** done |
| `get_material_text(material_id, offset?, max_chars?)` | `GET /materials/{id}/text` | **new** (TODO 4) |
| `sync_canvas()` | `POST /sync` | existing |
| `get_canvas_health()` | `GET /health` | existing |
| `mark_item_done_locally(item_id)` | `POST /items/{item_id}/user-done` | **TODO 3** |

Ping Saswata when TODOs 1-3 + 5 land; that unblocks the orchestrator's first voice end-to-end. TODO 4 unblocks Amrita separately.

## Abishek's TODO list (in order) — mark `[x]` when done

### [x] A. Course materials (= Saswata's TODO 4) — DONE
- Modules first (work even with a hidden Files tab), Files tab extra, syllabus + PDFs linked from it.
- Text on demand + pre-fetch this/next week + syllabus; 25 MB cap; archives/images skipped.
- `topic_hint` + `this_week` filters; MCP + REST.
- Later, if time: pptx/docx text; guess the "current module" for courses without dates in module names (CSE 507/579).

### [ ] B. Exam prep
- Syllabus text (+ syllabus PDFs) is now available via materials — use it as a source alongside announcements.
- Pull announcements (`/api/v1/announcements?context_codes[]=course_:id`) + syllabus body for current courses.
- Gemini extracts **exam date + topics** from that text ("Midterm 2 next Thursday covers AVL trees and heaps") → `exam` items with `due_at`, `topics`, `suggested_action: exam_prep`, `source_url` = the announcement.
- Exams must show in `/brief` and `/items/next`; the brain routes them to Amrita's quiz engine.

### [ ] C. Grades
- Submission scores per assignment (`/api/v1/courses/:id/students/submissions?student_ids[]=self` or planner `submissions`) → e.g. "HW4 → 9/10".
- New endpoint (e.g. `GET /grades?course_id=`) for Saswata's supermemory demo + Daily Pulse "past grade on similar" lane. The brain writes the facts to supermemory, not this service.

### [ ] D. Stress test
- Repeated `/sync` and many parallel reads; stale-cache background refresh under load.
- Expired Canvas login (→ `503`), Gemini down / slow (→ rules only), TinyFish slow / down (→ stale snapshot served).
- Empty weeks, courses with no items, items without due dates, very long instructions.
- Public tunnel restart → new URL → update `shared.env`.

### Done
- [x] Real Canvas via TinyFish (JSON in the logged-in browser), to-do list without submitted work, Gemini steps/topics/notes.
- [x] Saswata's TODOs 1, 2, 3, 5: `/brief`, `/items/{id}`, user-done + undo, public tunnel + `X-Jarvis-Key`.
- [x] Background refresh (reads never block). Optional later: live sync progress for the UI.
- [x] Course materials (TODO 4) + MCP server at `/mcp` (Saswata's TODO 6).

## Open questions

- TinyFish sponsor table: is using a profile *setup session* as the sync browser OK long-term? Any hackathon credits?
- How long does an ASU Canvas login last before Duo is needed again? (re-sign in the morning of the demo)
