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
  - Persona (nova | shruti) is prepended to the user message as
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
                   str(HERE / "hermes-home" / "default"))
).expanduser().resolve()
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
MAX_HERMES_SECONDS = int(os.environ.get("MAX_HERMES_SECONDS", "45"))

# ────────── logging ──────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s | %(message)s",
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
#   3. default = nova
#
# The persona token is prepended to the user message so SOUL.md's rule fires.

PERSONA_RE = re.compile(r"\b(nova|shruti)\b", re.I)

# TTS-unfriendly markdown. We strip before handing text to Vapi so Elliot/Savannah
# don't say "double asterisk" or "pound pound" out loud.
_MD_HEADER   = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_MD_BOLDITAL = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}")
_MD_UNDERITL = re.compile(r"_{1,3}([^_\n]+?)_{1,3}")
_MD_CODEFENC = re.compile(r"```[^\n]*\n?|```")
_MD_INLINEC  = re.compile(r"`([^`\n]+?)`")
_MD_BULLET   = re.compile(r"^\s*[-*+]\s+", re.M)
_MD_LINK     = re.compile(r"\[([^\]]+?)\]\([^)]+?\)")

def _strip_markdown_for_tts(text: str) -> str:
    if not text or not any(c in text for c in "*_`#[-"):
        return text
    t = text
    t = _MD_CODEFENC.sub("", t)
    t = _MD_LINK.sub(r"\1", t)
    t = _MD_INLINEC.sub(r"\1", t)
    t = _MD_HEADER.sub("", t)
    t = _MD_BOLDITAL.sub(r"\1", t)
    t = _MD_UNDERITL.sub(r"\1", t)
    t = _MD_BULLET.sub("", t)
    return t.strip()


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
    return "nova"


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
    """Collect the full Hermes reply (used for non-streaming callers).

    Internally reuses the streaming path, so there's one code path for Hermes I/O.
    """
    chunks: list[str] = []
    session_id = ""
    async for kind, payload in _run_hermes_stream(prompt, resume_session):
        if kind == "chunk":
            chunks.append(payload)
        elif kind == "session":
            session_id = payload
    return "".join(chunks).strip(), session_id


_WARN_PREFIXES = ("⚠", "WARNING", "warning:", "Warning:")


async def _run_hermes_stream(
    prompt: str, resume_session: str | None
) -> AsyncIterator[tuple[str, str]]:
    """Spawn Hermes and yield ("chunk", text) tokens as they arrive.

    When the subprocess ends we also yield ("session", session_id) if Hermes
    emitted a trailing `session_id: <id>` line.

    Behavior preserved from the old blocking path:
      - Leading `⚠ tirith …` / `WARNING:` lines are dropped (never spoken).
      - Markdown is stripped so TTS doesn't read ** / ## / - / ` literally.
      - Hermes exit != 0 → HTTP 502.
      - Trailing `session_id: <id>` line is extracted (not spoken).
    """
    env = os.environ.copy()
    env["HERMES_HOME"] = str(HERMES_PROFILE_HOME)
    args = [
        HERMES_BIN, "chat",
        "-q", prompt,
        "-Q",
        "--no-restore-cwd",
        "--ignore-rules",
    ]
    if resume_session:
        args += ["-r", resume_session]
    log.info("[t-hermes] launch resume=%s prompt=%r", resume_session or "(new)", prompt[:80])
    t_launch = time.time()
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    log.info("[t-hermes] spawned pid=%s in %.3fs", proc.pid, time.time() - t_launch)

    stdout = proc.stdout
    assert stdout is not None
    # Line-buffered streaming with a dropped-warning guard that only fires at
    # the start of the reply. Session_id is sniffed from the last line.
    past_warnings = False
    first_chunk_logged = False
    buffered_last: str | None = None  # last line held back in case it's session_id
    session_id = ""

    try:
        while True:
            try:
                raw = await asyncio.wait_for(stdout.readline(), timeout=MAX_HERMES_SECONDS)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise HTTPException(status_code=504, detail=f"hermes turn exceeded {MAX_HERMES_SECONDS}s")
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace")
            # Drop leading warning lines
            if not past_warnings:
                stripped = line.lstrip()
                if stripped == "" or any(stripped.startswith(p) for p in _WARN_PREFIXES):
                    continue
                past_warnings = True
            # Hold the previous line until we see what comes after it. If the
            # NEXT line turns out to be `session_id:`, the held one was the
            # last real content; if not, flush the held one and buffer this one.
            if buffered_last is not None:
                flushed = _strip_markdown_for_tts(buffered_last)
                if flushed:
                    if not first_chunk_logged:
                        log.info("[t-hermes] first-chunk at %.3fs", time.time() - t_launch)
                        first_chunk_logged = True
                    yield ("chunk", flushed)
                buffered_last = None
            if line.startswith("session_id:"):
                session_id = line.split(":", 1)[1].strip()
                continue
            buffered_last = line
        # End of stream: flush remaining buffered line (if any)
        if buffered_last is not None:
            flushed = _strip_markdown_for_tts(buffered_last)
            if flushed:
                if not first_chunk_logged:
                    log.info("[t-hermes] first-chunk at %.3fs", time.time() - t_launch)
                yield ("chunk", flushed)

        rc = await proc.wait()
        dt = time.time() - t_launch
        if rc != 0:
            err = (await proc.stderr.read() if proc.stderr else b"").decode(errors="replace")[:500]
            log.error("hermes exit=%d stderr=%s", rc, err)
            raise HTTPException(status_code=502, detail=f"hermes failed: {err[:200] or 'unknown'}")
        log.info("[t-hermes] total=%.3fs", dt)
        if session_id:
            yield ("session", session_id)
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


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


