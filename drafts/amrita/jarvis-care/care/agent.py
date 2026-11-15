"""Jarvis Care health agent: handle(request) -> JarvisCareResponse.

Deterministic rules engine (engine="rules"). No LLM is called, so the demo is
repeatable and works offline. Every external-looking effect (reminder, planned
visit) needs an explicit "confirm"; nothing is booked or sent anywhere.
"""
from __future__ import annotations

import re
from typing import Optional

from . import after_visit, bills, documents, scheduling
from .models import Action, Card, JarvisCareRequest, JarvisCareResponse
from .session import STORE, Session

TEXT_SCALES = [1.0, 1.25, 1.5, 2.0]
TEXT_SCALE_NAMES = {1.0: "normal", 1.25: "large", 1.5: "extra large", 2.0: "200 percent"}
RATE_MIN, RATE_MAX, RATE_STEP = 0.75, 1.5, 0.25

YES = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok|okay|please|go ahead|do it|sounds good|confirm|confirmed|save it|that works|absolutely|of course)\b", re.I)
NO = re.compile(r"^\s*(no|nope|not now|no thanks|cancel|never mind|nevermind)\b", re.I)
CONFIRM = re.compile(r"\b(confirm|confirmed|save it|yes,? save|yes)\b", re.I)

EMERGENCY = re.compile(
    r"\b(chest pain|can'?t breathe|cannot breathe|trouble breathing|overdos\w*|unconscious|passed out|"
    r"bleeding (?:a lot|heavily|badly)|seizure|stroke|heart attack|emergency)\b", re.I)
SELF_HARM = re.compile(r"\b(suicid\w*|kill myself|end my life|self[- ]harm|hurt myself|want to die)\b", re.I)
MEDICAL_ADVICE = re.compile(
    r"\b(should i take|how much .{0,20}(take|should)|what dose|dosage|is (?:it|this) serious|"
    r"do i have (?!to\b)|diagnos\w*|what'?s wrong with me|should i stop taking|can i stop taking)\b", re.I)

INTENT_PATTERNS: dict[str, re.Pattern] = {
    "health.accessibility": re.compile(
        r"\b(bigger|larger|enlarge|zoom|can'?t (?:read|see)|hard to read|smaller|slow(?:er|ly| down)|"
        r"speak (?:more )?slow|fast(?:er)?|speed up|high contrast|contrast|dark mode|light mode|simple language|"
        r"simpler|plain language|detailed|more detail|mute|stop talking|be quiet|turn (?:off|on) (?:voice|speech))\b", re.I),
    "health.parseAfterVisit": re.compile(
        r"\b(instructions?|visit summary|after[- ]visit|discharge|doctor said|doctor'?s note|what'?s next|"
        r"what do i (?:need|have) to do|next steps?|care plan|read (?:this|my|it)|document)\b", re.I),
    "health.compareBill": re.compile(
        r"\b(bill|billing|insurance|eob|explanation of benefits|charged?|charges|owe|copay|deductible|coinsurance)\b", re.I),
    "health.planAppointment": re.compile(
        r"\b(schedule|appointment|book|free time|find (?:some )?time|available|availability|when can i|"
        r"follow[- ]up (?:time|visit)|calendar)\b", re.I),
    "health.visitPrep": re.compile(
        r"\b(prepare|prep|questions? (?:for|to ask)|what should i ask|before my (?:appointment|visit)|"
        r"tell my doctor|visit notes)\b", re.I),
    "health.checkin": re.compile(
        r"\b(check[- ]in|i'?ve been|i have been|i feel|i'?m feeling|feeling|sleep(?:ing)? (?:poorly|badly)|"
        r"tired|stressed|headaches?|can'?t sleep)\b", re.I),
    "health.reminder": re.compile(r"\b(remind(?:er)?|remember to|don'?t let me forget)\b", re.I),
}

PAGES = {
    "home": "/health", "conversation": "/health/conversation", "visit prep": "/health/visit-prep",
    "care plan": "/health/care-plan", "bills": "/health/bills", "bill": "/health/bills",
    "appointments": "/health/appointments", "timeline": "/health/timeline",
}
NAVIGATE = re.compile(r"\b(open|go to|show me|take me to)\s+(?:the\s+|my\s+)?(home|conversation|visit prep|care plan|bills?|appointments|timeline)\b", re.I)


