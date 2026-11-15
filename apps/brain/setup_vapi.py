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


def nova_config(shruti_id: str) -> dict:
    """Patch body for Nova assistant (the main one)."""
    return {
        "name": "Nova",
        "firstMessage": "Hey, Nova here. What do you need?",
        "voice": {
            "provider": "vapi",
            "voiceId": "Elliot",         # calm, confident, neutral
        },
        "model": {
            "provider": "custom-llm",
            "url": BRAIN_BASE,           # Vapi appends /chat/completions
            "model": "nova",
            "temperature": 0.4,
            "messages": [{
                "role": "system",
                "content": (
                    "You are Nova, the user's main AI assistant on a voice call. "
                    "Direct, warm, confident. Keep replies short and conversational — one or two sentences unless asked. "
                    "The user's note shows up as the user turn; respond as Nova."
                ),
            }],
            "tools": _transfer_tool(shruti_id, "Shruti", "Switching you over to Shruti.",
                                    "Hand off to Shruti when the user asks for a student perspective "
                                    "or says 'talk to me as Shruti'."),
        },
        "transcriber": {"provider": "deepgram", "model": "nova-2", "language": "en-US"},
        "endCallFunctionEnabled": False,
        "silenceTimeoutSeconds": 20,
        "maxDurationSeconds": 600,
    }


def shruti_config(nova_id: str) -> dict:
    return {
        "name": "Shruti",
        "firstMessage": "Hey hey, it's me, Shruti. What's up?",
        "voice": {
            "provider": "vapi",
            "voiceId": "Savannah",       # warmer, friendly (new-gen Vapi voice)
            "speed": 0.95,
        },
        "model": {
            "provider": "custom-llm",
            "url": BRAIN_BASE,
            "model": "shruti",
            "temperature": 0.6,
            "messages": [{
                "role": "system",
                "content": (
                    "You are Shruti, a fellow student. Warmer and more casual than Nova. "
                    "Use 'we' where it fits ('we've got that exam Monday'). "
                    "Keep it short — one or two sentences unless asked. "
                    "The user turn is the student talking; respond as Shruti."
                ),
            }],
            "tools": _transfer_tool(nova_id, "Nova", "Handing you back to Nova.",
                                    "Hand off to Nova when the user wants formal mode or says 'back to Nova'."),
        },
        "transcriber": {"provider": "deepgram", "model": "nova-2", "language": "en-US"},
        "endCallFunctionEnabled": False,
        "silenceTimeoutSeconds": 20,
        "maxDurationSeconds": 600,
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
