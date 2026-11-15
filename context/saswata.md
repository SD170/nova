# Saswata — context + notes

Owner: Saswata Dutta (GitHub: SD170)

> **Context as of Nov 15, 06:45 local.** The earlier sections of this file are
> the plan / history (kept for grep). The LIVE STATE section at the bottom is
> the only part you need to re-read to catch up.

<!-- preserve full plan/history below; LIVE STATE appended at end -->

## Status — Nov 15, 00:30 local

**Brain is live.** Voice turns are going Vapi → Cloudflare tunnel → bridge → Hermes (Claude Haiku, in-repo profile) → voice.

- Main assistant: **Nova** (voice: Elliot; neutral confident). Vapi id: `f6bd0e01-6592-4ff9-98e8-4a90456441a9`
- Student-peer persona: **Shruti** (voice: Savannah; warm). Vapi id: `ca586ee1-e4e2-4148-a51b-f60d9737c00f`
- Transfer: Nova has a `transferCall` tool → Shruti, and vice versa. Say "talk to me as Shruti" / "back to Nova."
- Brain: `apps/brain/hermes-home/default/` (Hermes profile in the repo, NOT in `~/.hermes/`). Same brain serves both personas; persona injected per turn via `[persona: nova|shruti]` prefix.
- Public tunnel: `PUBLIC_BRAIN_BASE` in `shared.env` — quick tunnel, URL rotates on restart.
- No tool calls wired yet. Canvas (`apps/browser-agent`) still exposed on its own tunnel; adding its MCP into Hermes config is the next step.

## Architecture (what we're actually building)

```
User (voice / text)
    ↓
UI layer
    ↓
Voice loop  (STT ↔ TTS)
    ↓
Orchestrator / meta-agent  — spawns + coordinates sub-agents
    ↓
┌──────────────┬──────────────┬──────────────┬──────────────┐
Browser         Canvas         Calendar        OS-level
sub-agent       sub-agent      sub-agent       sub-agent
(scrape when    (API if        (OAuth, free/   (native app
 no API)         token works)   busy, writes)   access)
```

Design points:
- Orchestrator decides which sub-agent to spawn per turn
- Browser sub-agent is the fallback when services have no usable API (most of the time for student stuff)
- Approval gate sits between orchestrator and any external write (calendar create, email send, etc.)
- Everything grounded — quiz answers + Canvas claims carry source URLs / passages
- Memory layer runs across sessions: once the system knows you struggled with phase shifts last week, it does not re-explain, re-chunk, or re-ask

## Sponsor stack — which track each piece earns