def _pick(simple: bool, plain: str, detailed: str) -> str:
    return plain if simple else detailed


def detect_intents(text: str) -> list[str]:
    found = [name for name, pat in INTENT_PATTERNS.items() if pat.search(text)]
    # "make a reminder for my follow-up" is a reminder, not a scheduling request.
    if "health.reminder" in found and "health.planAppointment" in found and not re.search(r"\b(find|free|time|book)\b", text, re.I):
        found.remove("health.planAppointment")
    # "my doctor's instructions about the bill" — prefer the more specific bill intent.
    return found


class Turn:
    """Collects one response."""

    def __init__(self, req: JarvisCareRequest, session: Session, intent: str):
        self.req, self.s, self.intent = req, session, intent
        self.reply = ""
        self.spoken = ""
        self.cards: list[Card] = []
        self.actions: list[Action] = []
        self.clarification: Optional[str] = None
        self.is_mock = True

    @property
    def simple(self) -> bool:
        return self.req.preferences.simpleLanguage

    def build(self) -> JarvisCareResponse:
        spoken = self.spoken or self.reply
        self.s.last_spoken = spoken
        return JarvisCareResponse(
            requestId=self.req.requestId, intent=self.intent, replyText=self.reply or spoken,
            spokenSummary=spoken, cards=self.cards, actions=self.actions,
            clarification=self.clarification, isMock=self.is_mock,
        )


# ───────────────────────── document helpers ─────────────────────────

def _doc(s: Session, doc_id: str) -> Optional[documents.Document]:
    return s.docs.get(doc_id) or documents.load_sample(doc_id)


def register_doc(s: Session, doc: documents.Document) -> None:
    s.docs[doc.id] = doc
    if doc.type == "afterVisit":
        s.after_visit_id, s.plan = doc.id, None
    elif doc.type == "bill":
        s.bill_id = doc.id
    elif doc.type == "eob":
        s.eob_id = doc.id


def _apply_document_ids(s: Session, ids: Optional[list[str]]) -> None:
    for doc_id in ids or []:
        d = _doc(s, doc_id)
        if d:
            register_doc(s, d)


def _plan(s: Session) -> Optional[after_visit.AfterVisitPlan]:
    if s.plan is None and s.after_visit_id:
        d = _doc(s, s.after_visit_id)
        if d:
            s.plan = after_visit.extract(d)
    return s.plan


# ───────────────────────── intent handlers ─────────────────────────

def _after_visit(t: Turn) -> None:
    plan = _plan(t.s)
    if plan is None:
        t.reply = _pick(
            t.simple,
            "I can help with your doctor's instructions. Please choose your visit summary. "
            "You can upload it, paste the text, or use Sam's demo visit summary.",
            "I can turn your after-visit summary into clear next steps, with the exact sentence each step came from. "
            "Upload a PDF or text file, paste the text, or try Sam's fictional demo visit summary.",
        )
        t.spoken = "I can help with that. Would you like me to use the demo visit summary?"
        t.actions.append(Action(id="use-sample-av", label="Use demo visit summary", kind="useSample",
                                requiresConfirmation=False, payload={"documentId": "sample-after-visit"}))
        t.actions.append(Action(id="open-care-plan", label="Upload my own", kind="openPage",
                                requiresConfirmation=False, payload={"path": "/health/care-plan"}))
        t.s.pending = {"type": "offer_sample_after_visit"}
        return
    d = plan.doc
    t.is_mock = d.synthetic
    t.cards = plan.followups + plan.clarifications + plan.care + plan.warnings
    t.spoken = after_visit.spoken_overview(plan)
    lines = [f"From {d.name}:"]
    for c in plan.followups:
        due = f" (by {c.meta['dueSpoken']})" if c.meta.get("dueSpoken") else ""
        flag = " — needs confirmation" if c.status == "needsConfirmation" else ""
        lines.append(f"• {c.description}{due}{flag}")
    if not t.simple and plan.care:
        lines.append("Care instructions: " + " ".join(c.description for c in plan.care))
    t.reply = t.spoken + "\n" + "\n".join(lines)
    t.actions.append(Action(id="open-care-plan", label="Open care plan", kind="openPage",
                            requiresConfirmation=False, payload={"path": "/health/care-plan"}))
    t.s.pending = {"type": "offer_read_tasks"} if plan.followups or plan.care else None


