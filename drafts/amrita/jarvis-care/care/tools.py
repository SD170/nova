"""Orchestrator / Vapi integration point.

Same signature as the mock tools in apps/voice/server.py (`fn(args: dict) -> dict`),
so the team orchestrator can register the whole health module with:

    from care.tools import HEALTH_TOOLS
    TOOLS.update(HEALTH_TOOLS)

Only one tool is needed — `health_care` routes internally, so the main Jarvis
assistant never has to know the health intents.
"""
from __future__ import annotations

from typing import Any

from .agent import handle
from .models import JarvisCareRequest


def health_care(args: dict[str, Any]) -> dict:
    """Ask Jarvis Care something. args: {utterance, session_id?, intent?, document_ids?, simple_language?}."""
    req = JarvisCareRequest(
        requestId=str(args.get("request_id") or "tool"),
        sessionId=str(args.get("session_id") or "voice-default"),
        source="voice",
        utterance=args.get("utterance") or args.get("message") or "",
        intent=args.get("intent"),
        documentIds=args.get("document_ids"),
        preferences={"simpleLanguage": bool(args.get("simple_language", True)), "speak": True},
    )
    res = handle(req)
    # Shape aligned with the orchestrator draft in context/saswata.md: `speak` + `cards`.
    return {
        "speak": res.spokenSummary,
        "text": res.replyText,
        "cards": [c.model_dump() for c in res.cards],
        "actions": [a.model_dump() for a in res.actions],
        "status": "needs_approval" if any(a.requiresConfirmation for a in res.actions) else "complete",
        "is_mock": res.isMock,
        "intent": res.intent,
    }


HEALTH_TOOLS = {"health_care": health_care}

# Vapi function-tool definition, for create_assistant.py style registration.
VAPI_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "health_care",
        "description": (
            "Jarvis Care: explain after-visit instructions, prepare doctor-visit questions, compare a medical bill "
            "with an insurance EOB, find free time for a follow-up, or change accessibility settings. "
            "Not for diagnosis or medical advice. Speak the returned `speak` text to the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "utterance": {"type": "string", "description": "What the student said, verbatim."},
                "session_id": {"type": "string"},
            },
            "required": ["utterance"],
        },
    },
}
