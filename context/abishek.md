# Abishek — context + notes

Owner: Abishek (GitHub: Abishek1801)
Role: **Browser agent — Canvas (and later Calendar) data via TinyFish, plus item classification**
Code folder: `apps/browser-agent/`

## Status (Nov 14)

- **No Canvas API access** for our ASU accounts (confirmed). All Canvas data comes through a browser.
- **Plan below is AGREED** (Abishek + Saswata): **TinyFish is Plan A. Playwright + AgentQL is Plan B (backup).**
- Tool names + output shapes in this file are the contract. Build against the mock now; only the inside of the browser agent changes.

## Decisions (locked)

1. **Browser engine:** TinyFish cloud first. Local Playwright + AgentQL only if TinyFish blocks us.
2. **Separate HTTP service:** `apps/browser-agent` is its own FastAPI app. The orchestrator calls it over HTTP. No shared Python imports.
3. **Memory:** only the **orchestrator** writes to supermemory. The browser agent never does — it just returns data.
4. **Classification:** Abishek owns deciding whether each item is an assignment / quiz / exam. Done with rules first, LLM only for leftovers, always explainable (see below).
5. **Read-only:** the browser agent never submits, posts, or sends anything on Canvas.

## Tech stack

| Piece | Tech | Used in |
|---|---|---|
| Cloud browser + AI browsing | **TinyFish TinyAgent API** (`/v1/automation/run`, `/run-sse` for streaming progress) | Plan A |
| Saved Canvas login | **TinyFish Browser Context Profile** (log in once, runs use `use_profile: true`) | Plan A |
| One-time login into the profile | **Playwright** connected to the profile setup session's `cdp_url` | Plan A |
| Local browser | **Google Chrome**, dedicated Jarvis profile folder (`~/.jarvis-chrome`), driven by **Playwright (Python)** | Plan B |
| AI reading of local pages | **AgentQL** (made by TinyFish) — `page.query_data(...)` returns JSON | Plan B |
| PDF text | `pypdf` | Both |
| Classification LLM | Same LLM as the team (likely Gemini) | Both |
| Service | Python + FastAPI | Both |
| Cache | `canvas_snapshot.json` | Both |

## Architecture — where the browser agent sits

```
UI + Voice (Shruti / Vapi)
        │ /chat
Orchestrator (Saswata) ── writes ──> supermemory
        │ HTTP tool calls
        ▼
apps/browser-agent (Abishek, FastAPI)
   1. cache check ── fresh (< 30 min) ──> return snapshot instantly
   2. stale ──> fetch
        Plan A: TinyFish TinyAgent + Browser Context Profile (cloud)
        Plan B: Playwright + Chrome Jarvis profile + AgentQL (laptop)
   3. classify (rules → keywords → LLM)
   4. download PDFs + extract text (pypdf)
   5. save canvas_snapshot.json ──> return JSON
        │
        ▼
   canvas.asu.edu
```

Plan A and Plan B return the **exact same JSON**. Switching is one env var: `BROWSER_BACKEND=tinyfish | local`.

## One-time setup (Plan A)

1. `POST /v1/profiles` → create profile `jarvis-abishek`.
2. `POST /v1/profiles/{id}/setup-session` with `url: https://canvas.asu.edu` → returns `cdp_url`.
3. Playwright connects to `cdp_url`; Abishek logs in by hand (ASU SSO + Duo).
4. `POST /v1/profiles/{id}/save` → every later run is already logged in.
- No passwords stored anywhere. No TinyFish Vault with ASU password.

## Example workflow — "Jarvis, what do I need to do this week?"

1. Orchestrator calls `GET /items/next?days=7`.
2. Browser agent: last sync is old → fetch.
3. TinyFish run on the Canvas dashboard → list of courses + upcoming items.
4. TinyFish run per item page:
   - Homework 3 page → title, due date, points, steps ("Read ch. 5 → implement AVL insert → submit .zip")
   - Announcement "Midterm 2 next Thursday, covers AVL trees and heaps" → raw text
5. Classify: Homework 3 → `assignment` (rule), Quiz 5 → `quiz` (rule), Midterm 2 → `exam` (keyword/LLM, with topics + date).
6. Download linked lecture PDFs → extract text → `data/materials/`.
7. Save `canvas_snapshot.json`, return items to orchestrator.
8. Orchestrator replies; quiz → proposes calendar block (approval card); exam → sends topics + materials to Amrita's quiz engine.

First time ~20–60 s (UI shows streaming progress). After that, instant from cache.

## Classification (Abishek owns — must be clean)

