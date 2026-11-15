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

### P1 — makes the demo impressive

6. **Canvas API path (if a token is available)**
   Real Canvas REST calls as a faster + more reliable alternative to browser scrape. Same tool contract as the browser sub-agent.

7. **Calendar sub-agent**
   Google Calendar OAuth, read free/busy, propose study blocks, create block (approval-gated).

8. **Approval gate UI**
   Preview card showing exactly what tool will be called with what arguments. Approve / Cancel buttons. "What will be sent to the LLM" transparency.

### P2 — stretch / polish

9. **Memory layer**
   Persistent per-user memory of weak topics, past quizzes, study preferences. Fits supermemory.

10. **OS-level app access**
    AppleScript / accessibility bridge to native macOS apps (Reminders, Notes, Mail). Optional second integration surface.

11. **Second browser capability**
    e.g., scrape professor's personal course page when Canvas is missing material. Adds complexity for judges.

12. **Demo polish**
    Loading states, error toasts, graceful fallbacks, rehearsal, backup recorded video.

## Hour-0, done together (not assigned, decided as a group)

- Pick LLM provider + agent framework
- Pick voice stack (OpenAI Realtime vs STT + LLM + TTS pipeline)
- Pick browser-control library (browser-use / Playwright / TinyFish / Stagehand)
- Lock JSON schemas: `/chat` request/response, tool call shape, UI card types
- Decide Canvas path: API, browser, or both
- Stub mock responses for every tool so everyone can build in parallel from minute 1

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

## My ideas / open questions

- 

## Decisions I'm making

- 

## Blockers

- 