def _offer_reminder(t: Turn) -> None:
    plan = _plan(t.s)
    target = None
    if plan:
        target = next(iter(plan.dated_followups), None) or next(iter(plan.followups), None)
    if target is None:
        t.reply = "I don't have a follow-up task to make a reminder for yet. Would you like me to use the demo visit summary first?"
        t.s.pending = {"type": "offer_sample_after_visit"}
        return
    due = target.meta.get("dueDate")
    # Don't repeat the date when the instruction already says it.
    when = f" by {target.meta['dueSpoken']}" if due and not after_visit._parse_date(target.title) else ""
    t.reply = (f"Here's the reminder I can save: \"{target.title}\"{when}. "
               "It's saved inside Jarvis Care only — no phone or calendar alert is sent. Say \"confirm\" or press Confirm to save it.")
    t.spoken = f"Here's the reminder: {target.title}{when}. Say confirm, or press Confirm, to save it."
    t.actions.append(Action(
        id="confirm-reminder", label="Confirm reminder", kind="saveReminder", requiresConfirmation=True,
        payload={"title": target.title, "dueDate": due, "sourceCardId": target.id},
    ))
    t.s.pending = {"type": "confirm_reminder", "title": target.title, "dueDate": due, "sourceCardId": target.id}
    t.is_mock = plan.doc.synthetic if plan else True


def _bills(t: Turn) -> None:
    bill_doc = _doc(t.s, t.s.bill_id) if t.s.bill_id else None
    eob_doc = _doc(t.s, t.s.eob_id) if t.s.eob_id else None
    if not bill_doc and not eob_doc:
        t.reply = ("I can compare a medical bill with your insurance statement and show where they match. "
                   "Would you like to use Sam's demo bill and insurance statement? They use fictional values.")
        t.spoken = "I can compare your bill with your insurance statement. Would you like to use the demo documents?"
        t.actions.append(Action(id="use-sample-bill", label="Use demo bill and EOB", kind="useSample",
                                requiresConfirmation=False, payload={"documentIds": ["sample-bill", "sample-eob"]}))
        t.s.pending = {"type": "offer_sample_bill"}
        return
    cmp = bills.compare(bill_doc, eob_doc)
    t.is_mock = any(d.synthetic for d in (bill_doc, eob_doc) if d)
    t.cards = cmp.cards
    t.s.bill_questions = cmp.questions
    if not cmp.complete:
        t.reply = t.spoken = cmp.cards[0].description
        return
    if cmp.mismatch_count or cmp.more_info_count:
        t.spoken = ("There may be a difference between these two documents. "
                    "I'll show you the matching charges and questions to ask before paying.")
    else:
        t.spoken = "The lines I could compare match between the two documents."
    detail = [
        f"{cmp.mismatch_count} possible mismatch(es) to verify, {cmp.more_info_count} line(s) needing more information.",
        *cmp.arithmetic,
        "This is not a judgment that the bill is wrong. Check with the billing office or your insurer before paying.",
    ]
    t.reply = t.spoken + "\n" + "\n".join(detail)
    if cmp.questions:
        t.actions.append(Action(id="copy-bill-questions", label="Copy questions for billing office",
                                kind="copyQuestions", requiresConfirmation=False,
                                payload={"questions": cmp.questions}))
    t.actions.append(Action(id="open-bills", label="Open bill comparison", kind="openPage",
                            requiresConfirmation=False, payload={"path": "/health/bills"}))


def _slots_cards(t: Turn, slots: list[scheduling.Slot], source: str) -> None:
    t.s.last_slots = [s.as_dict() for s in slots]
    for i, sl in enumerate(slots, start=1):
        t.cards.append(Card(
            id=f"slot{i}", kind="appointmentOption", title=f"Option {i}: {sl.label()}",
            description=f"Free time on {source}. This is not clinic availability — call the clinic to book.",
            status="suggested", meta={"start": sl.start.isoformat(), "end": sl.end.isoformat(), "source": source},
        ))
        t.actions.append(Action(id=f"plan-slot{i}", label=f"Plan option {i}", kind="confirmAppointment",
                                requiresConfirmation=True, payload=sl.as_dict()))


