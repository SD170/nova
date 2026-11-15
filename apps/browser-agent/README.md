# apps/browser-agent

Reads the student's real Canvas (there is no Canvas API token) through a TinyFish browser that is already logged in, classifies every item, builds the **to-do list** (only work that is not submitted yet), and serves it to the orchestrator over HTTP on **port 9001**.
Full design + contract for teammates: `context/abishek.md`.

## Owner

Abishek (GitHub: Abishek1801)

## Run locally

```bash
cd apps/browser-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # BROWSER_BACKEND=mock works with no keys (labeled demo data)
uvicorn app.main:app --port 9001 --reload
```
Open http://localhost:9001/docs → `POST /sync` → `GET /items/next`.

**Real Canvas:** in `.env` set `BROWSER_BACKEND=tinyfish`, `TINYFISH_API_KEY`, `TINYFISH_PROFILE_ID`, and `GEMINI_API_KEY` (optional, for steps/notes).

**One-time Canvas login** (or when the API says `canvas_login_expired`):
`tinyfish profile sign-in <TINYFISH_PROFILE_ID>` → open the link → sign in to Canvas (ASU SSO + Duo) → save.

**Tests:** `pytest` (no network; 64 tests).
**Demo mock for teammates:** `python -m scripts.export_mock` → `mocks/canvas_snapshot.json`.

## How one sync works

```
1. TinyFish opens a cloud browser from the saved profile (already logged into Canvas)   ~1 s
2. Playwright connects to it over CDP                                                   ~0.5 s
3. Canvas JSON with the logged-in cookies (READ-ONLY GETs):                             ~2–5 s
     /api/v1/planner/items   everything due, all courses, one call (+ submitted flags)
     /api/v1/courses         course names
     /api/v1/courses/:id/assignments/:id   instructions + submission types (parallel)
4. Browser closed without saving (saved login untouched)
5. Gemini: ONE batched call for the open items → steps, topics, notes          ~5–25 s
6. Rules + hard to-do filter → data/canvas_snapshot.json
```
Reads never wait on Canvas: fresh snapshot → instant; stale → instant with the old data while a background refresh runs; only the very first call waits for one sync.

## Classification (3 layers)

1. **Rules** from Canvas's own data: quiz / assignment / discussion / calendar event. Exam keywords (`midterm`, `exam`, `final exam`) in titles, never in announcements.
2. **Gemini** (if `GEMINI_API_KEY` is set): decides items the rules can't, upgrades a quiz/assignment to `exam` when the text says so, writes `what_to_do`, `topics`, `notes`. Ignored below `LLM_CONFIDENCE_THRESHOLD`. Tries `GEMINI_MODEL`, then `GEMINI_FALLBACK_MODELS`; if all fail, rules only (`llm_used=false`, `llm_error` says why).
3. **To-do filter (hard rule, the LLM cannot override it):** submitted / excused / marked complete in Canvas → `in_todo=false`. Only assignment / quiz / exam / discussion can be in the to-do list.

## Endpoints (port 9001)

Auth: if `CANVAS_API_KEY` is set, send header `X-Canvas-Key` on every endpoint except `/health` and `/docs`.

| Method + path | Returns |
|---|---|
| `GET /health` | `{ok, backend, llm, last_sync, sync_in_progress, last_error}` |
| `GET /brief?days=7` | to-do list + current courses + `last_sync_age_minutes` + `sync_in_progress` (one call for "good morning") |
| `GET /items/{item_id}` | one item's full details |
| `POST /items/{item_id}/user-done` / `DELETE` | student says "I did it" (kept until Canvas catches up or due date passes) / undo |
| `POST /sync` | `{synced_at, backend, data_source, llm_used, llm_error, counts}` |
| `GET /items/next?days=7` | **to-do list** `{synced_at, data_source, items: [Item]}` — not submitted, soonest first |
| `GET /items/next?days=7&include_done=true` | everything due (submitted work + events too) with `in_todo` + `todo_reason` |
| `GET /items?course_id=` | all items of a course |
| `GET /courses` | `{synced_at, data_source, courses: [{id, code, name, term}]}` |
| `GET /materials?course_id=&topic_hint=&this_week=` | study materials list (syllabus, PDFs, Canvas pages, links) with module + week dates + `text_status`; no text |
| `GET /materials/{id}/text?offset=&max_chars=` | plain text of one material (`[page N]` markers), cached after first call; long docs in slices via `next_offset` |
| `POST /mcp` (MCP streamable-HTTP) | same 11 tools for Hermes / any MCP client; same `X-Canvas-Key` **MCP answers are voice-sized:** each tool returns a one-line `speak` plus compact data (short course codes, short titles, spoken due times; see `app/voice.py`). REST endpoints keep the full data. |

