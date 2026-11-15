# 01 — Project Brief

Full context for Nova. Synthesizes the gpt.pdf brief + the full brainstorm thread (ideas explored, why we picked this one, ideas rejected and why).

## Where we are

**Event:** SunHacks 2026, ASU Tempe Student Pavilion.
**Deadline:** Nov 15 2026, 11:00 AM MST.
**Team:** 4 people.
**Hours of real dev time:** ~20h after food, sleep, submission buffer.

## What we're building

Voice-enabled agentic student assistant, Canvas-grounded.

**Demo statement:** "Nova, I have an exam on Monday. Check what I need to study, test my knowledge, and find time to revise around my commitments."

This is **not** a chatbot wrapper. The agent must:
1. Retrieve real Canvas data (courses, assignments, materials)
2. Reason across retrieved sources with citations
3. Run a voice quiz grounded in that material
4. Propose revision plan based on quiz weak points + calendar free/busy
5. Execute calendar writes **only after explicit approval**

## Feature priority

| P | Capability | MVP scope |
|---|---|---|
| **P0** | Canvas academic context | Fetch courses, assignments, deadlines, materials |
| **P0** | Agent orchestration | Intent → tool call → compose results → approval gate |
| **P0** | Voice + simple UI | Push-to-talk STT, TTS response, result cards |
| **P0** | Exam-prep intelligence | Retrieve, generate grounded quiz, assess, identify weak topics |
| **P1** | Calendar scheduling | Read free/busy, propose + create study blocks post-approval |
| **P1** | Proactive academic rescue | Detect close deadlines/conflicts, propose realistic plan |
| **P2** | Universal student memory | Search across course notes + messages + transcripts |
| **P2** | Meeting intelligence | Summarize permitted transcripts, extract tasks |
| **P2** | Career/internship copilot | Job matching, resume suggestions |
| **P2** | Gmail assistance | Read + draft replies with permission |

**Scope discipline:** One reliable end-to-end academic flow before adding meetings, jobs, or email.

## Team split

| Owner | Component | Deliverables |
|---|---|---|
| **Person 1 — strongest backend** | Agent backend + orchestration | LLM API, `/chat` endpoint, tool registry/router, conversation state, multi-step workflows, confirmation gate, structured responses |
| **Person 2 — integrations** | External adapters | Canvas auth, `get_courses`, `get_assignments`, `get_course_materials`, normalized JSON; optional `get_calendar_events`, `create_study_block` |
| **Person 3 — AI/retrieval** | Academic intelligence | Index course docs, retrieve passages, generate grounded quiz, grade answers, identify weak topics, revision plan with source refs |
| **Person 4 — UI/voice/demo** | Student experience | Chat screen, push-to-talk STT, TTS, cards, approval button, loading/error states, demo polish |

**Boundaries:**
- Person 1 decides which tool to call, not how Canvas works internally
- Person 2 fetches/normalizes data, does not own quiz logic
- Person 3 reasons over retrieved content, does not own OAuth or UI
- Person 4 renders + captures interaction, does not own tool routing

If a teammate has less technical experience: assign template-driven UI/demo work with tight API contracts, supported by Person 1. Do not give them critical infra unsupervised.

## Architecture

```
Student (voice or text)
    ↓
[Person 4: UI + STT/TTS]
    ↓
[Person 1: LLM agent / orchestrator]
    ↓                    ↓
[Person 2: Canvas /     [Person 3: Retrieval +
 Calendar adapters]      exam quiz + study plan]
    ↓
[Approval for external writes]
    ↓
[Tool execution] → [UI response]
```

**Rule:** Agree on shared JSON contract immediately. Build with mocks until integrations work.

## Tool contract (proposed)

```json
{
  "name": "get_assignments",
  "arguments": {"course_id": "example-course"},
  "result": {
    "items": [
      {
        "id": "a1",
        "title": "Homework 3",
        "due_at": "2026-11-16T23:59:00",
        "source_url": "https://example.edu/assignment/a1"
      }
    ]
  }
}
```