def _appointments(t: Turn) -> None:
    ctx = t.req.permittedContext
    avoid_exam = True  # a clinic visit on an exam day is rarely what a student wants
    if ctx and ctx.availability:
        slots = scheduling.suggest_from_windows(ctx.availability)
        t.is_mock = False
        source = "the times you entered"
        notes: list[str] = []
    elif (ctx and ctx.useDemoSchedule) or (t.s.pending or {}).get("type") == "offer_demo_schedule":
        slots, notes = scheduling.suggest_from_schedule(scheduling.load_demo_schedule(), avoid_exam)
        source = "Sam's demo schedule"
    else:
        t.reply = ("I can look for free time that avoids your exam. I won't book anything without your approval. "
                   "Jarvis Care isn't connected to your real calendar, so I can use Sam's demo schedule, "
                   "or you can type the times you're free on the Appointments page.")
        t.spoken = ("I can look for free time that avoids your exam. I won't book anything without your approval. "
                    "Should I use the demo schedule?")
        t.actions.append(Action(id="use-demo-schedule", label="Use demo schedule", kind="useSample",
                                requiresConfirmation=False, payload={"schedule": "demo"}))
        t.actions.append(Action(id="open-appointments", label="Enter my free times", kind="openPage",
                                requiresConfirmation=False, payload={"path": "/health/appointments"}))
        t.s.pending = {"type": "offer_demo_schedule"}
        return
    if not slots:
        t.reply = t.spoken = "I couldn't find an hour of free time in those windows. Try adding more free times."
        return
    _slots_cards(t, slots, source)
    first = slots[0].label()
    t.spoken = (" ".join(notes) + f" Your first free time is {first}. "
                "These are your free times, not clinic openings. Would you like to plan option 1?").strip()
    t.reply = (" ".join(notes) + f" I found {len(slots)} free times on {source}. "
               "These are your own free times, not clinic availability. Nothing is booked until you confirm, "
               "and in this demo no real appointment is booked.").strip()
    t.s.pending = {"type": "choose_slot"}


def _confirm_visit(t: Turn, slot: dict) -> None:
    import uuid
    from .session import PlannedVisit

    v = PlannedVisit(id=f"visit-{uuid.uuid4().hex[:8]}", start=slot["start"], end=slot["end"], label=slot["label"])
    t.s.visits.append(v)
    t.reply = (f"Planned: follow-up on {v.label}. Demo — no real appointment was booked. "
               "It's on your care timeline. Remember to call the clinic to book.")
    t.spoken = f"Done. I added {v.label} to your care timeline as a planned time. No real appointment was booked."
    t.cards.append(Card(id=v.id, kind="appointmentOption", title="Planned (demo)", description=v.note,
                        status="done", meta=v.as_dict()))
    t.s.pending = None


def _visit_prep(t: Turn) -> None:
    from .visit_prep import build

    prep = build(t.s)
    t.cards = prep["cards"]
    t.is_mock = False
    t.reply = prep["reply"]
    t.spoken = prep["spoken"]
    t.actions.append(Action(id="copy-prep", label="Copy my visit notes", kind="copyQuestions",
                            requiresConfirmation=False, payload={"questions": prep["questions"]}))
    t.actions.append(Action(id="open-prep", label="Open visit prep", kind="openPage",
                            requiresConfirmation=False, payload={"path": "/health/visit-prep"}))


def _checkin(t: Turn) -> None:
    text = (t.req.utterance or "").strip()
    t.is_mock = False
    t.reply = (f"Thanks for telling me. Would you like me to add this to your visit notes so you can mention it to your doctor? "
               f"\"{text}\" I won't share it anywhere.")
    t.spoken = "Thanks for telling me. Would you like me to add that to your visit notes for your doctor?"
    t.s.pending = {"type": "offer_save_note", "text": text}


