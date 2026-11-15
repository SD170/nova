"""Vapi tool-call webhook + server-url handler.

Vapi POSTs every event (tool call, status update, transcript, end-of-call) to
our single endpoint. We log everything loudly, return mock tool results.

Run:  uv run --python 3.11 --with fastapi --with uvicorn python server.py
      (or: python server.py  — if fastapi/uvicorn already installed)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).parent


# Load local .env (secrets) and ../../shared.env (non-secrets) so /config can expose them.
def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


_load_env(HERE / ".env")
_load_env(HERE.parent.parent / "shared.env")


app = FastAPI(title="Student Jarvis voice webhook")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


# ───────────────────────── logging ─────────────────────────

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(tag: str, color: str, msg: str) -> None:
    print(f"{DIM}{ts()}{RESET} {color}{BOLD}[{tag}]{RESET} {msg}", flush=True)


def log_json(tag: str, color: str, obj) -> None:
    body = json.dumps(obj, indent=2, default=str)
    log(tag, color, "")
    for line in body.splitlines():
        print(f"  {DIM}│{RESET} {line}", flush=True)


# ─────────────────────── mock tool registry ───────────────────────
#
# Keep responses small and deterministic. These match the tool contract in
# packages/schemas (see context/saswata.md for the canonical shape).

def _tool_get_courses(args: dict) -> dict:
    return {
        "items": [
            {"id": "cse310", "code": "CSE 310", "name": "Data Structures", "term": "Fall 2026"},
            {"id": "cse355", "code": "CSE 355", "name": "Theory of Computation", "term": "Fall 2026"},
            {"id": "mat243", "code": "MAT 243", "name": "Discrete Math", "term": "Fall 2026"},
        ]
    }


def _tool_get_assignments(args: dict) -> dict:
    course = args.get("course_id") or "cse310"
    return {
        "items": [
            {
                "id": "a1",
                "title": "Homework 3 — AVL Trees",
                "course_id": course,
                "due_at": "2026-11-16T23:59:00",
                "source_url": f"https://canvas.asu.edu/courses/{course}/assignments/a1",
            },
            {
                "id": "a2",
                "title": "Project Milestone 2",
                "course_id": course,
                "due_at": "2026-11-20T23:59:00",
                "source_url": f"https://canvas.asu.edu/courses/{course}/assignments/a2",
            },
        ]
    }


def _tool_get_course_materials(args: dict) -> dict:
    return {
        "items": [
            {"id": "m1", "title": "Lecture 12 slides — Red-Black Trees", "type": "pdf"},
            {"id": "m2", "title": "Lecture 13 slides — Heaps", "type": "pdf"},
        ]
    }


def _tool_generate_exam_quiz(args: dict) -> dict:
    return {
        "items": [
            {
                "id": "q1",
                "q": "What is the worst-case insert complexity for an AVL tree?",
                "type": "short",
                "source_passages": [{"chunk_id": "m1#p3", "text": "AVL insert is O(log n) worst case."}],
            }
        ]
    }


def _tool_get_calendar_events(args: dict) -> dict:
    return {"events": [{"id": "e1", "title": "CSE 310 lecture", "start": "2026-11-15T13:30:00", "end": "2026-11-15T14:45:00", "busy": True}]}


def _tool_create_study_block(args: dict) -> dict:
    return {
        "id": "block_mock_123",
        "html_link": "https://calendar.google.com/mock",
        "note": "MOCK — real write requires user approval in UI; this stub just echoes.",
    }


def _tool_set_name(args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    # Persist to a side-file so the next cold-start remembers. Lightweight.
    (HERE / ".assistant_name").write_text(name)
    return {"ok": True, "name": name, "message": f"Okay, I'll go by {name} from now on."}


TOOLS = {
    "get_courses": _tool_get_courses,
    "get_assignments": _tool_get_assignments,
    "get_course_materials": _tool_get_course_materials,
    "generate_exam_quiz": _tool_generate_exam_quiz,
    "get_calendar_events": _tool_get_calendar_events,
    "create_study_block": _tool_create_study_block,
    "set_name": _tool_set_name,
}


# ───────────────────── Vapi webhook handler ─────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "ts": ts()}


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/config")
async def config():
    """Non-secret config the browser needs to start a Vapi web call.
    Public key is safe to expose; private key stays server-side only.
    """
    return {
        "publicKey": os.environ.get("VAPI_PUBLIC_KEY", ""),
        "assistantId": os.environ.get("VAPI_ASSISTANT_ID", ""),
        "dashboardUrl": os.environ.get("VAPI_DASHBOARD_URL", ""),
    }


@app.post("/vapi")
async def vapi(request: Request):
    """Single webhook — Vapi routes every event here.

    Events we care about:
      - message.type == "tool-calls"             → run tool, return results
      - message.type == "status-update"          → log transcript state
      - message.type == "transcript"             → log live transcript
      - message.type == "end-of-call-report"     → log summary
    """
    body = await request.json()
    message = body.get("message") or {}
    kind = message.get("type") or "unknown"

    if kind == "tool-calls":
        tool_call_list = message.get("toolCallList") or message.get("toolCalls") or []
        log("TOOL-CALLS", MAGENTA, f"{len(tool_call_list)} call(s) incoming")
        results = []
        for call in tool_call_list:
            name = (call.get("function") or {}).get("name") or call.get("name")
            raw_args = (call.get("function") or {}).get("arguments") or call.get("arguments") or {}
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {"_raw": raw_args}
            call_id = call.get("id")

            log("CALL", CYAN, f"{BOLD}{name}{RESET}  args={json.dumps(raw_args, default=str)}")
            fn = TOOLS.get(name)
            if fn is None:
                result = {"error": f"unknown tool: {name}", "available": list(TOOLS.keys())}
                log("MISS", RED, f"no handler for {name}")
            else:
                try:
                    result = fn(raw_args)
                    log("OK  ", GREEN, f"{name} → {json.dumps(result, default=str)[:200]}")
                except Exception as e:
                    result = {"error": str(e)}
                    log("ERR ", RED, f"{name} raised {e}")

            results.append({"toolCallId": call_id, "result": result})
        return JSONResponse({"results": results})

    if kind == "status-update":
        log("STATUS", YELLOW, f"{message.get('status')}  endedReason={message.get('endedReason') or '-'}")
        return JSONResponse({"ok": True})

    if kind == "transcript":
        role = message.get("role", "?")
        transcript_type = message.get("transcriptType", "?")
        text = (message.get("transcript") or "").strip()
        if transcript_type == "final" and text:
            log("TXT ", CYAN if role == "user" else GREEN, f"{role}: {text}")
        return JSONResponse({"ok": True})

    if kind == "end-of-call-report":
        log("END ", YELLOW, "call ended, summary:")
        log_json("SUMMARY", YELLOW, {
            "endedReason": message.get("endedReason"),
            "durationSeconds": message.get("durationSeconds"),
            "summary": message.get("summary"),
            "transcript": (message.get("transcript") or "")[:500],
        })
        return JSONResponse({"ok": True})

    # anything else — log quietly
    log("EVENT", DIM, kind)
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    import uvicorn
    print(f"{BOLD}{CYAN}Student Jarvis voice webhook{RESET} — listening on :7070")
    print(f"Point Vapi assistant.server.url at:  https://<tunnel>/vapi")
    print()
    uvicorn.run(app, host="0.0.0.0", port=7070, log_level="warning")
