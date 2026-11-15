# Abishek — context + notes

Owner: Abishek (GitHub: Abishek1801)
Role: **Browser agent — real Canvas data via TinyFish, item classification, and the to-do list**
Code: `apps/browser-agent/` (FastAPI, port **9001** from `shared.env`) — merged to `main`.

## Status (Nov 14, evening)

- ✅ **Working on real ASU Canvas.** One sync ≈ 7 s for Canvas + ≈ 5–25 s for Gemini. Answers are instant from cache.
- ✅ **To-do list = only work not submitted yet.** Submitted / excused / marked-complete items never appear (hard rule).
- ✅ **Gemini** writes "what to do" steps, topics and notes for each open item.
- ⏳ **Not built yet:** course materials (PDFs for Amrita), exam dates from announcements, grades, sync progress.
- There is **no Canvas API token** for ASU accounts. All Canvas data comes through a TinyFish browser that is logged in as the student.

## Decisions (locked)

1. **TinyFish** provides the logged-in browser. We do **not** use TinyFish's AI agent (TinyAgent) for Canvas — tested: 1–2 min per page, text dates, and TinyFish's safety check blocked reading Canvas JSON. Instead our code reads Canvas's own JSON inside the TinyFish browser: ~7 s, exact dates, exact submitted flags.
2. **Separate HTTP service.** The orchestrator calls it over HTTP. No shared Python imports.
3. **Only the orchestrator writes to supermemory.** The browser agent just returns data.
4. **Classification is explainable:** every item has `classified_by` + `reason`, and the to-do filter is a hard rule the LLM cannot override.
5. **Read-only:** only GET requests to Canvas. Never submits, posts, clicks or starts a quiz.
6. **LLM = Gemini** (`gemini-3.5-flash`, falls back to `gemini-3.5-flash-lite`). Without a key the service still works with rules only.
7. **Plan B (local Chrome + AgentQL) dropped.** If ever needed, the same JSON code can point Playwright at a local Chrome instead.

## The flow — one sync, step by step