def _accessibility(t: Turn) -> None:
    p = t.req.preferences
    text = t.req.utterance or ""
    changes: dict = {}
    said: list[str] = []
    if re.search(r"\b(bigger|larger|enlarge|zoom in|can'?t (?:read|see)|hard to read|increase)\b", text, re.I):
        higher = [s for s in TEXT_SCALES if s > p.textScale]
        if re.search(r"\b(everything|a lot|much|really)\b", text, re.I) and len(higher) > 1:
            changes["textScale"] = higher[1]
        else:
            changes["textScale"] = higher[0] if higher else TEXT_SCALES[-1]
        said.append("enlarged the text" if higher else "kept the text at its largest size")
    elif re.search(r"\b(smaller|zoom out|decrease)\b", text, re.I):
        lower = [s for s in TEXT_SCALES if s < p.textScale]
        changes["textScale"] = lower[-1] if lower else TEXT_SCALES[0]
        said.append("made the text smaller")
    if re.search(r"\bslow(?:er|ly| down)?\b", text, re.I):
        changes["speechRate"] = max(RATE_MIN, round(p.speechRate - RATE_STEP, 2))
        said.append("slowed down my voice")
    elif re.search(r"\b(faster|speed up|quicker)\b", text, re.I):
        changes["speechRate"] = min(RATE_MAX, round(p.speechRate + RATE_STEP, 2))
        said.append("sped up my voice")
    if re.search(r"\bhigh contrast|more contrast\b", text, re.I):
        changes["highContrast"] = True
        said.append("turned on high contrast")
    if re.search(r"\bdark mode\b", text, re.I):
        changes["theme"] = "dark"
        said.append("switched to dark mode")
    elif re.search(r"\blight mode\b", text, re.I):
        changes["theme"] = "light"
        said.append("switched to light mode")
    if re.search(r"\b(simple language|simpler|plain language)\b", text, re.I):
        changes["simpleLanguage"] = True
        said.append("switched to simple language")
    elif re.search(r"\b(detailed|more detail)\b", text, re.I):
        changes["simpleLanguage"] = False
        said.append("switched to detailed explanations")
    if re.search(r"\b(mute|stop talking|be quiet|turn off (?:voice|speech))\b", text, re.I):
        changes["speechEnabled"] = False
        said.append("turned off spoken replies. You can still read everything on screen")
    elif re.search(r"\bturn on (?:voice|speech)\b", text, re.I):
        changes["speechEnabled"] = True
        said.append("turned spoken replies back on")
    t.is_mock = False
    if not changes:
        t.reply = t.spoken = ("I can make text bigger or smaller, slow down or speed up my voice, turn on high contrast "
                              "or dark mode, or use simpler language. What would you like?")
        t.clarification = t.reply
        return
    sentence = " and ".join(said) if len(said) <= 2 else ", ".join(said[:-1]) + ", and " + said[-1]
    t.reply = t.spoken = f"Of course. I've {sentence}."
    if "textScale" in changes:
        t.reply += f" Text size is now {TEXT_SCALE_NAMES.get(changes['textScale'], 'larger')}."
    t.actions.append(Action(id="prefs", label="Accessibility settings updated", kind="setPreferences",
                            requiresConfirmation=False, payload=changes))


def _safety(t: Turn, self_harm: bool) -> None:
    t.is_mock = False
    if self_harm:
        t.reply = t.spoken = (
            "I'm really glad you told me. I can't help in a crisis, but people can, right now. "
            "In the US, call or text 988 to reach the Suicide and Crisis Lifeline. "
            "If you are in immediate danger, call 911 or your local emergency number."
        )
    else:
        t.reply = t.spoken = (
            "I can't assess emergencies. If this might be urgent, call 911 or your local emergency number now, "
            "or contact a healthcare professional."
        )
    t.cards.append(Card(id="safety", kind="info", title="Get help now", description=t.reply, status="ready"))
    t.s.pending = None


def _medical_advice(t: Turn) -> None:
    q = (t.req.utterance or "").strip()
    t.is_mock = False
    t.reply = ("I can't give medical advice, diagnoses, or medicine doses. That's a great question for your "
               "clinician or pharmacist. Would you like me to add it to your questions for your next visit?")
    t.spoken = t.reply
    t.s.pending = {"type": "offer_save_question", "text": q}


def _help(t: Turn) -> None:
    t.is_mock = False
    t.reply = ("I can help you understand your doctor's instructions, prepare questions for a visit, "
               "check a medical bill against your insurance statement, find free time for a follow-up, "
               "or make this screen easier to use. What would you like to do?")
    t.spoken = ("I can explain doctor's instructions, prepare visit questions, check a medical bill, "
                "find time for a follow-up, or make the screen easier to use. What would you like?")
    t.clarification = t.spoken


