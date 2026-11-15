# Student Jarvis — Jarvis Care (implementation brief)

Implementation brief for Claude Code | SunHacks 2026. Owner: Amrita (AmritaSeeram).
Implementation lives in `apps/health/` — see `apps/health/README.md` for what is built, what is mocked, and how to run it.

- **Product concept:** One calm, voice-first, fully accessible healthcare companion inside the existing Student Jarvis app.
- **Audience:** Primarily college students; interactions should also remain welcoming to users with different ages, abilities, reading levels, and languages.
- **Module name:** Jarvis Care. Internal experience called **CareLoop**.
- **Tagline:** Your health, explained. Your next step, made easier.

## 0. Instructions to Claude Code — start here

You are working inside the existing Student Jarvis repository (SD170/student-jarvis) as a teammate. Build a beautiful, functioning, accessible healthcare feature within the existing app, not a separate site or a disconnected demo.

1. Inspect the current project: AGENTS.md, README.md, context/, package manifests, app routes, reusable components, agent orchestration, voice stack, styling, and test framework. Follow repo instructions and team API contracts. Do not assume a framework until you inspect the code.
2. Respect teammates' work. Work in a clearly isolated healthcare feature folder (suggestion: `apps/healthcare/` or the existing app's equivalent). Make only minimal, documented changes for registration, routes, and shared UI. Do not overwrite or reformat unrelated work. Tell the team before proposing shared contract changes.
3. Deliver actual implemented components and runnable workflows, not just Figma-style mockups. At least one end-to-end flow must truly work with mock/sample data and the current available AI provider. Any unimplemented integration must be clearly labeled demo/mock, never falsely shown as live.
4. Treat the voice experience and disability accessibility as required functionality, not stretch goals. All tasks must be possible without a microphone too.
5. For healthcare data, default to synthetic demo data and conservative, non-diagnostic assistance. Never claim to access health records, insurance plans, booking inventories, or a student's calendar unless genuinely connected and authorized.
6. Prefer the team's existing Gemini/API/backend/tool abstractions. Avoid introducing an entirely separate auth, backend, database, or design system. Any API keys go server-side via `.env.example`; never commit secrets or call paid AI APIs directly from publicly shipped client code.
7. Build with clear error states, accessible fallbacks, deterministic mock data, and unit/integration tests. Verify locally with the project's existing commands.
8. Document exactly what works, what uses mocks, how to run it, and how teammates call the healthcare agent. Prepare a repeatable 90-second live demo.
9. If time is tight, follow the priority order in section 9. Make the core flow excellent rather than building a dozen incomplete screens.
10. When done, provide a concise summary of files changed, API contracts, commands executed, tests passed/failed, and any integration steps the team must perform.

## 1. Product vision

Jarvis Care is a personal health-navigation and life-organization companion inside Student Jarvis. It does not diagnose or replace doctors. Its value is turning confusing everyday healthcare information into understandable, audible, actionable next steps while taking student commitments into account.

The signature experience is **CareLoop**:

> Speak or upload → Jarvis understands and clarifies → Jarvis explains out loud and on screen → Jarvis proposes a next action → User approves → Jarvis helps follow through.

Example student voice request:

> "Hey Jarvis, I have an exam Monday, I've been sleeping poorly lately, I got confusing instructions from my doctor, and I need to schedule a follow-up. Can you help me organize all that?"

Jarvis Care should:

- Listen to the user's request with clearly visible recording state.
- Reply verbally in plain, concise language.
- Produce synchronized readable text, accessible action cards, and optional spoken guidance.
- Extract the actual documented next steps from a synthetic sample visit note, never adding medical directions.
- Request calendar availability from Jarvis's shared scheduling/academics agent only if available and permitted. Otherwise accept manual free/busy windows.
- Produce an editable follow-up plan with reminders and questions, asking for confirmation before saving/sharing/bookings.

**Differentiator:** accessible, voice-led care coordination (student voice → medical document → understandable explanation → planned tasks → calendar-aware action), not medical diagnosis or generic health advice.

## 2. Feature set

### A. Voice-first Care Conversation (P0, MUST WORK)
Large microphone button starts a turn-based conversation. Example utterances: "What do I need to do before my appointment?", "Can you read my doctor's instructions out loud, slowly?", "Help me prepare questions about what I've been noticing.", "What does my medical bill mean?", "Make a reminder for my follow-up next week.", "I can't read this; make the text bigger."

STT captures the utterance; the health agent picks a tool/action; the reply appears in text and is spoken via TTS; large action cards are offered. Everything works typed too.