```
Orchestrator (Saswata) ──HTTP──> apps/browser-agent :9001
                                   │
   GET /items/next ── snapshot fresh (< 30 min)? ── yes ──> answer instantly
                                   │ no / POST /sync
                                   ▼
 1. TinyFish: open a cloud browser from the saved Browser Context Profile
    ("Jarvis - ASU Canvas", already logged in — Duo was done once, by hand)        ~1 s
 2. Playwright connects to that browser (CDP)                                        ~0.5 s
 3. Read Canvas JSON with the browser's logged-in cookies (read-only):              ~2–5 s
      /api/v1/planner/items     → everything due, ALL courses, one call,
                                  incl. submitted / excused / marked-complete flags
      /api/v1/courses           → course names (current = has work due; ASU leaves term dates empty)
      /api/v1/courses/:id/assignments/:id → instructions, submission types, LockDown flag (parallel)
 4. Close the browser WITHOUT saving (the saved login is untouched)
 5. Gemini: ONE batched call with only the OPEN items (not submitted work,
    not office hours) → type check, steps, topics, notes                             ~5–25 s
 6. classify each item: rules → Gemini merge → hard to-do filter
 7. save data/canvas_snapshot.json → answer
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

| Method + path | Returns | Speed |
|---|---|---|
| `GET /items/next?days=7` | **the to-do list** `{synced_at, data_source, items: [Item]}`, soonest first | instant (syncs if stale) |
| `GET /items/next?days=7&include_done=true` | everything due incl. submitted work + events, each with `in_todo` + `todo_reason` | instant |
| `GET /items?course_id=` | `{synced_at, data_source, items: [Item]}` | instant |
| `GET /courses` | `{synced_at, data_source, courses: [{id, code, name, term}]}` | instant |
| `GET /materials?course_id=` | `{synced_at, data_source, materials: [...]}` — **empty for real Canvas (next step)** | instant |
| `POST /sync` | `{synced_at, backend, data_source, llm_used, llm_error, counts}` | 10–35 s |
| `GET /health` | `{ok, backend, llm, last_sync, last_error}` | instant |

Errors: `503 {"error":"canvas_login_expired","detail":...}` · `502 {"detail":...}` backend failure.
**Tip for the orchestrator:** don't block a voice turn on `POST /sync` (it can take ~30 s). Call `/items/next` (instant from cache) and trigger `/sync` in the background on app start / when the user says "sync".

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

### Demo data without keys
`BROWSER_BACKEND=mock` serves labeled fake courses (CSE 310, MAT 343). Static copy: `apps/browser-agent/mocks/canvas_snapshot.json`.

## What each file does (`apps/browser-agent/`)

| File | Responsibility |
|---|---|
| `app/main.py` | HTTP routes + error mapping (503 login expired, 502 failure). No logic. |
| `app/service.py` | One sync: `start_sync → courses → items → details (parallel) → end_sync → Gemini batch → classify → save`. Also cache-or-sync and the to-do query (`next_items`). |
| `app/backends/base.py` | Contract every backend follows + `CanvasLoginExpired`. |
| `app/backends/tinyfish.py` | Opens the TinyFish profile browser, connects Playwright, reads Canvas JSON, converts it to `RawItem`s, closes the browser. |
| `app/backends/mock.py` | Labeled demo data, no keys. |
| `app/classify.py` | Rules → Gemini merge → hard to-do filter → `Item`. |
| `app/llm.py` | Gemini classifier: one batched call, structured JSON output, model fallback, safe prompt. |
| `app/models.py` | All JSON shapes: `RawItem`, `Item`, `Course`, `Material`, `Snapshot`, `SyncResult`, `Health`. |
| `app/cache.py` | `data/canvas_snapshot.json` (gitignored) + freshness check. |
| `app/config.py` | Env settings (`.env`, see `.env.example`). |
| `app/materials.py` | PDF text extraction with `pypdf` — used by the course-materials step (next). |
| `scripts/export_mock.py` | Regenerates `mocks/canvas_snapshot.json`. |
| `tests/unit`, `tests/api`, `tests/fixtures` | 50 tests, no network: classifier, Canvas JSON conversion, Gemini parsing + fallback, every endpoint. |

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
- **Amrita (quiz):** materials (PDF text) are the next thing I build; until then use `mocks/canvas_snapshot.json` → `materials`.
- **Shruti (UI):** render `items` directly; every item has `source_url`, `due_at`, `notes`; show "syncing…" while `/sync` runs.

## TODO from Saswata (orchestrator) — unblocks voice demo

System design is locked (`context/saswata.md` → "System design — LOCKED"). Your service stays stateless; brain owns supermemory. Four endpoint-level todos + one infra todo. All in your existing cache / Snapshot shape, no architectural change.

Format: each item is a copy-pasteable instruction. Mark `[x]` when done.

### [ ] TODO 1 — add `GET /brief?days=7` endpoint (highest priority, ~15 min)

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

### [ ] TODO 2 — add `GET /items/{item_id}` endpoint (~5 min)

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

### [ ] TODO 3 — add `POST /items/{item_id}/user-done` endpoint (~20 min)

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

### [ ] TODO 4 — materials pipeline (reinforces your existing Next Steps #1)

Already your top priority. Minimal first cut unblocks Amrita even without PDF extraction:

- `TinyFishBackend.fetch_materials(course)` reads `/api/v1/courses/{id}/files` + `/api/v1/courses/{id}/modules` (same JSON pattern as planner/items).
- Return `Material` with `id`, `course_id`, `title`, `type`, `url`.
- Text extraction (your step 1's `pypdf` pass) can land in a second commit — Amrita can validate her embedding pipeline off URLs first.

### [ ] TODO 5 — expose your service over Cloudflare tunnel

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
| `get_course_materials(course_id, topic_hint?)` | `GET /materials?course_id=` | **TODO 4** fills body |
| `sync_canvas()` | `POST /sync` | existing |
| `get_canvas_health()` | `GET /health` | existing |
| `mark_item_done_locally(item_id)` | `POST /items/{item_id}/user-done` | **TODO 3** |

Ping Saswata when TODOs 1-3 + 5 land; that unblocks the orchestrator's first voice end-to-end. TODO 4 unblocks Amrita separately.

## Next steps (in order)

1. **Course materials** — `/api/v1/courses/:id/files` + modules → download PDFs → `pypdf` text → `/materials` (unblocks Amrita).
2. **Exam prep** — read announcements/syllabus, Gemini extracts exam **date + topics** → `exam` items with `exam_prep`.
3. **Grades** — submission scores ("HW4 → 9/10") for Saswata's supermemory demo and the Daily Pulse "past grade on similar" lane.
4. **Sync progress / background sync** for the UI + orchestrator.
5. **Stress test** — repeated syncs, expired login, Gemini down, TinyFish slow, empty weeks.

## Open questions

- TinyFish sponsor table: is using a profile *setup session* as the sync browser OK long-term? Any hackathon credits?
- How long does an ASU Canvas login last before Duo is needed again? (re-sign in the morning of the demo)
