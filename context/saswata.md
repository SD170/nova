# Saswata — context + notes

Owner: Saswata Dutta (GitHub: SD170)

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
| Orchestrator hosting | **Maritime** | Per-student agent VM. Jarvis keeps state across sessions, can run browser scrapes while you sleep (pre-fetch tomorrow's Canvas updates before your morning session). Literally their pitch. |
| Narrative / pitch | **JFFVentures (Future of Work)** | Future of learning + knowledge work. International-student angle sharpens it. |
| Compute / backup models | **AWS** (Bedrock) | One sub-agent on Bedrock, orchestrator on Lambda or ECS. |
| Primary hosting | **Vultr** | Main web app. Free credits, zero extra engineering, stacks alongside AWS. |
| Dev workflow (free raffle) | **MLH Cursor + Grok Bot** | Already coding in Cursor; add a Grok Bot to team Discord. 15 min of effort for a free raffle entry. |
| Activity analytics (if time) | **Tiger Data** | Time-series of study sessions, topic mastery over time, performance charts. P2. |
| Domain | **GoDaddy Registry** | Buy a .lol or similar for the demo. $12, trivial. |

**Realistic prize count: 5-8.** Best Overall is a stretch if the voice + orchestrator + browser demo lands.

Explicitly not chasing: MatLab (forced), Solana (forced), Hardware (no budget/time), Gaming (not primary — could gamify quizzes if slack), MLH niche tracks.

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
    Package a student's Jarvis context for a given course (embedded materials + weak-topic graph + prior quizzes + style prefs) as a portable artifact. Teammate imports → their Jarvis instantly knows the course structure + accumulated understanding.
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
  "message": "Jarvis, I have an exam Monday. Am I ready?",
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

User: *"Jarvis, quiz me for Monday's exam."*

Jarvis: *"Skipping convolution — you got 9/10 on HW4 and the prof's email last Tuesday said it won't be on the exam. Phase shifts — you missed 3 of 4 in HW3 and your notes from Oct 12 said 'I don't get this' — starting here. Question 1..."*

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
- **Teammate hand-off (Abishek's idea #2)** — "Fork my Jarvis context for CSE 310 to Priya." Her Jarvis gets the course structure + accumulated class understanding, not your personal weak-topic map. Clearly different from sharing notes.

## Voice stack decision

**For the demo: Vapi.** Sub-500ms end-to-end, handles turn-taking + barge-in + pauses out of the box, 30 min to wire up. Our `/chat` endpoint stays identical — Vapi just wraps around it. Fallback if Vapi's free tier bites: OpenAI Whisper (STT) + OpenAI TTS pipeline, ~15 min glue.

**For a privacy-first / secure environment (post-hackathon or if a track asks for local-only):** VoiceStudio (github.com/debpalash/VoiceStudio). Fully local, open-source ElevenLabs alternative — voice cloning, TTS, STT, 646 languages, runs on-device. Great fit when student data cannot touch cloud voice APIs (FERPA-sensitive deployments, dorm wifi off, international-student PII concerns). Not picked for the live demo because:
- Latency on a laptop under demo load (orchestrator + UI + browser-use all running) is 1-3s per turn, voice demos die at >1s gaps
- AGPL-3.0 is viral — licensing concern if we ever host it commercially
- Needs model download + HTTP wrapping (~4-8h of setup we don't have)

Keep VoiceStudio in the pitch as the "and here's the local / private deployment story" slide. Judges + JFF investors like seeing a credible on-prem path even if the demo is cloud.

## My ideas / open questions

- 

## Decisions I'm making

- 

## Blockers

- 