Tool names: `get_courses`, `get_assignments`, `get_course_materials`, `generate_exam_quiz`, `evaluate_quiz_answer`, `suggest_study_plan`, `get_calendar_events`, `create_study_block`.

These are **proposed internal interfaces**, not existing APIs.

## End-to-end demo

1. Student: *"Nova, I have an exam on Monday. Am I ready?"*
2. Nova retrieves relevant Canvas materials, upcoming assignments, exam info if available
3. Nova summarizes likely topics **with source links** — does not invent exam coverage
4. Student: *"Quiz me while I'm walking home."* Nova asks by voice, evaluates, identifies weak areas
5. Nova: *"You struggled with two topics. I can schedule revision in your free slots."*
6. Student approves → Nova creates calendar study block (only if calendar integration ready)

**Fallback:** If Calendar OAuth or Canvas doc access fails → use clearly labeled demo data for that integration. Keep agent + quiz working. **Never present mocks as live account access.**

## Privacy and responsible use

- Explicit informed permission before accessing student accounts or sending content to cloud LLM
- Request minimum necessary scopes; send only task-relevant excerpts
- Explain which external provider receives data; check retention + training terms
- Store credentials securely, never in source control or client bundles; revoke demo creds after event
- Require user confirmation before external writes (email, calendar, applications)
- Do not submit graded assignments automatically; do not impersonate students in meetings
- Meeting transcripts: get participant permission + follow institutional rules
- Consent is not the only requirement — follow university policy + applicable privacy law
- **Optional differentiator:** "Data preview" card shown before sensitive LLM calls, showing exactly what info will be shared

## Timebox (20h example)

| Window | Goal |
|---|---|
| 0–2h | Freeze demo flow, interfaces, repo structure, credentials, fallback data |
| 2–12h | Parallel implementation with mock tools |
| 12–16h | Integrate agent ↔ tools ↔ quiz ↔ voice/UI, fix broken contracts |
| 16–20h | Rehearse live demo, test failure paths, record backup video, polish pitch |

**If less time remains, shorten feature work, not integration/testing. Stop adding features once core flow works.**

## Reuse (evaluate before adopting)

Categories to evaluate quickly:
- Canvas official API
- Google Calendar API
- Existing voice agent / STT / TTS SDK
- Agent tool-calling framework (OpenAI Agents SDK, LangChain, LlamaIndex, Hermes)
- Retrieval libraries (LlamaIndex, Haystack, Chroma, Qdrant)

**CareerOps** was mentioned as possible OSS job-flow component — verify specific repo, license, maintenance, actual capabilities before adopting.

**Verify, don't assume.** No external repo or hackathon winner is independently verified here.

## Success criteria

- Student can ask natural-language question, get Canvas-grounded answer
- Nova can run short voice quiz using retrieved course content
- Nova can recommend personalized revision plan based on answers + deadlines
- At least one external action works (preferably Calendar) after explicit approval, OR is clearly demonstrated as mock
- Demo recovers from API errors without crashing

## Open decisions

- LLM provider? (Claude / Gemini / GPT / Hermes)
- Voice stack? (OpenAI Whisper + TTS, ElevenLabs, Cartesia)
- Agent framework? (OpenAI Agents SDK, LangGraph, Hermes, roll own)
- Real Canvas access? (Does anyone on team have a token?)
- Google Calendar OAuth feasible in time?
- Who owns final merge + demo rehearsal? (Suggested: Person 1 merge, Person 4 demo)

---

## Sponsor stack math (why this project)

SunHacks sponsor prizes we can realistically stack:

