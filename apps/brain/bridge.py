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
import urllib.request
import urllib.error

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

# ────────── filler-phrase classifier ──────────
#
# "Nova is thinking…" is dead air for the user. Instead, as soon as we receive
# a request we emit a SHORT, context-aware acknowledgement *before* Hermes
# spawns. Vapi speaks it while Hermes churns. Pseudo-"thinking out loud".
#
# The classifier picks a filler based on keywords in the user prompt that
# suggest which tool Nova will probably call. Fallback is a generic
# acknowledgement ("mm, one sec") so the user never hears silence.
#
# Skip fillers entirely for trivially short turns ("hi", "yes", "thanks")
# where speaking a filler before the real one-word reply would be awkward.

_FILLER_RULES: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"\b(canvas|assignment|homework|hw\d|exam|quiz|due|grade|class|course|syllabus|lecture|midterm|material|slide|reading|professor)\b", re.I),
     ["let me check Canvas.",
      "pulling up Canvas now.",
      "one sec, checking your classes.",
      "looking at your coursework."]),
    (re.compile(r"\b(schedule|calendar|meeting|appointment|block|free|busy|when)\b", re.I),
     ["pulling up your schedule.",
      "checking your calendar.",
      "let me look at your day."]),
    (re.compile(r"\b(email|inbox|message|unread|reply|draft)\b", re.I),
     ["looking at your inbox.",
      "one sec, checking email."]),
    (re.compile(r"\b(company|recruiter|research|who is|who are|tell me about|about them|background)\b", re.I),
     ["give me a moment to look them up.",
      "one sec, pulling that up."]),
    (re.compile(r"\b(write|draft|cover letter|document|resume|notes?|essay)\b", re.I),
     ["drafting that now.",
      "working on it, one sec."]),
    (re.compile(r"\b(news|updates?|headlines?|happening)\b", re.I),
     ["checking the news.",
      "one sec, pulling updates."]),
    (re.compile(r"\b(remember|memory|note|track|log)\b", re.I),
     ["noted, one sec."]),
]
_FILLER_GENERIC = ["mm, one sec.", "got it.", "okay, give me a second."]
_FILLER_SKIP = re.compile(
    r"^\s*(hi|hey|hello|yo|sup|thanks?|thank\s+you|ok|okay|yep|yeah|no|nope|bye|cool)\b[\s!.?]*$",
    re.I,
)

_filler_turn_counter = 0


