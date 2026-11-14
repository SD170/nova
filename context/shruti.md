# Shruti — context + notes

Owner: Shruti (GitHub: shrutipochiraju-sai)
Proposed role: **Student experience — UI + voice + demo polish**

## Role

Build the interface the judges actually see. Push-to-talk voice, TTS, result cards, approval button, demo polish. Own the live-demo rehearsal.

**Does NOT own:** Tool routing, retrieval internals, OAuth.

## Deliverables

- Web UI (Next.js / React / plain HTML — pick fastest)
- Push-to-talk button → mic → `/transcribe` → `/chat`
- STT: OpenAI Whisper (hosted) or `openai-whisper` local, or Deepgram
- TTS: OpenAI TTS, ElevenLabs, or Cartesia (fast + good voices)
- Result cards:
  - Assignment list card
  - Quiz question card (with "speak answer" button)
  - Weak-topic summary card
  - Approval card (with preview + Approve/Cancel buttons)
- Loading states, error toasts, graceful fallback when backend is slow
- Demo rehearsal + backup video recording

## UI card schema (lock with Saswata in hour 0)

```json
{"type": "assignment_list", "items": [...]}
{"type": "quiz_question", "q": "...", "choices": [...], "source_url": "..."}
{"type": "approval_request", "tool": "create_study_block", "preview": {...}}
{"type": "weak_topics", "topics": [{"name": "...", "mastery": 0.3}]}
```

## Demo script (draft — refine as backend lands)

1. "Jarvis, I have an exam Monday. Am I ready?" → assignment card + topic summary with source links
2. "Quiz me." → quiz card, voice Q, user answers aloud, evaluation card
3. "Schedule revision." → approval card showing proposed calendar block, user approves → success card

## Open questions

- React or vanilla? Vercel deploy or local only?
- Voice: all-in-one API (OpenAI Realtime) or STT + LLM + TTS pipeline?
- Dark mode? Mobile-first or desktop-first for demo?

## Ideas

- 

## Blockers

- Need `/chat` endpoint stub from Saswata ASAP to start integration
- 