async def _stream_hermes_to_sse(
    prompt: str,
    resume_session: str | None,
    model: str,
    on_session_id,
) -> AsyncIterator[bytes]:
    """Pipe Hermes output straight to Vapi as OpenAI SSE chunks.

    Each line Hermes emits becomes one `delta.content` chunk, so Vapi starts
    TTS on the first spoken sentence instead of waiting for the whole reply.
    """
    async for kind, payload in _run_hermes_stream(prompt, resume_session):
        if kind == "chunk":
            yield _openai_chunk(payload + "\n", model).encode()
        elif kind == "session":
            on_session_id(payload)
    yield _openai_chunk("", model, finish="stop").encode()
    yield b"data: [DONE]\n\n"


# ────────── FastAPI ──────────

app = FastAPI(title="Vapi ↔ Hermes bridge")


@app.get("/health")
async def health():
    return {"ok": True, "profile_home": str(HERMES_PROFILE_HOME), "ts": datetime.now().isoformat()}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _chat(request)


# Vapi "Custom LLM" appends /chat/completions to the configured base URL,
# not /v1/chat/completions. Mount an alias so both work.
@app.post("/chat/completions")
async def chat_completions_alias(request: Request):
    return await _chat(request)


async def _chat(request: Request):
    t_ingress = time.time()
    turn_id = uuid.uuid4().hex[:6]
    body = await request.json()
    t_parsed = time.time()
    try:
        _ = ChatRequest.model_validate(body)   # shape sanity
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"bad request: {exc}")

    call_id = _extract_call_id(body)
    persona = _infer_persona(body)
    user_text = _extract_last_user_text(body)
    if not user_text:
        raise HTTPException(status_code=400, detail="no user message")

    log.info("[t-turn %s] ingress call=%s persona=%s text=%r body_parse=%.3fs",
             turn_id, call_id[:8], persona, user_text[:60], t_parsed - t_ingress)

    session = _sessions_by_call.get(call_id)
    prompted = f"[persona: {persona}]\n{user_text}"

    model = body.get("model") or "hermes-shruti"
    stream = bool(body.get("stream", False))

    if stream:
        # Streaming path: pipe Hermes stdout → Vapi as it arrives. First token
        # reaches Vapi (and TTS) as soon as Hermes writes its first line,
        # which can be ~2s earlier than "wait for full reply".
        def _remember(sid: str) -> None:
            if sid and call_id:
                _sessions_by_call[call_id] = sid

        resp = StreamingResponse(
            _stream_hermes_to_sse(prompted, session, model, _remember),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"},
        )
        log.info("[t-turn %s] bridge→stream opened at %.3fs", turn_id, time.time() - t_ingress)
        return resp

    # Non-streaming: block, return single JSON (used by curl tests + fallback).
    t_prehermes = time.time()
    reply, new_session = await _run_hermes(prompted, resume_session=session)
    t_posthermes = time.time()
    if new_session and call_id:
        _sessions_by_call[call_id] = new_session
    if not reply:
        reply = "Sorry, I didn't catch that. Could you say it again?"
    log.info("[t-turn %s] hermes_leg=%.3fs reply_len=%d",
             turn_id, t_posthermes - t_prehermes, len(reply))

    resp = JSONResponse({
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
    log.info("[t-turn %s] total_bridge=%.3fs → JSON", turn_id, time.time() - t_ingress)
    return resp


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
