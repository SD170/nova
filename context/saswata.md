# Saswata — context + notes

Owner: Saswata Dutta (GitHub: SD170)
Proposed role: **Agent orchestrator + tool router + /chat API** (backend brain)

## Role

Decides what tool to call, manages conversation state, enforces the approval gate for external writes, returns structured responses for UI to render.

**Does NOT own:** Canvas internals, quiz logic, UI/voice.

## Deliverables

- `/chat` endpoint (REST or WebSocket)
- Tool registry + router
- Multi-step workflow engine (plan → call → observe → compose)
- Conversation state store
- Approval gate: any tool flagged `requires_approval` pauses, emits approval card, resumes on user confirm
- Structured JSON response shape for UI

## Interface contract (lock in hour 0)

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

(write as I think of them, commit)

- 

## Decisions I'm making

(log each decision with timestamp as I go)

- 

## Blockers

- 