def _organize(t: Turn, intents: list[str]) -> None:
    """Several needs in one breath: lay out a plan, then start with the first step."""
    labels = {
        "health.parseAfterVisit": ("Understand your doctor's instructions", "/health/care-plan"),
        "health.planAppointment": ("Find time for a follow-up around your exam", "/health/appointments"),
        "health.checkin": ("Note how you've been feeling for your doctor", "/health/visit-prep"),
        "health.visitPrep": ("Prepare questions for your visit", "/health/visit-prep"),
        "health.compareBill": ("Check your bill against your insurance", "/health/bills"),
        "health.reminder": ("Set reminders for your follow-ups", "/health/care-plan"),
    }
    steps = [i for i in labels if i in intents]
    for n, i in enumerate(steps, start=1):
        title, path = labels[i]
        t.cards.append(Card(id=f"step{n}", kind="task", title=f"Step {n}: {title}", description=title,
                            status="suggested", meta={"path": path}))
    t.is_mock = False
    if "health.parseAfterVisit" in intents and not _plan(t.s):
        t.spoken = ("Absolutely. I can organize your doctor's instructions, help you prepare questions, "
                    "and find a time that doesn't overlap your exam. First, would you like me to use the demo visit summary?")
        t.s.pending = {"type": "offer_sample_after_visit"}
        t.actions.append(Action(id="use-sample-av", label="Use demo visit summary", kind="useSample",
                                requiresConfirmation=False, payload={"documentId": "sample-after-visit"}))
    else:
        t.spoken = f"Absolutely. I made a plan with {len(steps)} steps. Let's start with step 1: {labels[steps[0]][0].lower()}."
    t.reply = t.spoken + "\n" + "\n".join(f"{n}. {labels[i][0]}" for n, i in enumerate(steps, start=1))


# ───────────────────────── pending follow-ups ─────────────────────────

ORDINALS = {"first": 1, "one": 1, "1": 1, "second": 2, "two": 2, "2": 2, "third": 3, "three": 3, "3": 3}


def _resolve_pending(t: Turn, text: str) -> bool:
    p = t.s.pending
    if not p:
        return False
    kind = p["type"]
    # A longer sentence with its own request ("please make the text bigger") is a new turn, not a yes/no.
    if detect_intents(text) and len(text.split()) > 4:
        return False
    if kind == "choose_slot" and t.s.last_slots:
        m = re.search(r"\b(first|second|third|one|two|three|[123])\b", text, re.I)
        day = next((s for s in t.s.last_slots if s["label"].split(",")[0].lower() in text.lower()), None)
        if m or day or YES.search(text):
            idx = ORDINALS.get(m.group(1).lower(), 1) if m else 1
            slot = day or t.s.last_slots[min(idx, len(t.s.last_slots)) - 1]
            t.intent = "health.planAppointment"
            t.reply = (f"Plan your follow-up for {slot['label']}? This only adds it to your Jarvis Care timeline — "
                       "no real appointment is booked. Say \"confirm\" or press Confirm.")
            t.spoken = f"Plan your follow-up for {slot['label']}? Say confirm to add it to your timeline."
            t.actions.append(Action(id="confirm-slot", label="Confirm planned time", kind="confirmAppointment",
                                    requiresConfirmation=True, payload=slot))
            t.s.pending = {"type": "confirm_slot", "slot": slot}
            return True
    if NO.search(text):
        t.intent = "health.help"
        t.reply = t.spoken = "Okay, I won't do that. What would you like to do instead?"
        t.s.pending = None
        return True
    if kind in ("confirm_reminder", "confirm_slot"):
        if not CONFIRM.search(text):
            return False
        if kind == "confirm_reminder":
            r = t.s.add_reminder(p["title"], p.get("dueDate"), p.get("sourceCardId"))
            t.intent = "health.reminder"
            when = f" for {p['dueDate']}" if p.get("dueDate") else ""
            t.reply = f"Saved. Reminder \"{r.title}\"{when} is on your care timeline. {r.note}"
            t.spoken = "Saved. Your reminder is on your care timeline."
            t.cards.append(Card(id=r.id, kind="task", title=r.title, description=r.note, status="done", meta=r.as_dict()))
            t.s.pending = None
        else:
            t.intent = "health.planAppointment"
            _confirm_visit(t, p["slot"])
        return True
    if not YES.search(text):
        return False
    if kind == "offer_sample_after_visit":
        register_doc(t.s, documents.load_sample("sample-after-visit"))  # type: ignore[arg-type]
        t.intent = "health.parseAfterVisit"
        _after_visit(t)
    elif kind == "offer_read_tasks":
        plan = _plan(t.s)
        t.intent = "health.parseAfterVisit"
        t.reply = t.spoken = after_visit.spoken_details(plan, t.simple) + " Would you like me to make a reminder for your follow-up?"  # type: ignore[arg-type]
        t.cards = plan.followups + plan.clarifications if plan else []
        t.is_mock = plan.doc.synthetic if plan else True
        t.s.pending = {"type": "offer_reminder"}
    elif kind == "offer_reminder":
        t.intent = "health.reminder"
        _offer_reminder(t)
    elif kind == "offer_sample_bill":
        register_doc(t.s, documents.load_sample("sample-bill"))  # type: ignore[arg-type]
        register_doc(t.s, documents.load_sample("sample-eob"))  # type: ignore[arg-type]
        t.s.pending = None
        t.intent = "health.compareBill"
        _bills(t)
    elif kind == "offer_demo_schedule":
        t.intent = "health.planAppointment"
        _appointments(t)
    elif kind in ("offer_save_note", "offer_save_question"):
        if kind == "offer_save_note":
            t.s.add_note(p["text"])
            t.reply = t.spoken = "Added to your visit notes. You can review them on the Visit Prep page."
        else:
            t.s.questions.append(p["text"])
            t.reply = t.spoken = "Added to your questions for your next visit."
        t.intent = "health.visitPrep"
        t.is_mock = False
        t.s.pending = None
        t.actions.append(Action(id="open-prep", label="Open visit prep", kind="openPage",
                                requiresConfirmation=False, payload={"path": "/health/visit-prep"}))
    else:
        return False
    return True


