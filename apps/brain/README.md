# apps/brain — Nova brain + Vapi bridge

Self-contained thinking stack. Vapi calls `bridge.py` as a Custom LLM; it spawns Hermes against the **in-repo** profile at `hermes-home/default/`. Same brain serves two voice personas: **Nova** (main assistant) and **Shruti** (student peer).

## Layout

```
apps/brain/
├── bridge.py                ← FastAPI OpenAI-shim → spawns hermes
├── requirements.txt
├── .env.example             ← committed template
├── .env                     ← your keys, gitignored
└── hermes-home/
    └── default/
        ├── config.yaml      ← committed: model, persona policy, approvals
        ├── SOUL.md          ← committed: Nova + Shruti persona rules
        ├── profile.yaml     ← committed: Hermes metadata
        ├── skills/          ← committed: shared skill templates (empty for now)
        └── (runtime dirs)   ← gitignored: memories, sessions, logs, cache
```

## Run

```bash
cd apps/brain
cp .env.example .env            # edit, paste your Anthropic key
pip install -r requirements.txt
python3 bridge.py               # :8000 by default
```

Verify: `curl http://127.0.0.1:8000/health`

## Env vars

| Var | Default | What |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **required**; passed to the Hermes subprocess |
| `PORT` | `8000` | bridge listen port |
| `HERMES_PROFILE_HOME` | `./hermes-home/default` | profile root (don't change unless you know why) |
| `HERMES_BIN` | `hermes` | path to `hermes` CLI |
| `MAX_HERMES_SECONDS` | `45` | fail-fast on stalled turns |

## How it works

1. Vapi sends OpenAI `/v1/chat/completions` → `bridge.py`
2. Bridge extracts persona from Vapi's assistant name (or system prompt), prepends `[persona: nova]` or `[persona: shruti]` to the user message
3. Bridge spawns `hermes chat -q "..."` with `HERMES_HOME=./hermes-home/default`; first turn creates a session, subsequent turns resume via `-r <session_id>`
4. Hermes reads `SOUL.md`, obeys persona rule, calls tools, writes memory
5. Bridge streams response back to Vapi as OpenAI SSE
6. Vapi TTS speaks it; the Electron avatar animates from Vapi events

## Personas

Both Nova and Shruti are the **same brain, same memory, same tools**. Only voice + tone differ. Persona-switch is handled at the Vapi layer via `transferCall` between two Vapi assistants, both pointing at this same bridge.

## Why Hermes-the-brain lives in the repo

- Teammates `git pull` → brain config is already there, no `~/.hermes/` setup step
- Your personal `~/.hermes/default` stays untouched
- Future Maritime deployment ships the profile with the container