def _pick_filler(user_text: str) -> str | None:
    """Return a short spoken ack for this turn, or None if we should stay silent.

    Rotates within each category to avoid "let me check Canvas" every time.
    """
    global _filler_turn_counter
    _filler_turn_counter += 1
    if _FILLER_SKIP.match(user_text or ""):
        return None
    if len(user_text) < 6:
        return None
    for pat, phrases in _FILLER_RULES:
        if pat.search(user_text):
            return phrases[_filler_turn_counter % len(phrases)]
    # Only emit generic filler if the prompt is long enough that a 3s wait
    # would be noticeable (short prompts → short replies → no gap to fill).
    if len(user_text) >= 18:
        return _FILLER_GENERIC[_filler_turn_counter % len(_FILLER_GENERIC)]
    return None

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
    filler: str | None = None,
) -> AsyncIterator[bytes]:
    """Pipe Hermes output straight to Vapi as OpenAI SSE chunks.

    Each line Hermes emits becomes one `delta.content` chunk, so Vapi starts
    TTS on the first spoken sentence instead of waiting for the whole reply.

    If `filler` is set, emit it as the very first SSE chunk BEFORE spawning
    Hermes. Vapi starts TTS on the filler while Hermes is still warming up,
    so the user hears continuous speech instead of a dead-air gap.
    """
    if filler:
        yield _openai_chunk(filler + " ", model).encode()
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

        # Fillers are now Vapi's job (assistant messagePlan.idleMessages +
        # ask_brain tool.messages). Speaking our own here would layer under
        # Vapi's fillers → user hears "got it... one sec... hmm, thinking..."
        # all stacked. Suppressed.
        filler = None

        resp = StreamingResponse(
            _stream_hermes_to_sse(prompted, session, model, _remember, filler=filler),
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


# ────────── /ask_brain: thin-wrapper delegation endpoint ──────────
#
# Vapi's router model (Groq Llama 3.1 8b) calls this as a `function` tool
# whenever it needs a fact. Shape is Vapi's standard tool-call POST:
#
#   { "message": { "toolCalls": [ { "id": "...",
#         "function": { "name": "ask_brain",
#                       "arguments": { "question": "..." } } } ] } }
#
# We extract the question, run it through Hermes (full SOUL.md + MCPs), and
# return Vapi's tool-call result envelope with the brain's reply as `result`.
# Groq then speaks the reply as-is.
#
# Why not go through /chat/completions? That's OpenAI-shape; Vapi tool calls
# are a separate POST shape. Keeping a dedicated endpoint makes the contract
# explicit and lets us skip persona prefix, markdown stripping tuning, etc.

@app.post("/ask_brain")
async def ask_brain(request: Request):
    t_ingress = time.time()
    turn_id = uuid.uuid4().hex[:6]
    body = await request.json()

    # Vapi wraps function tool calls in message.toolCalls
    tool_calls = (body.get("message") or {}).get("toolCalls") or []
    call_id = ((body.get("message") or {}).get("call") or {}).get("id")
    if not tool_calls:
        # Fall back: accept a plain {question: "..."} for curl testing
        q = (body.get("question") or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="missing toolCalls or question")
        tool_calls = [{"id": f"tc-{turn_id}", "function": {"arguments": {"question": q}}}]
        sync_mode = True  # curl probe: wait for Hermes, return the real reply
    else:
        sync_mode = not bool(call_id)
        # If we somehow don't have a call_id from Vapi, fall back to sync so
        # at least the result makes it back via the tool-call channel.

    results = []
    for tc in tool_calls:
        tc_id = tc.get("id") or tc.get("toolCallId") or f"tc-{turn_id}"
        fn = tc.get("function") or {}
        args = fn.get("arguments") or {}
        # Vapi can send arguments as a dict or a JSON string depending on version
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"question": args}
        question = (args.get("question") or "").strip()
        if not question:
            results.append({"toolCallId": tc_id,
                            "result": "I didn't get a question — try again?"})
            continue

        log.info("[t-ask_brain %s] question=%r", turn_id, question[:120])
        prompted = f"[persona: nova]\n{question}"
        if sync_mode:
            # No call_id (curl probe or old Vapi payload) → blocking old behavior
            try:
                reply, _ = await _run_hermes(prompted, resume_session=None)
            except HTTPException as exc:
                log.error("[t-ask_brain %s] hermes error: %s", turn_id, exc.detail)
                reply = "I hit an error reaching that — try again in a sec."
            if not reply:
                reply = "No result from that lookup."
            reply = _cap_reply(reply)
            log.info("[t-ask_brain %s] SYNC reply_len=%d took=%.3fs",
                     turn_id, len(reply), time.time() - t_ingress)
            results.append({"toolCallId": tc_id, "result": reply})
        else:
            # ASYNC: return "on it" immediately; Hermes runs in background;
            # when done, inject the reply into the live Vapi call via /control.
            # Register the task so the router can check status later.
            task = _register_task(call_id, question)
            log.info("[t-ask_brain %s] ASYNC dispatching call_id=%s task=%s",
                     turn_id, call_id, task["id"])
            asyncio.create_task(
                _run_brain_and_inject(turn_id, call_id, task["id"], prompted, question)
            )
            results.append({
                "toolCallId": tc_id,
                # Internal ack. NOT meant to be spoken verbatim — the router
                # already said its own bridge line before firing the tool.
                # This string is kept short + factual so if the model DOES
                # leak it, it sounds like a status line, not a filler.
                "result": f"[queued:{task['id']}]",
            })

    return JSONResponse({"results": results})


# Max chars we'll let into TTS from a single Hermes reply. Longer gets
# truncated at the last sentence boundary before this cap. Keeps turns < ~8s.
_REPLY_CAP = 240


# ────────── background task registry ──────────
# Tracks async Hermes jobs per call so the router can ask 'check_task' instead
# of re-delegating the same question.

_task_counter = 0