# ───────────────────────── entry point ─────────────────────────

def handle(req: JarvisCareRequest, session: Optional[Session] = None) -> JarvisCareResponse:
    s = session or STORE.get(req.sessionId)
    _apply_document_ids(s, req.documentIds)
    text = (req.utterance or "").strip()
    t = Turn(req, s, req.intent or "health.help")

    if text and SELF_HARM.search(text):
        t.intent = "health.help"
        _safety(t, self_harm=True)
        return t.build()
    if text and EMERGENCY.search(text):
        t.intent = "health.help"
        _safety(t, self_harm=False)
        return t.build()

    if text and re.fullmatch(r"(?i)\s*(repeat|say (?:that|it) again|again|what did you say)\W*", text):
        t.intent = "health.help"
        t.reply = t.spoken = s.last_spoken or "I haven't said anything yet. How can I help?"
        t.is_mock = False
        return t.build()

    if text and _resolve_pending(t, text):
        return t.build()

    if text and (m := NAVIGATE.search(text)):
        page = m.group(2).lower()
        t.intent = "health.help"
        t.is_mock = False
        t.reply = t.spoken = f"Opening {page}."
        t.actions.append(Action(id="nav", label=f"Open {page}", kind="openPage", requiresConfirmation=False,
                                payload={"path": PAGES.get(page, "/health")}))
        return t.build()

    if text and MEDICAL_ADVICE.search(text) and not INTENT_PATTERNS["health.compareBill"].search(text):
        t.intent = "health.help"
        _medical_advice(t)
        return t.build()

    intents = [req.intent] if req.intent else detect_intents(text)
    # Accessibility requests act immediately even when mixed with other words.
    if "health.accessibility" in intents:
        t.intent = "health.accessibility"
        _accessibility(t)
        return t.build()

    major = [i for i in intents if i != "health.reminder"]
    if len(set(major)) >= 3 or (len(set(major)) >= 2 and "health.checkin" in major and len(text) > 80):
        t.intent = "health.help"
        _organize(t, intents)
        return t.build()

    intent = intents[0] if intents else "health.help"
    if "health.reminder" in intents:
        intent = "health.reminder"
    elif "health.compareBill" in intents:
        intent = "health.compareBill"
    elif "health.planAppointment" in intents and "health.parseAfterVisit" not in intents:
        intent = "health.planAppointment"
    t.intent = intent
    s.pending = None
    {
        "health.parseAfterVisit": _after_visit,
        "health.compareBill": _bills,
        "health.planAppointment": _appointments,
        "health.visitPrep": _visit_prep,
        "health.checkin": _checkin,
        "health.reminder": _offer_reminder,
        "health.accessibility": _accessibility,
        "health.help": _help,
    }[intent](t)
    return t.build()
