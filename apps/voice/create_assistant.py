"""Create (or update) the Student Jarvis Vapi assistant via REST.

Usage:
  export WEBHOOK_URL=https://<your-ngrok-domain>/vapi
  python create_assistant.py               # creates (or updates existing by name)
  python create_assistant.py --list        # list current assistants
  python create_assistant.py --delete <id> # delete by id
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

# Load .env from this script's dir
ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

VAPI_KEY = os.environ.get("VAPI_PRIVATE_KEY")
if not VAPI_KEY:
    print("ERROR: VAPI_PRIVATE_KEY missing. Set it in apps/voice/.env", file=sys.stderr)
    sys.exit(2)

VAPI_BASE = "https://api.vapi.ai"
HEADERS = {"Authorization": f"Bearer {VAPI_KEY}", "Content-Type": "application/json"}
ASSISTANT_NAME = "Shruti"


def tool_spec(webhook_url: str) -> list[dict]:
    """Our tool catalog — each one points at our single /vapi webhook."""
    base = {
        "type": "function",
        "server": {"url": webhook_url},
    }

    def fn(name: str, desc: str, params: dict) -> dict:
        return {
            **base,
            "function": {"name": name, "description": desc, "parameters": params},
        }

    obj_params = {"type": "object", "properties": {}, "required": []}

    return [
        fn("get_courses",
           "List the student's current courses.",
           obj_params),
        fn("get_assignments",
           "List upcoming assignments for a course. Omit course_id to list all.",
           {"type": "object",
            "properties": {"course_id": {"type": "string", "description": "e.g. cse310"}},
            "required": []}),
        fn("get_course_materials",
           "List slides / notes / readings for a course.",
           {"type": "object",
            "properties": {"course_id": {"type": "string"}},
            "required": ["course_id"]}),
        fn("generate_exam_quiz",
           "Generate quiz questions grounded in course materials.",
           {"type": "object",
            "properties": {
                "course_id": {"type": "string"},
                "topic_hints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["course_id"]}),
        fn("get_calendar_events",
           "Read the student's calendar between two ISO timestamps.",
           {"type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
            },
            "required": ["start", "end"]}),
        fn("create_study_block",
           "Create a calendar study block (requires approval in UI — this call just drafts).",
           {"type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "title": {"type": "string"},
                "course_id": {"type": "string"},
            },
            "required": ["start", "end", "title"]}),
        fn("set_name",
           "Change the assistant's own name. Call this when the student says 'call yourself X' or 'your name is now X'.",
           {"type": "object",
            "properties": {"name": {"type": "string", "description": "The new name, e.g. 'Max'"}},
            "required": ["name"]}),
    ]


SYSTEM_PROMPT = """You are Shruti — a voice-first assistant for a university student.

The student may give you a different name at any time. If they say something
like "call yourself Max" or "your name is now Priya", call the set_name tool
and start responding to that name immediately.

You help with academic work: checking Canvas for assignments and course materials,
quizzing the student on upcoming exams using their real course content, and
scheduling revision blocks on their calendar.

Rules:
- Do not greet with "Jarvis" or any pop-culture AI name. Use your current name.
- Speak conversationally, one sentence at a time. Students are often walking.
- Prefer calling tools over guessing. If you do not know, call a tool.
- When you need to write to an external service (create_study_block, send emails),
  surface the proposal and wait for explicit "yes" before calling. The UI shows
  an approval card for the student to confirm.
- Every claim about assignments, grades, or course content must trace back to a
  tool result. Never invent exam coverage or due dates.
- Keep responses under 2 sentences unless the student asks for detail.
"""


def assistant_body(webhook_url: str) -> dict:
    return {
        "name": ASSISTANT_NAME,
        "firstMessage": "Hey, I'm Shruti. What do you need?",
        "voice": {"provider": "vapi", "voiceId": "Elliot"},
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "systemPrompt": SYSTEM_PROMPT,
            "tools": tool_spec(webhook_url),
        },
        "transcriber": {"provider": "deepgram", "model": "nova-2", "language": "en"},
        "server": {"url": webhook_url},  # status-update / transcript / end-of-call
        "serverMessages": ["status-update", "end-of-call-report", "transcript"],
    }


def list_assistants() -> list[dict]:
    r = requests.get(f"{VAPI_BASE}/assistant", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def find_by_name(name: str) -> dict | None:
    for a in list_assistants():
        if a.get("name") == name:
            return a
    return None


def create(webhook_url: str) -> dict:
    body = assistant_body(webhook_url)
    r = requests.post(f"{VAPI_BASE}/assistant", headers=HEADERS, json=body, timeout=30)
    if r.status_code >= 400:
        print("CREATE FAILED", r.status_code, r.text, file=sys.stderr)
        r.raise_for_status()
    return r.json()


def update(assistant_id: str, webhook_url: str) -> dict:
    body = assistant_body(webhook_url)
    r = requests.patch(f"{VAPI_BASE}/assistant/{assistant_id}", headers=HEADERS, json=body, timeout=30)
    if r.status_code >= 400:
        print("UPDATE FAILED", r.status_code, r.text, file=sys.stderr)
        r.raise_for_status()
    return r.json()


def delete(assistant_id: str) -> None:
    r = requests.delete(f"{VAPI_BASE}/assistant/{assistant_id}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    print(f"deleted {assistant_id}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true", help="List assistants and exit")
    p.add_argument("--delete", metavar="ID", help="Delete an assistant by id")
    p.add_argument("--webhook", default=os.environ.get("WEBHOOK_URL"),
                   help="Public URL for the voice webhook (default $WEBHOOK_URL)")
    args = p.parse_args()

    if args.list:
        for a in list_assistants():
            print(f"{a.get('id')}  {a.get('name')}  model={(a.get('model') or {}).get('model')}")
        return 0

    if args.delete:
        delete(args.delete)
        return 0

    if not args.webhook:
        print("ERROR: --webhook or $WEBHOOK_URL required (e.g. https://foo.ngrok.app/vapi)", file=sys.stderr)
        return 2

    existing = find_by_name(ASSISTANT_NAME)
    if existing:
        out = update(existing["id"], args.webhook)
        print(f"updated assistant id={out['id']}  webhook={args.webhook}")
    else:
        out = create(args.webhook)
        print(f"created assistant id={out['id']}  webhook={args.webhook}")
    print(f"→ talk to it: https://dashboard.vapi.ai/assistants/{out['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
