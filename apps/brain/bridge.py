"""Vapi ↔ Hermes bridge (lives inside apps/brain/).

Vapi calls this as its "Custom LLM" over OpenAI /v1/chat/completions.
We translate each request to a `hermes chat -q` invocation against the
in-repo `shruti` profile (apps/brain/hermes-home/shruti) and stream the
reply back as OpenAI SSE.

Design choices (see context/saswata.md):
  - Brain profile lives IN the repo, NOT in ~/.hermes/.
    HERMES_HOME is pointed at apps/brain/hermes-home/shruti.
  - One long-lived Hermes session per Vapi call, resumed across turns via
    `-c <name>` so the brain remembers within a call.
  - Persona (jarvis | shruti) is prepended to the user message as
    `[persona: <name>]` and SOUL.md tells the brain to strip + obey it.
  - Subprocess per turn, not a persistent stdio daemon. Cold subprocess startup
    is ~400ms on this machine, acceptable for voice. Trade: simplicity ≫ perf.
    If we ever need sub-200ms, swap to `hermes acp` socket.

Run:
  python3 bridge.py
  # or: uvicorn bridge:app --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

HERE = Path(__file__).parent


def _load_env_file(p: Path) -> None:
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


# Load apps/brain/.env + repo-root shared.env into process env, so the
# Hermes subprocess inherits ANTHROPIC_API_KEY and any shared public URLs.
_load_env_file(HERE / ".env")
_load_env_file(HERE.parent.parent / "shared.env")


# ────────── config ──────────

HERMES_PROFILE_HOME = Path(
    os.environ.get("HERMES_PROFILE_HOME",
                   str(HERE / "hermes-home" / "shruti"))
).expanduser().resolve()
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
MAX_HERMES_SECONDS = int(os.environ.get("MAX_HERMES_SECONDS", "45"))

# ────────── logging ──────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("vapi-bridge")


# ────────── OpenAI-compatible schema (just the fields Vapi sends/expects) ──────────

class ChatMessage(BaseModel):
    role: str                # "system" | "user" | "assistant" | "tool"
    content: str | list | None = None
    name: str | None = None


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    stream: bool = False
    # Vapi-specific passthrough fields we may see: call, assistant, phoneNumber, customer
    # Keep raw request available for metadata extraction.


# ────────── session mapping ──────────
#
# Vapi passes a call id in request metadata; we remember the Hermes session_id
# that Hermes emits on the FIRST turn of a call so we can `-r` resume it on
# subsequent turns. Across calls the brain still remembers everything via its
# memory system (persisted in hermes-home/shruti/memories/).

_sessions_by_call: dict[str, str] = {}


# ────────── persona extraction ──────────
#
# Vapi doesn't natively tell us which assistant called us, so we look at:
#   1. request.assistant.name (if present)
#   2. the first system message (Vapi injects the assistant's system prompt here)
#   3. default = jarvis
#
# The persona token is prepended to the user message so SOUL.md's rule fires.

PERSONA_RE = re.compile(r"\b(jarvis|shruti)\b", re.I)


def _infer_persona(body: dict[str, Any]) -> str:
    # 1. explicit from Vapi's assistant object
    name = (((body.get("call") or {}).get("assistant") or {}).get("name") or
            (body.get("assistant") or {}).get("name") or "")
    m = PERSONA_RE.search(name)
    if m:
        return m.group(1).lower()
    # 2. system-prompt sniff
    for msg in body.get("messages", []):
        if msg.get("role") == "system":
            m = PERSONA_RE.search(str(msg.get("content") or ""))
            if m:
                return m.group(1).lower()
            break
    return "jarvis"


def _extract_call_id(body: dict[str, Any]) -> str:
    call = body.get("call") or {}
    return str(call.get("id") or call.get("callId") or f"nocall-{uuid.uuid4().hex[:8]}")


def _extract_last_user_text(body: dict[str, Any]) -> str:
    messages = body.get("messages") or []
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    (c.get("text") or "") for c in content if isinstance(c, dict)
                ).strip()
    return ""


# ────────── Hermes invocation ──────────

async def _run_hermes(prompt: str, resume_session: str | None) -> tuple[str, str]:
    """Invoke `hermes chat -q` and return (response_text, session_id).

    If `resume_session` is given, use `-r <id>` to continue that session.
    Otherwise start a fresh one; caller stores the returned session_id for next turn.
    """
    env = os.environ.copy()
    env["HERMES_HOME"] = str(HERMES_PROFILE_HOME)
    # -Q strips spinner/banner, outputs only the final response + a session_id line.
    args = [
        HERMES_BIN, "chat",
        "-q", prompt,
        "-Q",
        "--no-restore-cwd",
        "--ignore-rules",       # skip project AGENTS.md pickup — we have SOUL.md
    ]
    if resume_session:
        args += ["-r", resume_session]
    log.info("hermes invoke resume=%s prompt=%r", resume_session or "(new)", prompt[:120])
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=MAX_HERMES_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail=f"hermes turn exceeded {MAX_HERMES_SECONDS}s")
    dt = time.time() - t0

    out = (stdout_b or b"").decode("utf-8", errors="replace").strip()
    err = (stderr_b or b"").decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        log.error("hermes exit=%d stderr=%s", proc.returncode, err[:500])
        raise HTTPException(status_code=502, detail=f"hermes failed: {err[:200] or 'unknown'}")

    # -Q format: trailing line = "session_id: <id>"; everything above = reply
    session_id = ""
    lines = out.splitlines()
    if lines and lines[-1].startswith("session_id:"):
        session_id = lines[-1].split(":", 1)[1].strip()
        reply = "\n".join(lines[:-1]).strip()
    elif len(lines) >= 2 and lines[-2].startswith("session_id:"):
        # sometimes session_id arrives before trailing newline-only line
        session_id = lines[-2].split(":", 1)[1].strip()
        reply = "\n".join(lines[:-2]).strip()
    else:
        reply = out

    log.info("hermes reply len=%d took=%.2fs", len(reply), dt)
    return reply, session_id


# ────────── OpenAI SSE emitter ──────────
#
# Vapi expects streamed chunks when stream=true. Simplest valid shape:
# we emit the whole reply in ONE chunk (TTS still starts as soon as it arrives).
# If judges feel latency, we'll word-chunk instead.

def _openai_chunk(text: str, model: str, *, finish: str | None = None) -> str:
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"content": text} if text else {},
            "finish_reason": finish,
        }],
    }
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_response(reply: str, model: str) -> AsyncIterator[bytes]:
    yield _openai_chunk(reply, model).encode()
    yield _openai_chunk("", model, finish="stop").encode()
    yield b"data: [DONE]\n\n"


# ────────── FastAPI ──────────

app = FastAPI(title="Vapi ↔ Hermes bridge")


@app.get("/health")
async def health():
    return {"ok": True, "profile_home": str(HERMES_PROFILE_HOME), "ts": datetime.now().isoformat()}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    try:
        _ = ChatRequest.model_validate(body)   # shape sanity
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"bad request: {exc}")

    call_id = _extract_call_id(body)
    persona = _infer_persona(body)
    user_text = _extract_last_user_text(body)
    if not user_text:
        raise HTTPException(status_code=400, detail="no user message")

    session = _sessions_by_call.get(call_id)
    prompted = f"[persona: {persona}]\n{user_text}"

    reply, new_session = await _run_hermes(prompted, resume_session=session)
    if new_session and call_id:
        _sessions_by_call[call_id] = new_session
    if not reply:
        reply = "Sorry, I didn't catch that. Could you say it again?"

    model = body.get("model") or "hermes-shruti"
    stream = bool(body.get("stream", False))

    if stream:
        return StreamingResponse(
            _stream_response(reply, model),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"},
        )

    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": reply},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


# Vapi "server url" catch-all — tool calls, status, end-of-call reports.
# For now we only log them. Future: wire tool dispatch, approval cards, etc.
@app.post("/vapi/event")
async def vapi_event(request: Request):
    body = await request.json()
    message = body.get("message") or {}
    kind = message.get("type") or "unknown"
    log.info("vapi event kind=%s", kind)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    log.info("bridge on :%d  profile_home=%s  hermes=%s", port, HERMES_PROFILE_HOME, HERMES_BIN)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
