# AGENTS.md — Student Jarvis

Auto-loaded by Hermes / Claude Code / Cursor / Codex when run from this repo.

## What we're building

Voice-enabled agentic student assistant. Canvas-grounded. Exam prep. Calendar scheduling. Ships at SunHacks 2026 (ASU Tempe), deadline Nov 15 2026 11:00am MST.

## Pitch in one line

"Jarvis for students — ask once by voice, it reads your Canvas, quizzes you on real course material, and books revision blocks into your calendar after approval."

## Hard constraints

- **Time:** <24h total, this is a hackathon
- **Team:** 4 people (see context/01-project-brief.md for split)
- **Scope discipline:** one reliable end-to-end academic flow before anything else
- **Approval gate:** never execute external writes (calendar, email, submissions) without explicit user confirm
- **Grounding:** every academic claim links back to a Canvas source; never invent exam coverage
- **Fallback:** if Canvas OAuth or Calendar fails, use clearly labeled demo data — never present mocks as live

## Non-negotiables for judging

SunHacks judges on: Originality, Complexity, Functionality, Design. NOT impact. Build must *work* on stage.

## Prize stack we're aiming at

Maritime (hosting), supermemory (memory), TinyFish (web research fallback), MongoDB Atlas (vector), Gemini (long-context reasoning), JFF Ventures (future of work angle), AWS (compute), MLH SpaceXSI (Cursor + Grok Bot — free raffle entry).

## Architecture (proposed)

```
Student voice/text
    ↓
UI layer (Person 4) — push-to-talk STT, TTS, approval cards
    ↓
Agent orchestrator (Person 1) — LLM, tool router, state, confirmation gate
    ↓                           ↓
Canvas/Calendar adapters    Course retrieval + quiz engine
(Person 2)                  (Person 3)
    ↓
Approval → Tool execution → UI response
```

## Interface contract (lock early, mock first)

Tool call shape:
```json
{
  "name": "get_assignments",
  "arguments": {"course_id": "example-course"},
  "result": {
    "items": [
      {"id": "a1", "title": "Homework 3", "due_at": "2026-11-16T23:59:00", "source_url": "https://example.edu/assignment/a1"}
    ]
  }
}
```

Tool registry (proposed, build with mocks first):
- `get_courses`
- `get_assignments`
- `get_course_materials`
- `generate_exam_quiz`
- `evaluate_quiz_answer`
- `suggest_study_plan`
- `get_calendar_events`
- `create_study_block` (requires approval)

## Working rules for AI agents reading this

1. **Read context/ before answering.** Full brainstorm + rejected ideas + sponsor fit live there.
2. **Never put secrets in config files.** `.env` only. `.env` is gitignored.
3. **No agent writes external services without explicit approval UI.**
4. **If asked to add a feature, check priority (P0/P1/P2) in context/01-project-brief.md first.** Reject scope creep.
5. **Prefer mock responses in early hours** so team can integrate in parallel.
6. **Every Canvas claim needs a source_url in the response.** Quiz questions must be answerable from retrieved passages.

## Owner map

| Person | Owns | Does NOT own |
|---|---|---|
| 1 | Agent orchestrator, tool router | Canvas internals |
| 2 | Canvas + Calendar adapters | Quiz logic |
| 3 | Retrieval, quiz, study plan | OAuth, UI |
| 4 | UI, voice, demo polish | Tool routing |

## Current status

Planning. No code committed yet. Next step: lock interface contract + spin up mock tools so everyone can start in parallel.