| Layer / sub-agent | Sponsor prize | How it is native (not forced) |
|---|---|---|
| Memory (persistent per-student) | **supermemory** | Past assignments, weak topics, writing style preserved across sessions. Quiz skips strong areas, hits weak ones. Also powers context-pack sharing between teammates. |
| Browser sub-agent | **Tiny Fish** | Scrape Canvas when API is blocked, fetch assignment PDFs from external course sites, pull prof personal pages, RateMyProf, external references. Browser is Plan A for most services. |
| Long-context reasoning | **Gemini** | 2M-token context: ingest whole course corpus (syllabus + all slides + all assignments) per turn. Vision: scan handwritten notes / whiteboard photos → memory. |
| Vector store | **MongoDB Atlas** | Embeddings for course materials + per-user memory. Pairs with supermemory. |
| Orchestrator hosting | **Maritime** | Per-student agent VM. Nova keeps state across sessions, can run browser scrapes while you sleep (pre-fetch tomorrow's Canvas updates before your morning session). Literally their pitch. |
| Narrative / pitch | **JFFVentures (Future of Work)** | Future of learning + knowledge work. International-student angle sharpens it. |
| Compute / backup models | **AWS** (Bedrock) | One sub-agent on Bedrock, orchestrator on Lambda or ECS. |
| Primary hosting | **Vultr** | Main web app. Free credits, zero extra engineering, stacks alongside AWS. |
| Dev workflow (free raffle) | **MLH Cursor + Grok Bot** | Already coding in Cursor; add a Grok Bot to team Discord. 15 min of effort for a free raffle entry. |
| Activity analytics (if time) | **Tiger Data** | Time-series of study sessions, topic mastery over time, performance charts. P2. |
| Domain | **GoDaddy Registry** | Buy a .lol or similar for the demo. $12, trivial. |

**Realistic prize count: 5-8.** Best Overall is a stretch if the voice + orchestrator + browser demo lands.

Explicitly not chasing: MatLab (forced), Solana (forced), Hardware (no budget/time), Gaming (not primary — could gamify quizzes if slack), MLH niche tracks.

[NOTE added later: Solana IS in-scope now — see LIVE STATE blockchain section. The earlier "not chasing" is kept for history.]

## Work chunks (priority ordered, no names yet)

### P0 — must exist for the demo

1. **UI shell + card renderers**
   Push-to-talk button, chat view, 4 card types (assignment list, quiz question, approval prompt, weak-topic summary). Wired to a mock `/chat` endpoint so it can be built before backend exists.

2. **Voice loop**
   Mic capture → STT → text → feed to `/chat` → TTS response. Standalone module, can run before anything else works.

3. **Orchestrator / meta-agent**
   The `/chat` endpoint. Understands intent, spawns + coordinates sub-agents (browser, canvas, calendar, quiz), enforces approval gate for external writes, returns structured card responses. Start with a mock router, upgrade to real LLM tool-calling.

4. **Browser sub-agent**
   Browser automation for data behind services without an API. Logs into Canvas (or whatever), scrapes assignment list / course materials, returns clean JSON. Needs a library decision (browser-use / Playwright / TinyFish / Stagehand) up front.

5. **Retrieval + quiz engine**
   Ingest course materials (PDFs / slides / notes) → chunk + embed → store in vector DB. Generate grounded quiz questions with source citations. Grade answers, identify weak topics, suggest revision plan.

### P0.5 — memory layer (Abishek's idea, supermemory-native, sponsor-critical)

6. **Persistent per-student memory**
   Every assignment done, every quiz taken, every weak topic identified → saved as atomic facts, not re-prompted. On next session:
   - System already knows what you struggled with
   - Quiz generator skips mastered topics, hits weak ones
   - Canvas re-ingest is incremental (only new material), not full re-chunk
   - Writing style + preferences persist (voice, tone of responses)

   Why this is bumped from P2 → P0.5: without it, our supermemory use is generic RAG. With it, judges see memory *as behavior*, not storage. This IS the supermemory demo moment.

### P1 — makes the demo impressive

7. **Canvas API path (if a token is available)**
   Real Canvas REST calls as a faster + more reliable alternative to browser scrape. Same tool contract as the browser sub-agent.

8. **Calendar sub-agent**
   Google Calendar OAuth, read free/busy, propose study blocks, create block (approval-gated).

9. **Approval gate UI**
   Preview card showing exactly what tool will be called with what arguments. Approve / Cancel buttons. "What will be sent to the LLM" transparency.

10. **Context pack export / import (team sharing — Abishek's idea #2)**
    Package a student's Nova context for a given course (embedded materials + weak-topic graph + prior quizzes + style prefs) as a portable artifact. Teammate imports → their Nova instantly knows the course structure + accumulated understanding.
    Scope for 20h: 10-minute version — serialize to JSON, drop-in-import endpoint, demo one hand-off on stage. Full product is post-hackathon.

### P2 — stretch / polish

11. **OS-level app access**
    AppleScript / accessibility bridge to native macOS apps (Reminders, Notes, Mail). Optional second integration surface.

12. **Second browser capability**
    e.g., scrape professor's personal course page when Canvas is missing material. Adds complexity for judges.

13. **Activity analytics (Tiger Data prize)**
    Time-series charts of study sessions, topic mastery over time. Cards in the UI. Only if someone has slack.

14. **Quiz gamification (Gaming prize, maybe)**
    XP, streaks, leaderboard across teammates. Only if slack. Not primary.

15. **Demo polish**
    Loading states, error toasts, graceful fallbacks, rehearsal, backup recorded video.

## Hour-0, done together (not assigned, decided as a group)

- Pick LLM provider + agent framework
- Pick voice stack (OpenAI Realtime vs STT + LLM + TTS pipeline)
- Pick browser-control library (browser-use / Playwright / TinyFish / Stagehand)
- Lock JSON schemas: `/chat` request/response, tool call shape, UI card types
- Decide Canvas path: API, browser, or both
- Stub mock responses for every tool so everyone can build in parallel from minute 1
- Decide memory schema (atomic facts shape) — needed by orchestrator + retrieval + supermemory together

## Interface contract draft (for orchestrator — lock in hour 0)

```json
POST /chat
{
  "session_id": "uuid",
  "message": "Nova, I have an exam Monday. Am I ready?",
  "voice": false
}

→
{
  "session_id": "uuid",
  "turn_id": "t_42",
  "status": "needs_approval" | "complete" | "streaming",
  "cards": [
    {"type": "assignment_list", "items": [...]},
    {"type": "quiz_question", "q": "...", "choices": [...]},
    {"type": "approval_request", "tool": "create_study_block", "preview": {...}}
  ],
  "speak": "Here are your 3 upcoming assignments..."
}
```

## supermemory — killer demo (the line we rehearse)

User: *"Nova, quiz me for Monday's exam."*

Nova: *"Skipping convolution — you got 9/10 on HW4 and the prof's email last Tuesday said it won't be on the exam. Phase shifts — you missed 3 of 4 in HW3 and your notes from Oct 12 said 'I don't get this' — starting here. Question 1..."*

Why this is **the** supermemory demo, not something else:

- One sentence in, dense magic out. User never pasted HW scores, prof email, or personal notes — the system was there alongside them for weeks.
- Four *different kinds* of atomic facts fused in one decision:
  - graded assignment memory (HW4 → 9/10)
  - inbox-ingested memory (prof email Tuesday)
  - prior quiz performance memory (HW3 → 3/4 missed)
  - personal note memory with sentiment (Oct 12 note "I don't get this")
- Memory *as behavior*, not storage. The agent didn't recall a fact — it changed what it did because of a fact. Judges feel the difference.

**Judge-killer Q we have to answer on stage:** *"How is this different from a system prompt with pasted notes?"*
Answer: atomic facts, not blobs. supermemory extracts "struggled with phase shifts" as a discrete, updatable, decayable fact — contradictions resolve ("got it right in Q4(b) yesterday → update confidence"). Prompt-pasting has no state evolution.

**Build requirement:** pre-seed the demo account with ~15 synthetic past sessions over "6 weeks" (HW scores, quiz attempts, a prof email, some notes with sentiment markers). Without the backstory, the magic doesn't exist.

Supporting memory moments to layer in if time:

- **Cross-assignment carryover** — "You wrote a great intro about dynamic programming in HW2. Reuse that framing here." The *voice* persists.
- **Fix-it-once rule** — first correction ("in this course we use Kleinberg, not Cormen") sticks forever.
- **Teammate hand-off (Abishek's idea #2)** — "Fork my Nova context for CSE 310 to Priya." Her Nova gets the course structure + accumulated class understanding, not your personal weak-topic map. Clearly different from sharing notes.

## Voice stack decision

**For the demo: Vapi.** Sub-500ms end-to-end, handles turn-taking + barge-in + pauses out of the box, 30 min to wire up. Our `/chat` endpoint stays identical — Vapi just wraps around it. Fallback if Vapi's free tier bites: OpenAI Whisper (STT) + OpenAI TTS pipeline, ~15 min glue.

**For a privacy-first / secure environment (post-hackathon or if a track asks for local-only):** VoiceStudio (github.com/debpalash/VoiceStudio). Fully local, open-source ElevenLabs alternative — voice cloning, TTS, STT, 646 languages, runs on-device. Great fit when student data cannot touch cloud voice APIs (FERPA-sensitive deployments, dorm wifi off, international-student PII concerns). Not picked for the live demo because:
- Latency on a laptop under demo load (orchestrator + UI + browser-use all running) is 1-3s per turn, voice demos die at >1s gaps
- AGPL-3.0 is viral — licensing concern if we ever host it commercially
- Needs model download + HTTP wrapping (~4-8h of setup we don't have)

Keep VoiceStudio in the pitch as the "and here's the local / private deployment story" slide. Judges + JFF investors like seeing a credible on-prem path even if the demo is cloud.

## Secrets convention (team rule — follow this for every app)

Three config tiers:

| File | Committed? | What goes in |
|---|---|---|
| `shared.env` (repo root) | **yes** | Non-secret shared values every service needs: assistant IDs, public URLs, port numbers. One source of truth — update here, teammates `git pull` + autosync picks it up. |
| `apps/<app>/.env.example` | **yes** | Template of env vars that service needs, with empty values + a comment pointing to where the real value is obtained. |
| `apps/<app>/.env` | **no** (gitignored) | Actual API keys, tokens, OAuth creds. Each teammate fills their own. Never commit. |

`.env.example` is committed so teammates know what to put in `.env`. Real `.env` files are excluded by root `.gitignore`.

Example for `apps/voice/.env.example`:
```
# Grab from https://dashboard.vapi.ai (Org Settings → API Keys)
VAPI_PRIVATE_KEY=
VAPI_PUBLIC_KEY=
```

Services read `shared.env` for the public-ish values (assistant IDs, tunnel URL, ports) and their local `.env` for secrets.

Rule for every PR: if you added a new env var, you updated `.env.example` (and `shared.env` if it's non-secret and shared) in the same commit.

## Repo folder layout (per-chunk, each person owns a folder)

Each P0 chunk gets its own folder under `apps/`. Keeps teammates from stepping on each other's code, makes diffs clean, makes it obvious what's done.

```
student-nova/
├── AGENTS.md
├── README.md
├── context/                     # shared team brain (md only, no code)
│   ├── 01-project-brief.md
│   ├── saswata.md
│   ├── abishek.md
│   ├── amrita.md
│   ├── shruti.md
│   └── gpt.pdf
├── apps/
│   ├── ui/                      # UI shell + card renderers + voice loop frontend
│   │   ├── README.md            # owner, run cmd, env vars
│   │   └── ...
│   ├── voice/                   # Vapi integration + STT/TTS glue
│   │   ├── README.md
│   │   └── ...
│   ├── orchestrator/            # /chat endpoint + tool router + approval gate + memory
│   │   ├── README.md
│   │   └── ...
│   ├── browser-agent/           # browser-use / Playwright / TinyFish — scrape Canvas + external
│   │   ├── README.md
│   │   └── ...
│   └── retrieval-quiz/          # embed + vector store + grounded quiz + grading
│       ├── README.md
│       └── ...
└── infra/                       # deploy configs (Vultr, Maritime, AWS) — added later
```

Shared JSON contracts (tool call shapes, /chat shape, card types) live in `context/` md, not a code folder. Keeps things lean for the 20h window.

### Rules

- Each `apps/<x>/` has a `README.md` with: owner, what it does, how to run locally, env vars, what endpoints it exposes
- Shared types live in `packages/schemas/` — one source of truth, everyone imports
- Mocks live in `packages/mocks/` and get wired up hour-1 so UI + orchestrator + voice can integrate before real tools exist
- Context folder stays *markdown only* — no code, no configs — it is the team brain
- Each app can use whatever language makes sense (UI in Next/React, orchestrator in Python/Node, browser-agent in Python because browser-use is Python) — they talk over HTTP

### Hour-0 step (I'll do): scaffold the folders + stub READMEs so teammates pull → each person sees their folder already created with a starter README.

## My ideas / open questions

### Daily Pulse — the "what I need to know when I wake up" brief

Student wakes up → single brief. Not a feed, not a dashboard. **One curated page** that answers: "what's on fire today, what should I actually work on, and what's about to hit my bank account."

#### Four lanes feeding one brief

```
                       ┌─────────────────────┐
  Canvas (browser) ───▶│                     │
  Gmail (read-only) ──▶│                     │
  Calendar ───────────▶│   Daily Pulse       │──▶  one page
  Interest feeds ─────▶│   synthesizer       │     (voice + web card)
  Bank (Plaid, P2) ───▶│                     │
                       └─────────────────────┘
                                 ▲
                                 │
                       supermemory — knows what
                       you cared about yesterday,
                       what's stale, what changed
```

#### Lane 1: academic (what I should work on today)
- Canvas: upcoming assignments, due dates, points weight, past grade on similar
- Supermemory signal: weak topics from past quizzes
- Priority algorithm: `urgency × weight × weakness_delta`
- Output: "work on HW3 Q4-6 (phase shifts, you missed these on HW3 Q2)"

#### Lane 2: interests (what I care about outside school)
- No Twitter API — fine. Alternatives:
  - **RSS feeds from the sites behind the tweets**: Nitter instances (unreliable), or go direct (TechCrunch, Hacker News, The Athletic for football, MAL/AniList for anime)
  - **Google News RSS** per topic (legit, no auth): `https://news.google.com/rss/search?q=<topic>`
  - **Reddit** per subreddit (free public JSON): `reddit.com/r/MachineLearning/.json`, `/r/soccer/.json`, `/r/anime/.json`
  - **Hacker News API** for AI/tech (free, official)
  - **YouTube RSS** per channel
  - **LessWrong / arxiv-sanity** for AI
- Supermemory learns which items I clicked / skipped → tunes next day's filter
- Output: 3-5 items max, in my voice ("The paper you were reading last week got cited in X.")

#### Lane 3: money (the one that keeps me up)
- **For the demo (and honestly the real pain):** use **Gmail read-only** as the money signal. Bank + ASU already send you everything:
  - ASU financial aid disbursement emails
  - Tuition / rent due reminders
  - Bank "you spent X" alerts (Chase, Discover, etc.)
  - CPT paycheck confirmations (Vapi Inc for you)
  - Visa / insurance renewal reminders
- Agent scans the inbox daily via Gmail API (OAuth read-only scope), extracts money events, flags "rent due in 5 days, balance low based on last Chase alert."
- **Plaid** is available later (free dev tier, 100+ US banks, read-only transaction sync) if we want real balances post-hackathon. Not in demo scope.
- Output: "Heads up: tuition payment plan second installment hits Dec 3rd ($2,850). You have 2 Vapi paychecks before then — you're fine."

#### Lane 4: logistics (the glue)
- Calendar: today's blocks, free slots
- Reminders: anything on your Apple Reminders / Google Tasks list
- Weather / commute (nice-to-have)

#### Why this is right for us

**Hits sponsor stack 5+ ways:**
- supermemory — the *whole point* is persistent context across days, filtering by what you care about
- TinyFish — Canvas scrape + any site that resists RSS
- Gemini — long-context synthesis of a day's worth of signals into one voice reply
- MongoDB Atlas — vector memory over your interest profile
- Maritime — the agent runs *overnight* on their VM, prepares the brief before you wake up
- JFF — future-of-work is literally "AI prepares your morning so you start sharp"

**Judging criteria it wins on:**
- Originality: student-specific, money + academics + interests fused. None of the agent-hackathon winners did this.
- Complexity: four heterogeneous data sources + synthesis + voice + memory layer
- Functionality: demoable with a single "good morning" voice prompt
- Design: one beautiful page = visual judge candy

#### Pitfall discipline (what we're NOT building)

- Not a news aggregator. No infinite scroll. 5 items max per category, curated.
- Not a budget app. No charts, no categorization UI. Just inbox-mining + "heads up about X."
- Not a to-do list. We surface Canvas + email tasks; we don't ask the student to add items.
- Not realtime. Briefs are generated once overnight (supermemory + Maritime), updated on demand when they ask.

#### Data sources ranked by hackathon-feasibility

| Source | Access | Cost | Fit |
|---|---|---|---|
| Canvas (browser scrape) | ✅ Abishek is on this | $0 | P0 |
| Gmail (OAuth read-only) | Google APIs, 5-min setup | $0 | P0 for money + ASU emails |
| Reddit JSON | Public, no auth | $0 | P1 |
| Google News RSS | Public, no auth | $0 | P1 |
| Hacker News API | Public, official | $0 | P1 |
| YouTube RSS per channel | Public, no auth | $0 | P1 |
| Google Calendar | OAuth, same Google flow as Gmail | $0 | P1 |
| arXiv / HN cross-ref | APIs free | $0 | P2 |
| Plaid (real bank) | Free dev tier, 2-day setup | $0 | **P2 — for post-hackathon pitch only** |
| Apple Reminders | osascript bridge local | $0 | P2 |

#### The demo moment

Judge hits a button. Voice:
> *"Good morning. You've got CSE 310 at 1:30, and HW3 is due tonight — you nailed convolution in HW4 so I lined up the 4 problems on phase shifts, that's where you dropped points last time. Nothing urgent in Gmail, but ASU's second tuition installment hits Dec 3rd, $2,850 — you have two Vapi paychecks before then, you're clear. In your world: that DeepSeek paper you starred Tuesday has a follow-up on the front page of HN right now, and Arsenal pulled off a 3-2 from behind against City last night. Want me to pin the HN thread?"*

That's the demo. One prompt, one reply, every lane shows up, memory visible everywhere.

### Open questions

- Who owns Gmail integration? Not Abishek (he's on Canvas-via-browser). Maybe Amrita if her LinkedIn stuff lands early.
- Push Plaid to post-hackathon or build a 10-min mock bank-balance tile for the demo?
- How does "one page" render — in Shruti's web UI as a card, or do we spin a dedicated `/morning` route?

### Decisions I'm making

### System design — LOCKED (Nov 14, late)

**One brain, many eyes.** Hermes is the brain. Vapi is ears + mouth. Sub-agents are dumb HTTP services. supermemory holds the user state, and only the brain writes to it.

```
┌──────────────── live voice path (latency-critical) ─────────────────┐
│                                                                     │
│   Vapi (STT + TTS)                                                  │
│       ↕ OpenAI /v1/chat/completions                                 │
│   Orchestrator wrapper (~100 LOC FastAPI, apps/orchestrator/)       │
│       ↕ translates to Hermes session                                │
│   Hermes "shruti" profile (THE BRAIN)                               │
│       ├─ system prompt (identity + rules + memory policy, static)   │
│       ├─ tool registry (dynamic, see catalogs below):               │
│       │    canvas_*       → HTTP :9001 (Abishek)                    │
│       │    materials_*    → HTTP :9003 (Amrita retrieval+quiz)      │
│       │    news_*         → HTTP :9004 (Amrita interests)           │
│       │    gmail_*        → HTTP :9005 (money + ASU emails, later)  │
│       │    calendar_*     → HTTP :9006 (free/busy + blocks, later)  │
│       │    hermes-native: memory, delegate_task, cron, terminal     │
│       └─ supermemory MCP (sole writer of user state)                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────── background (latency relaxed) ──────────────────────┐
│                                                                     │
│   Hermes cron (Daily Pulse @ 6am) — same brain, longer budget       │
│   Hermes delegate_task — fork sub-agents for heavy parallel work    │
│   Discord/Slack bot surface — same brain again                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Why this shape:**
- Hermes is the brain, not a router. It reasons, delegates, approves, remembers.
- Sub-agents stay stateless. Fresh data every call. Fault-isolated. Teammates own one folder each.
- supermemory is the only state. One writer (brain), avoids cross-service race conditions.
- Same brain powers live voice AND the 6am cron brief. Consistent reasoning.

### supermemory rules — LOCKED

1. **Only the orchestrator (Hermes brain) writes to supermemory.** No sub-agent writes.
2. **Sub-agents are stateless.** Every HTTP call returns fresh data from its source. In-service caching is allowed (Abishek's snapshot cache is CACHE, not memory).
3. **The brain reads supermemory at the top of every turn** (via Hermes memory + supermemory MCP) and uses it to decide what to ask sub-agents.
4. **The brain writes supermemory at the end of a turn** when something changed: new weak topic, new star/skip, intent shift, cross-session fact, user override of a classifier.
5. **Shared spaces are a brain operation.** Sharing an item ("share this news with Priya") = brain creates a shared supermemory entry both users read. The share tool does not copy data between accounts; it authorizes a slice.
6. **Classifier opinions ≠ user memory.** Abishek's Gemini says "this is an exam with confidence 0.82" — that lives in the item payload, not supermemory. Supermemory gets facts about the *student*, not facts about the *data*.

### Communication style — LOCKED (updated)

- **MCP (streamable-HTTP) for sub-agents, when they ship it.** Native Hermes MCP client auto-discovers tools (`mcp_canvas_*`, etc.). No hand-rolled custom-tools block in the Shruti profile.
- **HTTP fallback allowed during transition.** Abishek's service shipped REST first; MCP is TODO 6. Until MCP lands, Hermes talks to the REST endpoints via a custom-tools block.
- Decision reversal from earlier draft: cleaner Hermes config + standard discovery wins over the "HTTP-only, no protocol overhead" instinct. Same latency either way.
- **Hermes tool registry still maps semantic names → service tools.** LLM picks tools by intent, Hermes dispatches (via MCP or custom-HTTP as appropriate).
- **One intent = one tool call.** The brain never composes a tool call out of browser primitives. If a common prompt needs two sub-agents, add a bundled endpoint on the sub-agent side (see `/brief` for Abishek).

### Canvas tool catalog — the brain's view of Abishek's service (9 tools)

```
# Tier 1 — hot path (brain picks these 90% of the time)
get_todo_list(days=7)                   → GET /items/next?days=7
get_daily_brief(days=7)                 → GET /brief?days=7       (NEW — ask Abishek)

# Tier 2 — drill-down
get_item_details(item_id)               → GET /items/{id}         (NEW — ask Abishek)
get_course_items(course_id, include_done=True)  → GET /items?course_id=X
list_courses()                          → GET /courses

# Tier 3 — materials (for Amrita)
get_course_materials(course_id, topic_hint?)    → GET /materials?course_id=X
                                                  (currently stub, needs priority)

# Tier 4 — slow / rarely called
sync_canvas()                           → POST /sync              (10-35s; brain warns user first)
get_canvas_health()                     → GET /health

# Tier 5 — student override
mark_item_done_locally(item_id)         → POST /items/{id}/user-done  (NEW — ask Abishek)
                                           ALSO writes a fact to supermemory
```

System-prompt policy (what the brain is told about these):
```
For "what's due", "work on"               → get_todo_list
For "morning brief", status               → get_daily_brief
For "tell me about X"                     → get_item_details
For "how am I doing in COURSE"            → get_course_items
For "what classes"                        → list_courses
For "show me slides/materials"            → get_course_materials
For "refresh Canvas now" (explicit)       → sync_canvas (warn user, 20s)
For student override ("I did HW3")        → mark_item_done_locally, then confirm verbally
Default: prefer cached tools. Never call sync_canvas mid-conversation.
```

### News / sharing — where curation lives

**Curation happens in the brain, not in the news service.** Rationale:
- Personalization needs memory (what you starred, skipped, spent time on). Memory lives at the brain.
- Cross-lane synthesis is brain-only ("the DeepSeek paper you starred Tuesday has a follow-up on HN right now" fuses news + supermemory stars — only the brain can do that).
- Sharing is a brain action: `share_item(item_id, recipient)` creates a shared supermemory space. News service never writes.

Amrita's news service exposes just three endpoints (data layer only):
```
GET  /news/candidates?topics=ai,soccer,anime&since=24h   → raw pool, 50-200 items
GET  /news/item/{id}                                      → full extracted text
POST /news/dedupe  body:[items]                           → cluster near-duplicates
```

The brain then: pulls `supermemory.get_user_interests()` + `get_recent_stars()` + `get_recent_skips()`, hits `/news/candidates`, ranks with a small LLM call against user context, picks 5, writes "served item X" back to supermemory so tomorrow doesn't repeat.

### Build order (next 90 min)

1. `~/.hermes/profiles/shruti/` — pinned model (Gemini 2.5 Flash), approval=manual, minimal skills, supermemory MCP
2. `shruti` system prompt — identity + rules + tool-policy lines (NO inline tool specs; those auto-inject from registry)
3. Register HTTP tools pointing at `localhost:9001/*` in the Shruti Hermes config
4. `apps/orchestrator/main.py` — ~100 LOC FastAPI exposing `/v1/chat/completions`, streaming SSE
5. Flip Vapi's custom LLM URL from `apps/voice/` to `apps/orchestrator/`
6. Keep `apps/voice/` as fallback for 1 hour until orchestrator is proven green
7. First end-to-end test: voice "what's due this week" → Hermes → Abishek's cached snapshot → Vapi speaks real ASU Canvas data

### Blockers / open questions

- Need Abishek's three new endpoints (`/brief`, `/items/{id}`, `/items/{id}/user-done`) and materials pipeline unblocked
- Supermemory MCP server details (hosted URL or local npx?) — ask sponsor at venue
- Whether the orchestrator exposes a second SSE route for the web UI, or only Vapi — defer until we know if we need live token streaming in the browser

## Decisions I'm making — session log

- Nov 14 → Nov 15: everything from "plan" above shipped incrementally. The LIVE STATE section below is the authoritative current snapshot.

## Blockers

- See LIVE STATE → blockers list.

---

# LIVE STATE — Nov 15, 06:50 local  *(this is the only part that's current)*

## What's running right now

| Service | Where | Status | Owner |
|---|---|---|---|
| Nova.app (Electron, holographic avatar) | `~/Applications/Nova.app`, pid tracked in session | ✅ running | Shruti (UI), Saswata (voice wiring) |
| Vapi bridge (FastAPI :8000) | `apps/brain/bridge.py` — Hermes-as-brain, SSE streaming to Vapi, control-URL inject | ✅ running | Saswata |
| Cred-agent (FastAPI :9010) | `apps/cred-agent/` — mint credentials to Solana devnet + R2 + Metaplex NFT | ✅ running | Saswata |
| Canvas MCP (FastAPI :9001) | `apps/browser-agent/` — Abishek's Playwright-via-TinyFish Canvas scraper + MCP server | ✅ running (public tunnel) | Abishek |
| Google workspace mock (:9005) | `apps/google-agent/` — mock Gmail/Calendar/Drive | ✅ running | Abishek |
| Amrita news (:9004) | `drafts/amrita-current-events/` — RSS pool | ✅ running | Amrita |
| Cloudflare tunnels | `PUBLIC_BRAIN_BASE`, `PUBLIC_CANVAS_BASE` in `shared.env` | ✅ UP | Saswata |

Health one-liner:
```bash
for p in 8000 9010 9004 9005; do curl -sf http://127.0.0.1:$p/health > /dev/null && echo ":$p UP" || echo ":$p DOWN"; done
```

## Voice stack (locked)

- **Router**: `openai gpt-4o-mini` on Vapi (NOT our Hermes brain). Handles small-talk directly (<1s), delegates hard questions via tools.
- **Brain**: Hermes (Claude Haiku/Opus via Anthropic) at `apps/brain/hermes-home/default/`. Called via `ask_brain` tool from the router.
- **Why two layers**: 80% of turns are small-talk ("hi", "thanks"); routing through Hermes would cost 8s each. Router handles those in 500ms, brain only runs on real fact lookups.
- **Voice**: Nova = `Sagar` (user's dashboard pick, preserved by `_merge_preserving` in setup_vapi), Shruti = `Rohan`. Both Indian male voices for consistency.
- **PTT (push-to-talk)**: SPACE held = mic open, SPACE released = mic muted. Default muted. `desiredMuted` state in `drafts/shruti/app/src/voice/vapiClient.ts` re-asserted on every `call-start` to kill the "mic open on reconnect" footgun.
- **Interrupt**: SPACE press also sends `control: mute-assistant` to Vapi, cutting Nova mid-sentence. 120ms later we unmute her so the next turn plays.

## Tools wired onto Vapi (both Nova + Shruti have all 3)

1. **`ask_brain(question)`** → `POST ${BRAIN_BASE}/ask_brain`
   Fire-and-forget. Returns opaque `<ACK#tNNN>` instantly. Hermes runs in background (6-15s for Canvas/Gmail queries), result injected as spoken message via Vapi's `monitor.controlUrl` → `{type:"say", content, endCallAfterSpoken:false}`.

2. **`check_task(task_id?)`** → `POST ${BRAIN_BASE}/check_task`
   Status lookup for pending background tasks. Prevents re-delegation when user says "still on it?" / "any update?"

3. **`mint_credential(item_key?, nft_name?)`** → `POST ${BRAIN_BASE}/mint_credential`
   Fire-and-forget NFT mint. Forwards to cred-agent :9010. Returns `<ACK#mint-...>` instantly. Real completion spoken via inject-say when NFT lands on devnet + R2 + Metaplex.

## NOVA_ROUTER.md rules (summary — see file for full)

- Rule 1: **ALWAYS invoke the tool** when delegating. Pretending to delegate without calling the tool is a failure.
- Rule 2: `ask_brain` is fire-and-forget. Speak a bridge line ("meanwhile I'm checking Canvas…"), fire the tool, then stay silent. Real answer arrives separately.
- Rule 2a: Follow-ups → `check_task`, never re-call `ask_brain`.
- Rule 2b: Mint intent ("mint my credentials", "put it on-chain", "nft my transcript") → `mint_credential`.
- Rule 3: Normal conversation never triggers the brain.
- Rule 4: One-word prompts answered directly in <5 words.

## Blockchain / credentials (new as of Nov 15)

### What it does

Voice command "mint my credentials" → cred-agent pulls student's Canvas record → canonicalizes → Ed25519-signs with the student's keypair → anchors SHA-256 on Solana devnet (Memo program) → uploads credential JSON to Cloudflare R2 → mints a Metaplex NFT whose `uri` points at the R2 JSON. Anyone with the NFT mint address can:
1. Open Solana Explorer → see the anchor tx
2. GET the R2 JSON → see the full credential envelope
3. Re-hash the canonical bytes → match the on-chain hash → Ed25519-verify the signature

Verify page at `http://127.0.0.1:9010/v/<cred_id>` renders this live: show JSON, let user edit it, hash + signature go red immediately = tamper detection demo.

### Honest trust model (what we tell judges)

This is **NOT** an ASU-signed transcript. ASU doesn't issue verifiable credentials. The on-chain data attests: *"at time T, pubkey P fetched URL U from the Canvas MCP and the bytes hashed to H."*

Trust root = student + browser-oracle (Playwright + TinyFish). For a proper chain of trust, the browser-oracle would also sign the scrape. Documented in `research_asu_credentials.md` at repo root.

### Live devnet state

- **Student pubkey**: `Bq3Ba6ayhtAvf6kuxUyWZKZGu7Da3rRL8aLsBAWhePy1` (funded via `requestAirdrop` on devnet)
- **R2 bucket**: `pub-5a51a49f50124972be99720d47ce46cb.r2.dev` (public read)
- **Latest live mint** (verified ad-hoc end-to-end):
  - Solana tx: `3UxQ7UUivCwRn6VvY6YrrNuJsCgPiffC2PNLmFMGMAzdoonjH4m1PAzPLUMKEnzYEGqgC8mMEVSJMBQWifzXE6Hh`
  - NFT: `9S6WE854BA8v6ARDyNB5oLnvyhjwd936AnbfCHpF6naW`
  - R2 JSON: `https://pub-5a51a49f50124972be99720d47ce46cb.r2.dev/credentials/cred_1794749333_d40a7e.json`
  - Verify: `http://127.0.0.1:9010/v/cred_1794749333_d40a7e`

### Cred-agent files (`apps/cred-agent/app/`)

| File | Purpose |
|---|---|
| `main.py` | FastAPI :9010. Endpoints: `/health`, `/mint_credential`, `/verify`, `/credentials`, `/api/credential/{id}`, `/v/{id}`, `/pending`, `/register_done`, `/airdrop`, `/screenshots/*`, `/static/*` |
| `canonical.py` | Deterministic JSON canonicalization (sorted keys, compact, UTF-8) + SHA-256 |
| `signer.py` | Ed25519 load-from-env + sign + verify |
| `solana_memo.py` | Memo program anchor via pure-Python JSON-RPC (solana-py 0.42 dropped sync Client) |
| `nft_mint.py` | Metaplex Token Metadata NFT: creates mint account, inits mint (decimals=0), ATA, mint_to(1), then borsh-encoded `CreateMetadataAccountV3` at PDA `[b"metadata", METADATA_PROGRAM, mint]`. Two txs, both waited for confirmed. |
| `r2.py` | Cloudflare R2 S3-compatible upload via boto3. `VERIFY_USER_AGENT` exported for UA-gated public GETs. |
| `browser_client.py` | Client for Abishek's `/screenshot` endpoint (defensive — graceful fallback when Abishek hasn't shipped it yet) |
| `canvas_fetch.py` | Pulls transcript data from Canvas MCP (list_courses + get_daily_brief + get_course_items) |
| `registry.py` | Idempotent mint registry → `credentials/_registry.json`. `item_key` → `{cred_id, tx, ts}`. Blocks double-mints. |
| `vapi_tool_def.py` | Scaffolded Vapi function tool def (not auto-wired; `setup_vapi.py` has its own copy) |

### Cred-agent one-shot: `scripts/mint.sh`

```bash
cd apps/cred-agent
./scripts/mint.sh                               # default item_key
./scripts/mint.sh grades hw3 "HW3 Ed25519 proof" # + witness + nft name
```

Boots the service if not running, does a health check, builds the mint body, surfaces any HTTP error with an airdrop command hint, pretty-prints SOLANA tx + NFT mint + verify URL.

## Bridge (`apps/brain/bridge.py`) key endpoints

```
POST /v1/chat/completions   OpenAI-shape stream to Vapi (router model lives upstream)
POST /ask_brain             tool forwarder; fire-and-forget to Hermes
POST /check_task            tool; task registry lookup
POST /mint_credential       tool forwarder; fire-and-forget to cred-agent :9010
GET  /tasks?call_id=...     UI polls this; Electron task panel auto-completes rows
GET  /health
```

Design patterns:
- **Fire-and-forget**: tool handler returns `<ACK#tNNN>` in <5ms, dispatches background work via `asyncio.create_task(...)`, injects final answer via Vapi `monitor.controlUrl` POST `{type:"say", ...}` when done. Prevents Vapi 30s tool timeouts.
- **Task registry**: per-call-id list of `{id, question, status, result, result_full, started_at, finished_at}`. Exposed on `GET /tasks` for the Electron UI poller.
- **Response cap**: `_cap_reply(reply)` truncates at last sentence boundary before 240 chars (TTS-friendly). Full uncapped text preserved in `result_full` for the UI card.

## UI (`drafts/shruti/app/`)

Shruti's Electron + React + three.js holographic avatar app.

- **Push-to-talk**: SPACE held = mic open. SPACE released = muted. `vapiClient.ts` tracks `desiredMuted` and re-asserts on every `call-start` (fixes mic-open-on-reconnect bug).
- **Interrupt**: SPACE press also calls `vapi.send({type:'control', control:'mute-assistant'})` → 120ms → `unmute-assistant`. Instant barge-in.
- **Task panel**: `src/ui/TaskPanel.tsx` + `src/tasks/tasks.ts` + `src/tasks/poller.ts`. When a new task fires, drawer auto-peeks open (notification animation) then auto-closes after 3s. Poller hits `GET /tasks?call_id=<X>` every 1.5s while any task is running.
- **Bridge → UI wire**: `voiceBridge.ts` parses Vapi `tool-calls` + `tool-calls-result` events, maps server task state → UI task rows. Handles `<ACK#tNNN>` (no-op), "just finished" (complete), "Still on" (progress), "snag/error/failed" (fail).
- **Jaw rotation mouth**: `hologramMaterial.ts` (Shruti's latest). Jaw swings around a hinge below ears, lip corners anchored, upper lip moves ~10% of lower.

## Services + files summary

### `apps/brain/`
- `bridge.py` — FastAPI :8000, the Vapi bridge
- `setup_vapi.py` — syncs assistant definitions onto Vapi via REST API. `_merge_preserving` keeps user-managed voice + model-core fields.
- `hermes-home/default/SOUL.md` — Hermes identity, tool routing rules for Canvas/Workspace/news. ≤2-sentence hard cap on replies.
- `hermes-home/default/config.yaml` — Hermes MCPs: canvas + workspace, both via env-driven tunnels.
- `.env` — `ANTHROPIC_API_KEY`, `CANVAS_API_KEY`, `VAPI_PRIVATE_KEY` (gitignored)
- `NOVA_ROUTER.md` — Vapi router system prompt (slim, routing-focused)

### `apps/cred-agent/`
- See table above
- `.env` — `STUDENT_PRIVATE_KEY_BASE58`, `STUDENT_PUBLIC_KEY_BASE58`, `CANVAS_API_KEY`, R2 creds (gitignored)
- `scripts/gen_keypair.py` — one-shot Ed25519 keypair generator
- `scripts/cron_mint.py` — reconciles pending items → Solana (for batch end-of-semester mints)
- `scripts/mint.sh` — fireable one-command mint

### `apps/browser-agent/` (Abishek)
- Canvas MCP + REST on :9001
- Playwright + TinyFish CDP for scraping
- Needs new: `POST /screenshot` and `POST /myasu/login + GET /myasu/snapshot` per `context/abishek-screenshot-myasu-patch.md`

### `apps/google-agent/` (Abishek)
- Gmail + Calendar + Drive on :9005
- Currently `WORKSPACE_BACKEND=mock` — real OAuth deferred

### `drafts/amrita-current-events/` (Amrita)
- RSS news pool on :9004
- News + ASU events tools exposed

### `drafts/shruti/app/` (Shruti)
- Electron holographic avatar
- Current latest: jaw-rotation mouth (`64b7f4e`)

## Shared env (`shared.env` — tracked, non-secret)

```
VAPI_ASSISTANT_ID=f6bd0e01-6592-4ff9-98e8-4a90456441a9
VAPI_SHRUTI_ASSISTANT_ID=ca586ee1-e4e2-4148-a51b-f60d9737c00f
PUBLIC_BRAIN_BASE=https://posts-restructuring-oriental-integral.trycloudflare.com
PUBLIC_CANVAS_BASE=https://establish-editorials-template-occupations.trycloudflare.com
PUBLIC_WORKSPACE_BASE=<tunnel>
BRAIN_PORT=8000
```

## Honest open blockers / punted items

- **MyASU scraping**: Abishek needs to apply `context/abishek-screenshot-myasu-patch.md` to his browser-agent. Until then, credentials embed Canvas data only, no GPA. Screenshot witness is also unavailable (my `browser_client` → 404 → graceful fallback to witnessless mint).
- **Screenshot witness coordinate**: if Abishek ships `/screenshot`, we still need to know WHICH Canvas URL to screenshot per mint type. Simplest: hardcode `/grades` in cred-agent. Cleaner: make `mint_credential` accept a `page` arg → cred-agent maps `"grades" | "transcript"` → URL.
- **Supermemory**: integrated into Hermes profile but not actively used by the voice loop yet. Live demo plan still relies on the "pre-seed 6 weeks of synthetic sessions" trick.
- **Gmail OAuth**: still mocked. Real OAuth 2-3h; mock is fine for stage.
- **Nova.app Electron** has pre-existing lint noise on `vapiClient.ts` when linted in isolation (`--jsx` / `import.meta.env` warnings). Project-level `npm run typecheck` is clean. Don't be fooled by LSP diagnostics on individual files.

## Latency budget (observed, honest)

| Turn type | Time | Notes |
|---|---|---|
| Small talk ("hi", "thanks") | <1s | Router handles, no brain |
| Canvas lookup ("what's due") | 8-10s | Hermes + MCP; filler masks it |
| Gmail (mock) | 8-10s | Same as Canvas |
| News headlines | 11-13s | Hermes + Amrita's RSS |
| Mint credential | 6-15s | Canvas fetch + sign + Solana + R2 + Metaplex NFT (2 txs waited for confirmed) |

## Git state

- Branch: `main`
- Latest commit: `01084e3 voice: enforce mute until SPACE (fix mic-open-on-call-start bug)` (exact SHA may drift — run `git log -1` for current)
- Shruti's latest UI commit pulled: `64b7f4e shruti: natural talking mouth — jaw rotation with anchored corners`
- Autosync via `.git-autosync.sh` runs periodically; manual `git pull --rebase --autostash` + `git push` cadence in practice