def _next_task_id() -> str:
    global _task_counter
    _task_counter += 1
    return f"t{_task_counter:03d}"


# call_id -> list[dict]
_tasks_by_call: dict[str, list[dict]] = {}


def _register_task(call_id: str, question: str) -> dict:
    tid = _next_task_id()
    entry = {
        "id": tid,
        "question": question,
        "status": "running",       # running | done | error
        "started_at": time.time(),
        "finished_at": None,
        "result": None,       # spoken (TTS-capped) text, short
        "result_full": None,  # full Hermes reply, uncapped — shown in the card
    }
    _tasks_by_call.setdefault(call_id, []).append(entry)
    return entry


def _update_task(call_id: str, tid: str,
                 *, status: str, result: str, result_full: str | None = None) -> None:
    for t in _tasks_by_call.get(call_id, []):
        if t["id"] == tid:
            t["status"] = status
            t["finished_at"] = time.time()
            t["result"] = result
            if result_full is not None:
                t["result_full"] = result_full
            return


def _format_tasks_for_speech(call_id: str, which: str | None) -> str:
    tasks = _tasks_by_call.get(call_id, [])
    if not tasks:
        return "No active tasks."
    if which:
        for t in tasks:
            if t["id"] == which:
                return _one_task_line(t)
        return f"No task {which}."
    # Default: summarize most recent
    running = [t for t in tasks if t["status"] == "running"]
    done_unspoken = [t for t in tasks if t["status"] == "done" and not t.get("spoken")]
    if done_unspoken:
        t = done_unspoken[-1]
        t["spoken"] = True
        return f"That {t['question'][:40]!r} just finished: {t['result'][:160]}"
    if running:
        latest = running[-1]
        age = int(time.time() - latest["started_at"])
        return f"Still on '{latest['question'][:40]}' — {age} seconds in."
    # All done & already-spoken
    return "Nothing running right now."


def _one_task_line(t: dict) -> str:
    if t["status"] == "running":
        age = int(time.time() - t["started_at"])
        return f"'{t['question'][:40]}' — running, {age} seconds in."
    if t["status"] == "done":
        return f"'{t['question'][:40]}' — done. {t['result'][:160]}"
    return f"'{t['question'][:40]}' — errored."


