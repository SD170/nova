# apps/voice

Voice loop for Nova. Mic audio → STT → feeds orchestrator `/chat` → spoken reply.

## Owner

Saswata Dutta (GitHub: SD170)

## Stack decision

- **Demo: Vapi** — sub-500ms end-to-end, turn-taking + barge-in handled, 30 min to wire. Vapi acts as the voice frontend; our orchestrator `/chat` is its backend.
- **Fallback:** OpenAI Whisper (STT) + OpenAI TTS pipeline — ~15 min glue if Vapi free tier is tight.
- **Private / local path (post-hackathon or FERPA deployments):** VoiceStudio (github.com/debpalash/VoiceStudio) — fully local, 646 languages. Not for demo due to latency on laptop under load + AGPL-3.0.

## Vapi MCP (control Vapi from this terminal)

Vapi exposes its APIs as an MCP server at `https://mcp.vapi.ai/mcp` (streamable HTTP, OAuth auth in-browser). Added to `~/.hermes/config.yaml` under `mcp_servers.vapi`.

**Restart Hermes once** so native-MCP picks it up. First tool call triggers OAuth in your browser — sign in with the Vapi account, pick org, done. Session persists.

Once wired, Hermes tools `mcp_vapi_*` are available: create/edit assistants, place calls, manage phone numbers, run simulations, search Vapi docs.

### Auth notes

- No API key goes in config. OAuth only.
- If an older Vapi CLI entry (`@vapi-ai/mcp-docs-server`) exists in config, replace it with the hosted URL above.

## What this app will own

- Vapi assistant config (model = our orchestrator via custom-LLM, voice, first-message, system prompt)
- Vapi → `/chat` glue (if we need custom tool-calls; otherwise Vapi hits orchestrator directly as a custom LLM endpoint)
- Fallback STT+TTS adapter (same interface as Vapi, swappable)
- Voice loop frontend widget (if separate from UI — otherwise lives in `apps/ui`)

## Run locally

TBD once scaffolded.

## Env vars

- `VAPI_PRIVATE_KEY` — only if we end up using the REST API directly instead of MCP. Not needed for MCP (OAuth).
- Secrets go in repo-root `.env` (gitignored), never commit.

## Endpoints / interface

- Vapi assistant will call our orchestrator via its "Custom LLM" integration pointed at `{ORCHESTRATOR_URL}/chat` (OpenAI-compatible shape or raw).

## Status

Scaffold only. Vapi MCP wiring in config, awaiting Hermes restart + OAuth.

## Auto-sync

This repo runs `.git-autosync.sh` locally — pulls teammate changes + pushes mine every 2 min. Ignored by git (not committed).
