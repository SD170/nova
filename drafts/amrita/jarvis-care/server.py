"""Jarvis Care server — accessible health module for Student Jarvis.

Run:   python server.py            (http://localhost:7080/health)
Tests: python -m pytest

Serves the UI at /health/* and a JSON API at /api/health/*. All state is
in memory per session. No health data is logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from care import agent, after_visit, bills, documents, scheduling, visit_prep
from care.models import JarvisCareRequest, JarvisCareResponse, TimeWindow
from care.session import STORE
from care.tools import HEALTH_TOOLS

HERE = Path(__file__).parent
STATIC = HERE / "static"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(HERE / ".env")
_load_env(HERE.parent.parent / "shared.env")

app = FastAPI(title="Jarvis Care", docs_url="/api/health/docs", openapi_url="/api/health/openapi.json")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ───────────────────────── pages ─────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/health")


@app.get("/health", include_in_schema=False)
@app.get("/health/{page:path}", include_in_schema=False)
async def page(page: str = ""):
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health/ping")
async def ping():
    return {"ok": True}


@app.get("/api/health/config")
async def config():
    return {
        "jarvisHomeUrl": os.environ.get("JARVIS_HOME_URL", "http://localhost:7070/"),
        "engine": "rules",
        "llmConnected": False,
        "calendarConnected": False,
        "demoToday": scheduling.DEMO_TODAY.isoformat(),
    }


# ───────────────────────── agent ─────────────────────────

@app.post("/api/health/handle", response_model=JarvisCareResponse)
async def handle(req: JarvisCareRequest):
    return agent.handle(req)


# ───────────────────────── documents ─────────────────────────

class SessionBody(BaseModel):
    sessionId: str = "default"


@app.get("/api/health/samples")
async def samples():
    return {"items": documents.list_samples()}


def _get_doc(session_id: str, doc_id: str) -> documents.Document:
    s = STORE.get(session_id)
    d = s.docs.get(doc_id) or documents.load_sample(doc_id)
    if not d:
        raise HTTPException(404, "I couldn't find that document. It may have been cleared — please choose it again.")
    return d


@app.get("/api/health/documents/{doc_id}")
async def get_document(doc_id: str, sessionId: str = "default"):
    d = _get_doc(sessionId, doc_id)
    return {**d.summary(), "pages": d.pages}


@app.post("/api/health/documents")
async def upload(file: UploadFile = File(...), sessionId: str = Form("default"), kind: Optional[str] = Form(None)):
    data = await file.read()
    try:
        d = documents.extract_upload(file.filename or "upload", file.content_type or "", data)
    except documents.UploadError as e:
        raise HTTPException(422, str(e))
    if kind in ("afterVisit", "bill", "eob"):
        d.type = kind
    agent.register_doc(STORE.get(sessionId), d)
    return d.summary()


class PasteBody(SessionBody):
    text: str
    name: str = "Pasted text"
    kind: Optional[str] = None


@app.post("/api/health/documents/paste")
async def paste(body: PasteBody):
    try:
        d = documents.from_pasted_text(body.text, body.name)
    except documents.UploadError as e:
        raise HTTPException(422, str(e))
    if body.kind in ("afterVisit", "bill", "eob"):
        d.type = body.kind
    agent.register_doc(STORE.get(body.sessionId), d)
    return d.summary()


# ───────────────────────── care plan ─────────────────────────

class CarePlanBody(SessionBody):
    documentId: str


@app.post("/api/health/care-plan")
async def care_plan(body: CarePlanBody):
    s = STORE.get(body.sessionId)
    d = _get_doc(body.sessionId, body.documentId)
    d.type = "afterVisit"
    agent.register_doc(s, d)
    plan = after_visit.extract(d)
    s.plan = plan
    s.pending = {"type": "offer_read_tasks"} if plan.followups else None
    spoken = after_visit.spoken_overview(plan)
    s.last_spoken = spoken
    return {
        "document": d.summary(),
        "visitDate": plan.visit_date.isoformat() if plan.visit_date else None,
        "followups": [c.model_dump() for c in plan.followups],
        "care": [c.model_dump() for c in plan.care],
        "warnings": [c.model_dump() for c in plan.warnings],
        "clarifications": [c.model_dump() for c in plan.clarifications],
        "spokenSummary": spoken,
        "readAllText": after_visit.spoken_details(plan, simple=False),
        "isMock": d.synthetic,
    }


class ReminderBody(SessionBody):
    title: str
    dueDate: Optional[str] = None
    sourceCardId: Optional[str] = None
    approved: bool = False


@app.post("/api/health/reminders")
async def create_reminder(body: ReminderBody):
    if not body.approved:
        raise HTTPException(400, "A reminder is only saved after you confirm it.")
    if not body.title.strip():
        raise HTTPException(422, "Please give the reminder a name.")
    s = STORE.get(body.sessionId)
    r = s.add_reminder(body.title.strip()[:300], body.dueDate, body.sourceCardId)
    if s.pending and s.pending.get("type") in ("confirm_reminder", "offer_reminder"):
        s.pending = None
    return r.as_dict()


@app.get("/api/health/reminders")
async def list_reminders(sessionId: str = "default"):
    return {"items": [r.as_dict() for r in STORE.get(sessionId).reminders]}


@app.delete("/api/health/reminders/{rid}")
async def delete_reminder(rid: str, sessionId: str = "default"):
    s = STORE.get(sessionId)
    s.reminders = [r for r in s.reminders if r.id != rid]
    return {"ok": True}


# ───────────────────────── bills ─────────────────────────

class BillBody(SessionBody):
    billId: Optional[str] = None
    eobId: Optional[str] = None


@app.post("/api/health/bills/compare")
async def compare_bills(body: BillBody):
    s = STORE.get(body.sessionId)
    bill_doc = _get_doc(body.sessionId, body.billId) if body.billId else None
    eob_doc = _get_doc(body.sessionId, body.eobId) if body.eobId else None
    if not bill_doc and not eob_doc:
        raise HTTPException(422, "Please choose a bill, an insurance statement, or the demo pair.")
    for d, role in ((bill_doc, "bill"), (eob_doc, "eob")):
        if d:
            d.type = role
            agent.register_doc(s, d)
    cmp = bills.compare(bill_doc, eob_doc)
    s.bill_questions = cmp.questions
    if cmp.complete and (cmp.mismatch_count or cmp.more_info_count):
        spoken = ("There may be a difference between these two documents. "
                  "I'll show you the matching charges and questions to ask before paying.")
    elif cmp.complete:
        spoken = "The lines I could compare match between the two documents."
    else:
        spoken = cmp.cards[0].description
    s.last_spoken = spoken
    return {
        "complete": cmp.complete,
        "rows": cmp.rows,
        "cards": [c.model_dump() for c in cmp.cards],
        "questions": cmp.questions,
        "arithmetic": cmp.arithmetic,
        "mismatchCount": cmp.mismatch_count,
        "moreInfoCount": cmp.more_info_count,
        "glossary": [{"term": t, "meaning": m} for t, m in bills.GLOSSARY],
        "howToVerify": bills.HOW_TO_VERIFY,
        "spokenSummary": spoken,
        "isMock": any(d.synthetic for d in (bill_doc, eob_doc) if d),
    }


# ───────────────────────── visit prep ─────────────────────────

class CheckinBody(SessionBody):
    text: str = ""
    sleep: Optional[str] = None
    energy: Optional[str] = None
    stress: Optional[str] = None


@app.post("/api/health/checkins")
async def checkin(body: CheckinBody):
    if not (body.text.strip() or body.sleep or body.energy or body.stress):
        raise HTTPException(422, "Add a note or pick at least one answer before saving.")
    n = STORE.get(body.sessionId).add_note(body.text[:2000], body.sleep, body.energy, body.stress)
    return n.as_dict()


@app.get("/api/health/visit-prep")
async def get_prep(sessionId: str = "default"):
    p = visit_prep.build(STORE.get(sessionId))
    return {**p, "cards": [c.model_dump() for c in p["cards"]],
            "notes": [n.as_dict() for n in STORE.get(sessionId).notes]}


class QuestionsBody(SessionBody):
    questions: list[str]


@app.put("/api/health/visit-prep/questions")
async def put_questions(body: QuestionsBody):
    s = STORE.get(body.sessionId)
    s.questions = [q.strip()[:500] for q in body.questions if q.strip()][:30]
    return {"questions": s.questions}


@app.get("/api/health/visit-prep/export")
async def export_prep(sessionId: str = "default"):
    return PlainTextResponse(
        visit_prep.as_text(STORE.get(sessionId)),
        headers={"Content-Disposition": 'attachment; filename="my-visit-notes.txt"'},
    )


# ───────────────────────── appointments ─────────────────────────

class SuggestBody(SessionBody):
    useDemoSchedule: bool = False
    availability: list[TimeWindow] = []


@app.post("/api/health/appointments/suggest")
async def suggest(body: SuggestBody):
    s = STORE.get(body.sessionId)
    if body.availability:
        slots, notes, source, demo = scheduling.suggest_from_windows(body.availability), [], "the times you entered", False
    elif body.useDemoSchedule:
        slots, notes = scheduling.suggest_from_schedule(scheduling.load_demo_schedule(), avoid_exam_days=True)
        source, demo = "Sam's demo schedule", True
    else:
        raise HTTPException(422, "Enter the times you're free, or choose the demo schedule.")
    s.last_slots = [sl.as_dict() for sl in slots]
    s.pending = {"type": "choose_slot"} if slots else None
    events = scheduling.load_demo_schedule()["events"] if body.useDemoSchedule and not body.availability else []
    if slots:
        spoken = " ".join(notes) + f" Your first free time is {slots[0].label()}. These are your free times, not clinic openings."
    else:
        spoken = "I couldn't find an hour of free time. Try adding more free times."
    s.last_spoken = spoken.strip()
    return {"slots": s.last_slots, "notes": notes, "source": source, "isMock": demo,
            "busy": events, "spokenSummary": spoken.strip()}


class PlanBody(SessionBody):
    slot: dict[str, Any]
    approved: bool = False


@app.post("/api/health/appointments/plan")
async def plan_visit(body: PlanBody):
    if not body.approved:
        raise HTTPException(400, "Nothing is planned until you confirm.")
    if not {"start", "end", "label"} <= body.slot.keys():
        raise HTTPException(422, "That time is missing details. Please choose it again.")
    from care.session import PlannedVisit
    import uuid

    s = STORE.get(body.sessionId)
    v = PlannedVisit(id=f"visit-{uuid.uuid4().hex[:8]}", start=str(body.slot["start"]),
                     end=str(body.slot["end"]), label=str(body.slot["label"]))
    s.visits.append(v)
    s.pending = None
    return v.as_dict()


# ───────────────────────── timeline + privacy ─────────────────────────

@app.get("/api/health/timeline")
async def get_timeline(sessionId: str = "default", academics: bool = False):
    return {"items": visit_prep.timeline(STORE.get(sessionId), include_academics=academics)}


@app.delete("/api/health/session/{session_id}")
async def clear(session_id: str):
    STORE.clear(session_id)
    return {"ok": True, "message": "Your Jarvis Care data for this session was deleted from the server."}


# ───────────────────────── orchestrator / Vapi tool webhook ─────────────────────────

@app.post("/api/health/tools")
async def tools_webhook(request: Request):
    """Vapi-style tool-calls webhook (same envelope as apps/voice/server.py /vapi)."""
    body = await request.json()
    message = body.get("message") or {}
    calls = message.get("toolCallList") or message.get("toolCalls") or []
    results = []
    for call in calls:
        fn_info = call.get("function") or {}
        name = fn_info.get("name") or call.get("name")
        args = fn_info.get("arguments") or call.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"utterance": args}
        fn = HEALTH_TOOLS.get(name)
        result = fn(args) if fn else {"error": f"unknown tool: {name}", "available": list(HEALTH_TOOLS)}
        results.append({"toolCallId": call.get("id"), "result": result})
    return JSONResponse({"results": results})


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("HEALTH_PORT", "7080"))
    print(f"Jarvis Care running at http://localhost:{port}/health")
    uvicorn.run(app, host=os.environ.get("HEALTH_HOST", "127.0.0.1"), port=port, log_level="warning")