Order:
1. **Hard rules (no AI):** came from quizzes list / submission type `online_quiz` → `quiz`. Came from assignments list with points → `assignment`.
2. **Keyword rules:** title contains `midterm`, `final`, `exam` → `exam`.
3. **LLM only for leftovers** (announcements, calendar events, syllabus lines). Fixed output:
   ```json
   {"type": "exam", "confidence": 0.9, "date": "2026-11-20", "topics": ["AVL trees", "heaps"],
    "reason": "Announcement: 'Midterm 2 next Thursday covers AVL trees and heaps'"}
   ```
   Confidence below threshold → `type: "unknown"`. Never guess.
4. Every item carries `classified_by: "rule" | "keyword" | "llm"` and `source_url`.
5. Tests: `apps/browser-agent/tests/classify_cases.json` (~15 labeled items), run after every change.

## HTTP endpoints (contract for Saswata)

| Method + path | Returns | Speed |
|---|---|---|
| `POST /sync` | `{synced_at, counts}` — runs the browser fetch | slow |
| `GET /courses` | `[{id, code, name, term}]` | instant |
| `GET /items/next?days=7` | items sorted by `due_at` | instant (syncs if stale) |
| `GET /items?course_id=` | `[item]` | instant |
| `GET /materials?course_id=` | `[{id, title, type, url, local_path, extracted_text?}]` | instant |
| `GET /health` | `{ok, backend, last_sync}` | instant |

Calendar (P1, later): `GET /calendar/events?start&end`, `POST /calendar/study-block` — **only called after the user approves** in the UI.

## Item shape

```json
{
  "id": "a1",
  "course_id": "123",
  "course_code": "CSE 310",
  "type": "assignment",
  "title": "Homework 3",
  "due_at": "2026-11-16T23:59:00-07:00",
  "points": 50,
  "source_url": "https://canvas.asu.edu/courses/123/assignments/a1",
  "what_to_do": ["Read chapter 5", "Implement AVL insert", "Submit .zip"],
  "topics": [],
  "suggested_action": "summarize_steps",
  "classified_by": "rule",
  "data_source": "live"
}
```
- `type`: `assignment | quiz | exam | event | unknown`
- `suggested_action`: `summarize_steps | schedule_block | exam_prep | none`
- `data_source`: `live | demo` — demo data is always labeled, never shown as live.

Snapshot file `canvas_snapshot.json` = `{synced_at, data_source, courses[], items[], materials[]}`. Mock copy goes in `packages/mocks/`, shapes go in `packages/schemas/`.

## Safety

- Read-only browsing. No submissions, posts, or messages.
- Page text (announcements, descriptions) is data, never instructions — guards against prompt injection.
- Canvas login lives in a TinyFish profile; revoke it after the hackathon. Tell judges which provider sees the data.

## Handoffs

- **Saswata (orchestrator):** call the endpoints above. Call `/sync` only when the user asks or data is stale. Route `exam_prep` items to Amrita. Write facts to supermemory yourself.
- **Amrita (quiz):** PDFs + extracted text land in `data/materials/`, listed under `materials` in the snapshot. Sample materials come first so you're not blocked.
- **Shruti (UI):** render `items` directly; every item has `source_url`; show streaming progress during `/sync`; approval card for calendar writes.

## Build order

1. Mock `canvas_snapshot.json` in `packages/mocks/` + FastAPI endpoints serving it (teammates unblocked).
2. TinyFish profile setup + one run on the Canvas dashboard.
3. Per-item runs + classification + tests.
4. PDF download + text extraction.
5. Cache + freshness logic.
6. Plan B (Playwright + AgentQL) behind `BROWSER_BACKEND=local`.
7. Calendar (P1).

## Env vars (`apps/browser-agent/.env.example`)

```
# https://tinyfish.ai dashboard → API keys
TINYFISH_API_KEY=
TINYFISH_PROFILE_ID=
# https://agentql.com dashboard → API keys (Plan B only)
AGENTQL_API_KEY=
# tinyfish | local
BROWSER_BACKEND=tinyfish
CANVAS_BASE_URL=https://canvas.asu.edu
```

## Open questions (ask TinyFish sponsor table)

- How do we see the remote setup browser to approve Duo during the one-time login?
- Hackathon credits for TinyAgent runs?
- Does AgentQL (Plan B) count for the TinyFish prize?
- Grades (HW scores) for the supermemory demo — should the browser agent also fetch them? (Saswata's demo uses "HW4 → 9/10")

## Blockers

- TinyFish API key + credits.