Errors: `401` wrong/missing key · `404 item_not_found` / `material_not_found` · `422 material_text_unavailable` · `503 {"error": "canvas_login_expired"}` → sign in again · `502` → backend failure (see `detail`).

## Env vars (see `.env.example`; secrets in `.env`, gitignored)

| Var | Default | Meaning |
|---|---|---|
| `CANVAS_API_KEY` | empty | Shared secret for `X-Canvas-Key` (set it before going public) |
| `BROWSER_BACKEND` | `mock` | `mock` (labeled demo data) / `tinyfish` (real Canvas) |
| `CACHE_TTL_MINUTES` | `30` | How long a snapshot counts as fresh |
| `SYNC_DAYS` / `SYNC_PAST_DAYS` | `14` / `0` | Window of items fetched |
| `CANVAS_COURSE_IDS` | empty | Optional comma-separated course ids; empty = courses with work due |
| `CLASSIFIER_LLM_ENABLED` | `true` | Use Gemini (only if `GEMINI_API_KEY` is set) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-3.5-flash` | Classification LLM |
| `GEMINI_FALLBACK_MODELS` / `GEMINI_TIMEOUT_SECONDS` | `gemini-3.5-flash-lite` / `30` | Tried in order if the main model is slow or busy |
| `LLM_CONFIDENCE_THRESHOLD` | `0.7` | Below this the LLM result is ignored |
| `TINYFISH_API_KEY` / `TINYFISH_BASE_URL` / `TINYFISH_PROFILE_ID` | — | TinyFish browser signed into Canvas |
| `MATERIALS_MAX_MB` | `25` | Files bigger than this are listed as `too_large` (no download) |
| `MATERIALS_PREFETCH_DAYS` / `_LIMIT` / `_SECONDS` | `7` / `12` / `60` | Each sync pre-extracts syllabus + modules dated today..+N days, max N per course, time-boxed |

## Code map

```
app/
  main.py               HTTP routes + error mapping only
  service.py            one sync: start → fetch → details → Gemini → classify → overrides → save; reads, brief, user-done
  overrides.py          student "I did it" overrides (data/user_overrides.json)
  classify.py           rules → LLM merge → hard to-do filter
  llm.py                Gemini batched classifier (structured JSON, model fallback)
  models.py             all JSON shapes (RawItem, Item, Course, Material, Snapshot, ...)
  cache.py              data/canvas_snapshot.json + freshness
  config.py             env settings
  materials.py          Canvas modules/files/syllabus → Material list, week dates, prefetch pick, PDF → text, text cache
  mcp_server.py         MCP tools at /mcp (same service) + X-Canvas-Key guard
  backends/
    base.py             backend contract + CanvasLoginExpired
    tinyfish.py         real Canvas via TinyFish browser + Canvas JSON
    mock.py             labeled demo data (no keys)
scripts/export_mock.py  regenerate mocks/canvas_snapshot.json
mocks/                  demo snapshot for teammates
tests/
  unit/                 classifier, Canvas JSON conversion, Gemini parsing/fallback
  api/                  every endpoint + MCP on the mock backend
  fixtures/             classify_cases.json (labeled examples)
```

## Public URL (Cloudflare quick tunnel)

```bash
uvicorn app.main:app --port 9001                                   # terminal 1
cloudflared tunnel --no-autoupdate --url http://localhost:9001      # terminal 2 → prints https://xxx.trycloudflare.com
```
Put the URL in repo-root `shared.env` as `PUBLIC_CANVAS_BASE` (it changes every restart). Always set `CANVAS_API_KEY` first.

## Status

Done: real Canvas via TinyFish, to-do list without submitted work, Gemini steps/notes/topics, /brief, /items/{id}, user-done overrides, background refresh, shared-secret auth, public tunnel, course materials (list + text), MCP at /mcp.
Next: exam prep (exam dates from announcements), grades for the Daily Pulse, stress test.