Voice controls: Start listening, Stop listening, Mute/unmute spoken replies, Replay answer, Stop speaking, Repeat more slowly, Edit transcript, Send typed message. Never continuously record by default. Playback can be interrupted. States Listening / Thinking / Speaking / Done / Error are communicated accessibly.

### B. Health Check-in & Doctor Visit Prep (P1)
Optional journal (sleep, energy, stress, well-being, symptoms/questions in the user's words — not medical screening). No numerical health scores or diagnostic judgments. Visit Prep Card: "What I want my doctor to know", "Questions I want to ask" (editable), "Things I'm unsure about"; download/copy. Insights phrased as conversation starters ("You mentioned tiredness three times this week. Would you like to mention that at your next visit?").

### C. After-Visit Care Plan (P0, MUST WORK)
Upload a synthetic after-visit summary (PDF, image, or text). Extract only source-supported follow-up dates, instructions (exact or faithful paraphrase), items needing clarification, and reminder suggestions derived only from documented instructions. Each card shows Evidence (quoted sentence / filename / page). Editable checklist; the user approves reminders; uncertain extraction → "Needs confirmation". Read-aloud speaks a short summary, then individual cards on demand. Medication items may be organized but never new medication use, timing, dosing changes, or treatment decisions.

### D. BillSmart (P1)
Compare a synthetic hospital bill and EOB: service dates, billed, adjustments, patient responsibility. Neutral labels: "Possible mismatch to verify", "Need more information", "Matches the supplied documents". General educational explanations of deductible/copay/coinsurance. Never promise a lower bill, assert an error from incomplete evidence, estimate coverage without the plan, or tell users to ignore a bill. "Copy questions for billing office" and "How to verify". One document only → comparison incomplete.

### E. Smart Appointments & Calendar Awareness (P1/P2)
Free/busy from the existing Jarvis scheduler only with permission, or manually entered availability. Suggested windows are free time, not clinic availability. Confirmation summary and explicit approval before any change. Demo booking clearly labeled "Demo — no real appointment booked".

### F. Your Care Timeline (P1)
Chronological: appointments/planning tasks, provider questions, after-visit checklist items, bill questions, student deadlines (if permitted). Not a clinical record.

### G. Accessibility Center (P0, MUST WORK)
Visible "Accessibility" button on every page. Preferences persist locally: text size (Normal / Large / Extra Large / 200%) plus native zoom; high contrast and dark mode; read-aloud on/off, repeat, voice selection, speed 0.75x–1.5x, pause/resume; simple vs detailed language; reduced motion; transcripts always available; non-color-only status; generous buttons; logical headings; keyboard navigation.

## 3. Visual design — "Calm, premium, intelligent care"

Refined wellness product, part of the Jarvis family — not a hospital portal or harsh dashboard.

Palette (verify contrast): canvas `#F6F8F7`, cards `#FFFFFF`, text `#1C2930`, primary `#126E67`, accent sage `#D9EDE5`, warm peach `#F9EDE3`, dividers `#DDE5E4`, dark mode `#101B21` with distinct surface layers.

Fonts: repo typography first, else Inter / Atkinson Hyperlegible / system sans. 20–24px corners, low shadows, generous whitespace, line icons, ≥44×44px targets, contrast ≥4.5:1. No unnecessary gradients, glow, constant animation, or emoji overload.

Desktop: top bar (Student Jarvis · Care / Academics · Accessibility), module nav, main (greeting, Talk to Jarvis, quick tasks, AI reply with Replay / Slow down / View evidence), right "Your Care Loop" panel, voice dock. Don't create a competing global sidebar or duplicate Jarvis's voice assistant if the main app already has one.

Mobile / high zoom: single column, no horizontal scroll, greeting → voice → next step → actions → timeline. Reflow at 200% and 400%; never disable pinch zoom.

Routes: `/health`, `/health/conversation`, `/health/visit-prep`, `/health/care-plan`, `/health/bills`, `/health/appointments`, `/health/timeline`, plus a global accessibility panel.

Components: CareHome, VoiceDock, ConversationTranscript, LargeActionTile, NextBestStepCard, DocumentUploader, DocumentEvidence, VisitPrepSummary, CareChecklist, BillComparison, AppointmentPlanner, CareTimeline, AccessibilityPanel, ConsentDialog, StatusAnnouncement — each with focus management, loading/empty/error states, semantic labels, responsive styling.

## 4. Voice experience

A user can talk and get a spoken answer without reading; all speech is also shown as text.

Sequence: activate Talk to Jarvis → visible/announced "Listening…" with Stop → transcript shown and editable → route to the health module; low confidence → one concise clarification → `spokenSummary` (1–3 short sentences) + cards → auto read-aloud if enabled with Speaking state, Stop and Replay; never read huge documents automatically → short follow-up question; wait for approval before any change.

Technical: reuse the team ASR/TTS pipeline if present; else progressive enhancement with browser SpeechRecognition (disclose that some browsers use a server service) and typed fallback; mic permission only on intentional activation. TTS via the app's adapter or `window.speechSynthesis`; stop stale audio; respect rate/language; fully silent mode supported. Shortcuts optional, never the only path. Tap-to-talk; no always-on claims. Single mic ownership. `aria-live="polite"` for short state updates only; avoid duplicate announcements while TTS speaks.

Demoable samples:
1. **Documents** — "Jarvis, read this visit summary and tell me what I need to do next." → "I found two follow-up tasks in your document. One has a date, and one needs clarification. Would you like me to read them?"
2. **Scheduling** — "Find some time next week for a follow-up, but I have a Monday exam." → "I can look for free time that avoids your exam. I won't book anything without your approval."
3. **Bill** — "Does my hospital bill match what insurance says?" → "There may be a difference between these two documents. I'll show you the matching charges and questions to ask before paying."
4. **Accessibility** — "Jarvis, I can't read that. Make everything bigger and say it slowly." → "Of course. I've enlarged the text and slowed down my voice." (preferences must actually change)

## 5. Agent design and integration contract

One healthcare capability (`healthAgent.handle(request, context)`) registered with the app's orchestrator; no separate conversational assistant.

```ts
interface JarvisCareRequest {
  requestId: string;
  source: 'voice' | 'text' | 'upload' | 'ui';
  utterance?: string;
  intent?: 'health.checkin' | 'health.visitPrep' | 'health.parseAfterVisit' |
           'health.compareBill' | 'health.planAppointment' | 'health.reminder' |
           'health.accessibility' | 'health.help';
  documentIds?: string[];
  preferences?: { simpleLanguage: boolean; speak: boolean; locale: string };
  permittedContext?: { availability?: Array<{ start: string; end: string }> };
}

interface JarvisCareResponse {
  requestId: string;
  intent: string;
  replyText: string;
  spokenSummary: string;
  cards: Array<{
    id: string;
    kind: 'task' | 'question' | 'billFlag' | 'appointmentOption' | 'info';
    title: string;
    description: string;
    status?: 'suggested' | 'needsConfirmation' | 'ready' | 'done';
    evidence?: Array<{ docId: string; filename: string; page?: number; excerpt: string }>;
  }>;
  actions: Array<{
    id: string;
    label: string;
    kind: 'saveReminder' | 'copyQuestions' | 'openCalendar' | 'confirmAppointment' | 'edit';
    requiresConfirmation: boolean;
    payload?: Record<string, unknown>;
  }>;
  clarification?: string;
  disclaimer?: string;
  isMock: boolean;
}
```

Rules: scheduling context only with authorization; text + speech-friendly wording (voice layer plays it); keep evidence, flag unsupported summaries as uncertain; never execute external actions on a suggestion — render for approval first; prefer existing storage; keep health data isolated from career/academic profiling; all errors return an accessible explanation plus retry/manual alternatives.

Data models: `HealthNote`, `Document`, `CareTask`, `BillLine`, `BillFinding`, `AccessibilityPrefs { textScale, highContrast, reduceMotion, speechEnabled, speechRate, simpleLanguage, locale }`.

## 6. Document understanding / bill logic

Constrained, validated outputs (no ad-hoc prose parsing). Source quotes must be true substrings of extracted text where possible, otherwise marked unverified.

Bills: extract role (EOB vs bill), provider, service dates, descriptions, billed, allowed, payments/adjustments, patient responsibility, denied/pending items. Match comparable lines by date/description/code/amount; keep unmatched rows visible. Billed vs allowed difference is not automatically an error. Flag a responsibility mismatch only when comparable lines clearly conflict. Amounts traceable to rows; arithmetic checked locally, not by an LLM. Generate questions, not disputes or payment decisions.

After-visit notes: dates and tasks with evidence; never rewrite into new treatment directions; missing time/date/provider → clarification card; user chooses and confirms reminders.

## 7. Accessibility acceptance requirements (target WCAG 2.2 AA — test, don't just claim)

- **Motor:** full keyboard use, visible focus, predictable order, skip link, no traps, ≥44×44px targets.
- **Low vision:** 200% text resize; reflow at 400% / 320 CSS px without loss; never disable zoom; contrast ≥4.5:1 text, ≥3:1 UI indicators.
- **Screen readers:** semantic headings, labeled forms, descriptive buttons, error associations, dialog focus trap/return, alt text, status announcements.
- **Hearing:** nothing speech-only; transcript always; visible mic/connection status.
- **Speech limitations:** nothing requires speaking.
- **Cognitive:** simple-language mode, short sections, one primary action at a time, helpful error recovery, no alarming cues for ordinary uncertainty.
- **Photosensitivity / vestibular:** honor reduced motion, no flashing.
- **Privacy:** visible recording indicator, user-controlled stop, no background recording.
- **i18n:** proper `lang`, accessible dates/times, locale preference, no claims of clinically verified translation.

Checks: lint/build/unit tests; axe tests if infra exists (else a manual checklist); keyboard walkthrough of the four demo screens; 200% text and 400% zoom; voice off → fully usable; mic denied → fallback; no speechSynthesis / SpeechRecognition → no crash.

## 8. Privacy, trust, and health safety

Information-organization aid, not a physician, therapist, insurer, billing adjudicator, or appointment inventory. No diagnosis, risk scoring, prescriptions, or treatment changes. Urgent situations → short reminder that the assistant can't assess emergencies; contact emergency services or a professional, without triage. No guarantees on coverage or bills. No false claims that something was booked, saved, or sent. Minimize health data; synthetic profiles only in demos. Files/audio opt-in; document storage; provide clear-data control. Credentials server-side; redact logs. Privacy by default for minors. No social comparison of bodies, eating, appearance, or fitness.

Footer: "Jarvis Care helps organize healthcare information and questions. It does not provide medical advice or verify coverage. Confirm important details with your provider or insurer."

## 9. Delivery plan

**P0:** (1) `/health` accessible home integrated with Jarvis navigation; (2) reliable voice/text chat with STT where available, audible TTS, transcript, stop/replay, voice-off fallback; (3) one synthetic after-visit flow: select/upload → source-backed steps → spoken explanation → editable checklist → approve local reminder; (4) accessibility panel (large text, contrast, speech controls, simple language, reflow); (5) deterministic mock backend fallback.

**P1:** (6) bill/EOB comparison with one verifiable discrepancy/question; (7) visit-prep question generator; (8) calendar-aware suggestions without pretending clinic availability.

**P2:** (9) timeline persistence and tested multilingual audio; (10) real booking only if feasible, authenticated, approved; (11) extra animation/marketing pages last.

No placeholder screens claiming functionality. Never trade accessibility or voice output for cosmetics.

## 10. 90-second judge demo

Setup: synthetic student "Sam", fictional after-visit note, fictional bill/EOB, fake exam schedule — all visibly "Demo data".

- **00–15s Voice + inclusion:** tap the mic, "Jarvis, I don't understand my doctor's instructions. Can you tell me what's next?" — spoken answer + captions.
- **15–40s Document → actions:** select the sample note; follow-up task + one open question with evidence; "Make reminder" → confirm → shows in timeline.
- **40–55s Accessibility:** "Jarvis, please make the text bigger and speak more slowly." Text enlarges, layout holds, speech slows. Flash keyboard/high contrast.
- **55–75s Billing:** sample bill + EOB, highlighted lines and a possible difference, copy a billing-office question; users verify before paying.
- **75–90s Cross-agent:** "Find me a free time to follow up that doesn't interfere with my Monday exam." Real availability if integrated, otherwise the labeled sample schedule; approval checkpoint before any change.

Closing: "Most assistants answer questions. Student Jarvis understands a student's whole day. Jarvis Care makes confusing healthcare information readable, audible, and actionable — so accessible care coordination isn't another chore."

## 11. Definition of done

Runs from documented setup with no dead ends; integrated into Jarvis navigation/orchestration or a documented adapter; deterministic happy path on synthetic data; voice in where available, spoken out, playback controls, text equivalent; keyboard-only and speech-free work; 200% text / 400% zoom / screen-reader labels / contrast tested; evidence and uncertainty shown; no phantom bookings, records, or insurance integrations; user confirms reminders/actions/sharing; follows the Jarvis visual system with the calm-care direction; no secrets in frontend or git; tests and build run and summarized; README documents architecture, contract, and demo controls.

## 12. Expected deliverable

Implement, don't just plan. Inspect the repo, find the smallest safe integration point, ship P0 + tests before P1. Report: what was implemented (working vs mock), paths, how to launch/navigate, how the shared agent routes to the module, needed permissions/keys/integrations, a 90-second demo script, and accessibility checks and results.