| Sponsor | Fit | How |
|---|---|---|
| **Maritime** | Strong | Host one agent VM per student user, persistent across sessions. Matches their pitch exactly. |
| **supermemory** | Strong | Student's academic memory — courses, past assignments, weak topics, learning style. |
| **TinyFish** | Medium | Web research fallback when Canvas lacks info (lecture slides on prof's personal site, external references). Multi-hop research for exam topic coverage. |
| **MongoDB Atlas** | Medium | Vector search over course materials. |
| **Gemini** | Strong | Long-context (2M tokens) ingest of entire course material corpus per query. |
| **JFF Ventures** | Medium | Future of *learning* adjacent to future of work. International student angle is strong. |
| **AWS** | Medium | Generic hosting / Bedrock fallback. |
| **MLH SpaceXSI** | Free | Use Cursor for coding + wire Grok Bot into workflow. Zero added work, free raffle entry. |
| **Best Hardware** | Weak | Not aiming. |
| **Best Gaming** | Weak | Not aiming. |

**Realistic prize count:** 3-5 if execution is tight. Best Overall contender if the live voice demo lands.

## Judging criteria — be honest with ourselves

SunHacks judging: **Originality, Complexity, Functionality, Design.** No impact axis. Build must work on stage.

- **Originality:** medium — "student assistant" has been done, but voice-first + Canvas-grounded + multi-hop retrieval + approval-gated actions is a sharper slice than most entries
- **Complexity:** high — real retrieval, real tool orchestration, real voice loop, real OAuth
- **Functionality:** this is where we win or lose — the demo must work live
- **Design:** approval cards + grounded citations + source links = visible polish

## Brainstorm history — what we considered + rejected

Full log of alternatives explored and why we didn't pick them. Useful if we hit a wall and need to pivot.

### Rejected ideas

1. **"Hire Your First AI Agent" track framing** — turned out not to be a real track; JFFVentures "Future of Work" was the closest.
2. **Bounty marketplace** — two-sided marketplace demo is hollow; existing competitors (Replit, Gitcoin, Algora); verification problem can't be solved in 20h legitimately.
3. **Campus reputation score** — basic framing; perverse incentives trap in Q&A; low visible complexity; doesn't stack sponsor prizes.
4. **GTA VI leak dashboard** — fun, timely, stacks Tiger Data; weaker JFF angle than student-focused project; frivolous for the investor meeting.
5. **"Talk to Goku / famous people" voice clone** — Character.AI genre saturation; IP + right-of-publicity landmines; judges have seen 50+; no sponsor fit.
6. **VR step into historical events** — scope impossible in 20h; headset dependency; no sponsor fit; 3D generation still unsolved.
7. **AI credit arbitrage marketplace** — ToS violation across all providers; MLH would flag; no VC touches it.
8. **"Watch my browser all day" ambient Cluely-clone** — crowded (Dia, Comet, Arc Max, Rewind); creepy framing; crowded prize landscape.
9. **Helping autistic kids** — high domain risk without community input; low complexity ceiling; no sponsor stack fit; no judging axis for impact.

### Why Nova won the final selection

- **You live this problem** (ASU student, Canvas is real pain, international student + CPT context)
- **Real backend work:** retrieval pipeline, tool orchestration, voice loop, OAuth, approval gate
- **Canvas grounding is a defensible wedge** — generic student AIs don't ground in course material
- **Voice is the demo moment** — judges hear it work, remember it
- **Approval gate is a serious design choice** that judges will notice
- **Sponsor stack is 3-5 prizes deep**
- **Fallback demo exists** — if Canvas fails, mock data keeps the quiz working
- **4-person team fits the architecture cleanly** — no one is blocking anyone

## Patterns that won recent agent hackathons (reference)

From 2026 agent hackathons (Berkeley AI, Anthropic x Maryland, Agentic Engineering Hack, etc.):

- **"Agent reads an ignored source, makes it queryable"** — WAGE.md, RegRadar, Receipts
- **"Voice → structured output"** — Relay (nurse handoff), Memo, Haven
- **"Niche vertical, real pain"** — policyDiff, TC-Pilot, Arrive (international students at UMD)
- **"Grounded with citations, no hallucinations"** — saga, CoTA

**Nova matches 3 of these patterns simultaneously.** That's the design thesis.

## First-hour checklist

- [ ] Lock interface contract (JSON shape above)
- [ ] Stand up mock tool registry so all 4 people can start in parallel
- [ ] Decide LLM provider + voice stack
- [ ] Verify Canvas access (does anyone have a real token?)
- [ ] Decide Calendar: real OAuth or clearly mocked?
- [ ] Choose repo layout for sub-components
- [ ] Set up Hermes config to auto-load this AGENTS.md across all teammates' laptops
