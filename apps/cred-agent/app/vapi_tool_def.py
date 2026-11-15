# Voice tool scaffolding — NOT wired to live Nova yet (per user instruction).

"""Vapi tool definition for the credential-mint voice command.

Not imported by setup_vapi.py yet — intentional. To enable:
  1. Start cred-agent (uvicorn app.main:app --port 9010) — exposed via a
     cloudflare tunnel or the same Nova tunnel.
  2. Add this tool factory to apps/brain/setup_vapi.py tool list, just like
     _check_task_tool():
         from apps.cred_agent.app.vapi_tool_def import mint_credential_tool
         "tools": [_ask_brain_tool(), _check_task_tool(),
                   mint_credential_tool(mint_url=f"{BRAIN_BASE}/ask_brain")] + ...
  3. Add a route on bridge.py that forwards tool_calls.mint_credential args
     to POST ${CRED_AGENT}/mint_credential. Keep the long-running mint in the
     background exactly like /ask_brain — Vapi tool timeout is 30s, Metaplex
     + R2 together take ~4s on devnet but can spike.

Honest trigger phrases NOVA_ROUTER.md should recognize (add once wired):
  - "mint this" / "mint it"
  - "lock this in" / "put this on chain"
  - "make a credential for <thing>"
  - "nft my grades"
"""

from typing import Any


def mint_credential_tool(forwarder_url: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "mint_credential",
            "description": (
                "Lock a Canvas milestone to the blockchain as a signed, "
                "verifiable NFT credential. Captures a screenshot witness via "
                "the browser-agent, uploads to R2, signs with the student's "
                "Ed25519 key, anchors the hash on Solana devnet, and mints a "
                "Metaplex NFT whose URI is the signed credential. Use when "
                "the user says 'mint this', 'lock this in', 'put this on "
                "chain', 'nft my grades', or 'make a credential for X'. "
                "Idempotent by item_key — safe to call twice for the same thing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {
                        "type": "string",
                        "description": (
                            "Dedupe key. Use the Canvas item id if available "
                            "(canvas:assignment:12345), otherwise manual:<slug>."
                        ),
                    },
                    "browser_capture_path": {
                        "type": "string",
                        "description": (
                            "Canvas path to screenshot as witness, e.g. "
                            "'/grades' or '/courses/12345/grades'. Omit for "
                            "no witness."
                        ),
                    },
                    "nft_name": {
                        "type": "string",
                        "description": "Display name (<=32 chars) on the NFT.",
                    },
                },
                "required": [],
            },
            "server": {
                "url": forwarder_url,
                "timeoutSeconds": 30,
            },
            "messages": [
                {
                    "type": "request-start",
                    "content": "Alright, locking this to the chain. Give me a few.",
                },
                {
                    "type": "request-failed",
                    "content": "Hit a snag minting that. Can I try again?",
                },
            ],
        },
    }