def _cap_reply(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _REPLY_CAP:
        return text
    # Cut at the last period/question/exclamation before the cap
    head = text[:_REPLY_CAP]
    for sep in (". ", "? ", "! ", "\n"):
        i = head.rfind(sep)
        if i > 80:   # don't produce a 10-word reply
            return head[: i + 1].strip()
    return head.rstrip() + "…"


async def _run_brain_and_inject(turn_id: str, call_id: str, task_id: str,
                                prompted: str, question: str) -> None:
    """Background worker: run Hermes, then inject the reply into the live call."""
    t0 = time.time()
    status = "done"
    try:
        reply, _ = await _run_hermes(prompted, resume_session=None)
    except HTTPException as exc:
        log.error("[t-ask_brain %s] async hermes error: %s", turn_id, exc.detail)
        reply = "I hit a snag looking that up."
        status = "error"
    except Exception as exc:
        log.exception("[t-ask_brain %s] async hermes crash: %s", turn_id, exc)
        reply = "I hit a snag looking that up."
        status = "error"
    if not reply:
        reply = "Couldn't find anything on that."
    reply_full = reply
    reply = _cap_reply(reply)
    _update_task(call_id, task_id, status=status, result=reply, result_full=reply_full)
    log.info("[t-ask_brain %s] ASYNC done len=%d took=%.3fs q=%r",
             turn_id, len(reply), time.time() - t0, question[:80])
    ok = _vapi_inject_say(call_id, reply)
    log.info("[t-ask_brain %s] inject call_id=%s ok=%s", turn_id, call_id, ok)


VAPI_PRIVATE_KEY = os.environ.get("VAPI_PRIVATE_KEY", "")
VAPI_API_BASE = "https://api.vapi.ai"


# Each live Vapi call has a per-call control URL on a regional WebSocket domain
# (e.g. phone-call-websocket.aws-us-west-2-backend-production2.vapi.ai/<id>/control).
# It's returned as monitor.controlUrl on GET /call/{id}. We fetch and cache once
# per call_id, then POST {type:'say', content:...} to make Nova speak unprompted.
# NOTE: /call/{id}/control on api.vapi.ai is 404 — must use monitor.controlUrl.
_control_url_cache: dict[str, str] = {}


def _fetch_control_url(call_id: str) -> str | None:
    cached = _control_url_cache.get(call_id)
    if cached:
        return cached
    if not VAPI_PRIVATE_KEY:
        return None
    req = urllib.request.Request(
        f"{VAPI_API_BASE}/call/{call_id}",
        headers={
            "Authorization": f"Bearer {VAPI_PRIVATE_KEY}",
            "User-Agent": "nova-bridge/0.3",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        log.error("vapi fetch call %s: %s", call_id, e)
        return None
    url = ((data.get("monitor") or {}).get("controlUrl")
           or data.get("controlUrl"))
    if url:
        _control_url_cache[call_id] = url
    return url


def _vapi_inject_say(call_id: str, content: str) -> bool:
    """Inject an assistant utterance into a live Vapi call.

    Uses the per-call monitor.controlUrl. Returns True on 2xx.
    """
    if not VAPI_PRIVATE_KEY or not call_id or not content:
        return False
    url = _fetch_control_url(call_id)
    if not url:
        log.error("vapi inject: no controlUrl for call %s", call_id)
        return False
    body = json.dumps({
        "type": "say",
        "content": content,
        "endCallAfterSpoken": False,
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "nova-bridge/0.3",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        log.error("vapi inject HTTP %d at %s: %s", e.code, url, e.read()[:300])
        return False
    except Exception as e:
        log.error("vapi inject error at %s: %s", url, e)
        return False


# ────────── /check_task: status lookup tool for the router ──────────

@app.get("/tasks")
async def list_tasks(request: Request):
    """CORS-friendly GET for the Electron UI to poll task state.

    Usage: GET /tasks?call_id=<id>
    Returns: {"tasks": [{id, question, status, result, started_at, finished_at}, ...]}
    Omitting call_id returns the whole registry (dev convenience).
    """
    cid = request.query_params.get("call_id") or ""
    if cid:
        tasks = list(_tasks_by_call.get(cid, []))
    else:
        # Flatten everything (dev)
        tasks = [t for lst in _tasks_by_call.values() for t in lst]
    # Only ship fields the UI needs; drop internal 'spoken' flag.
    public = [{k: t.get(k) for k in
               ("id", "question", "status", "result", "result_full",
                "started_at", "finished_at")}
              for t in tasks]
    resp = JSONResponse({"tasks": public})
    resp.headers["access-control-allow-origin"] = "*"
    return resp


@app.post("/check_task")
async def check_task(request: Request):
    """Vapi function tool. Returns spoken status of pending/recent Hermes tasks.

    Args: optional `task_id` (e.g. 't003'). Without it returns the latest
    relevant task (unspoken-done preferred, else running, else "nothing").
    """
    body = await request.json()
    turn_id = uuid.uuid4().hex[:6]
    tool_calls = (body.get("message") or {}).get("toolCalls") or []
    call_id = ((body.get("message") or {}).get("call") or {}).get("id")

    if not tool_calls:
        # curl fallback: {"call_id": "...", "task_id": "..."}
        cid = body.get("call_id") or ""
        which = body.get("task_id")
        reply = _format_tasks_for_speech(cid, which) if cid else "No call id."
        return JSONResponse({"results": [{"toolCallId": f"tc-{turn_id}",
                                           "result": reply}]})

    results = []
    for tc in tool_calls:
        tc_id = tc.get("id") or tc.get("toolCallId") or f"tc-{turn_id}"
        args = (tc.get("function") or {}).get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        which = args.get("task_id")
        reply = _format_tasks_for_speech(call_id or "", which)
        log.info("[t-check_task %s] call=%s which=%s → %r",
                 turn_id, call_id, which, reply[:120])
        results.append({"toolCallId": tc_id, "result": reply})
    return JSONResponse({"results": results})



if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    log.info("bridge on :%d  profile_home=%s  hermes=%s", port, HERMES_PROFILE_HOME, HERMES_BIN)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
