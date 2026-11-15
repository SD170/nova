"""Set up two Vapi assistants pointing at our Hermes brain:

  Nova   — main assistant, neutral confident voice
  Shruti — student-peer persona, warmer voice

Both use Vapi "Custom LLM" → our Cloudflare tunnel → bridge.py → Hermes.
Transfer between them via Vapi's native transferCall destination.

Idempotent:
  - Existing assistant VAPI_ASSISTANT_ID (currently "Nova") is
    PATCHed in place to become Nova, pointed at the custom LLM.
  - "Shruti student" is created on first run; subsequent runs PATCH by name.

Run:
  cd apps/brain
  python3 setup_vapi.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from pathlib import Path

import urllib.request
import urllib.error

HERE = Path(__file__).parent


def _load_env(p: Path) -> None:
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v


_load_env(HERE / ".env")
_load_env(HERE.parent / "voice" / ".env")   # legacy: VAPI_* lives here
_load_env(HERE.parent.parent / "shared.env")


VAPI_KEY = os.environ.get("VAPI_PRIVATE_KEY", "")
NOVA_ID = os.environ.get("VAPI_ASSISTANT_ID", "")
SHRUTI_ID_ENV = os.environ.get("VAPI_SHRUTI_ASSISTANT_ID", "")
BRAIN_BASE = os.environ.get("PUBLIC_BRAIN_BASE", "").rstrip("/")

if not VAPI_KEY:
    sys.exit("missing VAPI_PRIVATE_KEY (expected in apps/voice/.env)")
if not NOVA_ID:
    sys.exit("missing VAPI_ASSISTANT_ID in shared.env")
if not BRAIN_BASE:
    sys.exit("missing PUBLIC_BRAIN_BASE in shared.env (set via cloudflared tunnel)")

VAPI_API = "https://api.vapi.ai"
HEADERS = {
    "Authorization": f"Bearer {VAPI_KEY}",
    "Content-Type": "application/json",
    "User-Agent": "nova-setup/0.1 (+https://github.com/SD170/student-nova)",
}


def api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{VAPI_API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"HTTP {e.code} on {method} {path}", file=sys.stderr)
        print(body, file=sys.stderr)
        raise


# ─── assistant configs ───────────────────────────────────────────────────

CUSTOM_LLM_URL = f"{BRAIN_BASE}/v1/chat/completions"
ASK_BRAIN_URL = f"{BRAIN_BASE}/ask_brain"

# Router prompt lives in NOVA_ROUTER.md next to this file. Groq gets the slim
# version; deep Canvas/Gmail guidance stays in SOUL.md (Hermes side).
_HERE = pathlib.Path(__file__).parent
NOVA_ROUTER_PROMPT = (_HERE / "NOVA_ROUTER.md").read_text()


def _ask_brain_tool() -> dict:
    """Vapi function tool that delegates fact-lookups to our Hermes brain."""
    return {
        "type": "function",
        "function": {
            "name": "ask_brain",
            "description": (
                "Delegate to Nova's brain for Canvas, Gmail, Calendar, memory, "
                "research, documents, or anything factual about the user's life. "
                "Returns a short spoken reply. Call this BEFORE claiming any fact."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The concise natural-language question to send to the brain.",
                    },
                },
                "required": ["question"],
            },
        },
        "server": {"url": ASK_BRAIN_URL, "timeoutSeconds": 30},
        "messages": [
            # Fires IMMEDIATELY when Nova decides to delegate — hides the ~2-8s Hermes wait.
            # blocking=false so it layers under the real reply when it arrives.
            {"type": "request-start",
             "content": "Give me a moment.",
             "blocking": False},
            # Fires if the brain takes longer than request-start-delayed-millis (default 1s).
            # Rotating phrases via multiple entries isn't supported; Vapi picks one.
            {"type": "request-response-delayed",
             "content": "Almost there.",
             "timingMilliseconds": 7000},
            # Fires if the call to /ask_brain hard-fails.
            {"type": "request-failed",
             "content": "Hit a snag reaching that — try again?"},
        ],
    }


def nova_config(shruti_id: str) -> dict:
    """Patch body for Nova assistant (the main one).

    Architecture: Groq Llama 3.1 8b is the VOICE-FACING ROUTER. Small talk is
    handled directly for sub-second responses. Any factual question delegates
    to Hermes via the `ask_brain` function tool (ASK_BRAIN_URL).
    """
    return {
        "name": "Nova",
        "firstMessage": "Hey, Nova here. What do you need?",
        "voice": {
            "provider": "vapi",
            "voiceId": "Rohan",          # Indian male — warm, confident
        },
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",             # Vapi-native, sub-second router
            "temperature": 0.4,
            "messages": [{
                "role": "system",
                "content": NOVA_ROUTER_PROMPT,
            }],
            "tools": [_ask_brain_tool()] + _transfer_tool(
                shruti_id, "Shruti", "Switching you over to Shruti.",
                "Hand off to Shruti when the user asks for a student perspective "
                "or says 'talk to me as Shruti'.",
            ),
        },
        "endCallFunctionEnabled": False,
        "silenceTimeoutSeconds": 20,
        "maxDurationSeconds": 600,
        # Barge-in: cut off Nova the instant the user says even 1 word.
        # Endpointing: wait longer before firing Hermes if user clearly isn't
        # done talking (no sentence-end punctuation = still thinking).
        "transcriber": {
            "provider": "deepgram", "model": "nova-2", "language": "en-US",
            "endpointing": 400,
            "smartFormat": True,
        },
        "startSpeakingPlan": {
            "waitSeconds": 0.6,
            "smartEndpointingPlan": {"provider": "livekit",
                                     "waitFunction": "200 + 8000 * x"},
            "transcriptionEndpointingPlan": {
                "onPunctuationSeconds": 0.2,
                "onNoPunctuationSeconds": 1.0,
                "onNumberSeconds": 0.5,
            },
        },
        "stopSpeakingPlan": {"numWords": 1, "voiceSeconds": 0.15, "backoffSeconds": 0.8},
        "backgroundDenoisingEnabled": True,
                "responseDelaySeconds": 0.1,
        # Never idle — speak a filler every 6s while thinking/waiting.
        "messagePlan": {
            "idleMessages": [
                "Working on it.",
                "Just a sec.",
                "Hang tight.",
            ],
            "idleTimeoutSeconds": 15,
            "idleMessageMaxSpokenCount": 1,
            "silenceTimeoutMessage": "",
        },
    }


def shruti_config(nova_id: str) -> dict:
    return {
        "name": "Shruti",
        "firstMessage": "Hey hey, it's me, Shruti. What's up?",
        "voice": {
            "provider": "vapi",
            "voiceId": "Rohan",          # Indian male — warm, confident
            "speed": 0.95,
        },
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.6,
            "messages": [{
                "role": "system",
                "content": (
                    NOVA_ROUTER_PROMPT.replace("You are **Nova**", "You are **Shruti**, a fellow student (warmer, more casual than Nova)")
                ),
            }],
            "tools": [_ask_brain_tool()] + _transfer_tool(
                nova_id, "Nova", "Handing you back to Nova.",
                "Hand off to Nova when the user wants formal mode or says 'back to Nova'.",
            ),
        },
        "endCallFunctionEnabled": False,
        "silenceTimeoutSeconds": 20,
        "maxDurationSeconds": 600,
        # Barge-in: cut off Nova the instant the user says even 1 word.
        # Endpointing: wait longer before firing Hermes if user clearly isn't
        # done talking (no sentence-end punctuation = still thinking).
        "transcriber": {
            "provider": "deepgram", "model": "nova-2", "language": "en-US",
            "endpointing": 400,
            "smartFormat": True,
        },
        "startSpeakingPlan": {
            "waitSeconds": 0.6,
            "smartEndpointingPlan": {"provider": "livekit",
                                     "waitFunction": "200 + 8000 * x"},
            "transcriptionEndpointingPlan": {
                "onPunctuationSeconds": 0.2,
                "onNoPunctuationSeconds": 1.0,
                "onNumberSeconds": 0.5,
            },
        },
        "stopSpeakingPlan": {"numWords": 1, "voiceSeconds": 0.15, "backoffSeconds": 0.8},
        "backgroundDenoisingEnabled": True,
                "responseDelaySeconds": 0.1,
        # Never idle — speak a filler every 6s while thinking/waiting.
        "messagePlan": {
            "idleMessages": [
                "Working on it.",
                "Just a sec.",
                "Hang tight.",
            ],
            "idleTimeoutSeconds": 15,
            "idleMessageMaxSpokenCount": 1,
            "silenceTimeoutMessage": "",
        },
    }


def _transfer_tool(_assistant_id: str, _name: str, _message: str, _description: str) -> list:
    """DISABLED: Vapi's transferCall schema here is sensitive and rejecting every
    combination of assistantId/assistantName we've tried (both the 'should not
    exist' and 'resources-validation' errors). Persona switch is not on the
    critical demo path. Ship Nova + Shruti as independent assistants; user picks
    which one to start on the client. Revisit via Vapi squads when time allows.
    """
    return []


# ─── reconcile ───────────────────────────────────────────────────────────

def find_by_name(name: str) -> dict | None:
    rows = api("GET", "/assistant?limit=100")
    if isinstance(rows, list):
        for r in rows:
            if (r.get("name") or "").strip().lower() == name.lower():
                return r
    return None


def upsert(existing: dict | None, cfg: dict, label: str) -> dict:
    if existing:
        existing_id = existing["id"]
        print(f"→ patch {label}: {existing_id}")
        return api("PATCH", f"/assistant/{existing_id}", cfg)
    print(f"→ create {label}")
    return api("POST", "/assistant", cfg)


def main() -> None:
    print(f"brain URL: {CUSTOM_LLM_URL}")

    # Shruti first — Nova needs Shruti's id in its transferCall tool.
    print("\n[Shruti] upserting")
    existing_sh = find_by_name("Shruti")
    # On first creation Shruti doesn't know Nova's id yet; pass NOVA_ID (always set).
    shruti = upsert(existing_sh, shruti_config(NOVA_ID), "Shruti")
    print(f"  id: {shruti['id']}  voice: {shruti.get('voice', {}).get('voiceId')}")

    # Nova: patch the existing assistant, now that Shruti has a real id.
    print(f"\n[Nova] patching existing VAPI_ASSISTANT_ID={NOVA_ID}")
    nova = api("PATCH", f"/assistant/{NOVA_ID}", nova_config(shruti["id"]))
    print(f"  name: {nova.get('name')}  voice: {nova.get('voice', {}).get('voiceId')}")

    print("\nWrite these to shared.env:")
    print(f"VAPI_ASSISTANT_ID={nova['id']}            # Nova (main)")
    print(f"VAPI_SHRUTI_ASSISTANT_ID={shruti['id']}  # Shruti (student persona)")


if __name__ == "__main__":
    main()
