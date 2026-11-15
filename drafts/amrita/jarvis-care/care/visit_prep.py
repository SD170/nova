"""Visit Prep Card + Care Timeline, built only from what the user told us.

No diagnoses, no scores. Patterns are phrased as conversation starters.
"""
from __future__ import annotations

import re
from collections import Counter

from . import scheduling
from .models import Card
from .session import Session

THEMES = {
    "tiredness": r"\b(tired|tiredness|exhausted|fatigue|low energy|no energy)\b",
    "sleep trouble": r"\b(sleep(?:ing)? (?:poorly|badly)|can'?t sleep|insomnia|trouble sleeping|not sleeping)\b",
    "stress": r"\b(stress(?:ed)?|anxious|overwhelmed)\b",
    "headaches": r"\b(headaches?|migraines?)\b",
    "ankle pain": r"\b(ankle|swelling|swollen)\b",
}
UNSURE = re.compile(r"\b(not sure|unsure|don'?t know|confus\w*|wonder)\b|\?", re.I)

SUGGESTED_QUESTIONS = [
    "What should I do if this doesn't get better?",
    "When should I come back for a follow-up?",
    "Is there anything I should avoid while I recover?",
]

WORD = {1: "once", 2: "twice", 3: "three times", 4: "four times", 5: "five times"}


def build(s: Session) -> dict:
    know: list[str] = []
    for n in s.notes:
        extras = [f"{k}: {v}" for k, v in (("sleep", n.sleep), ("energy", n.energy), ("stress", n.stress)) if v]
        line = n.userText or ""
        if extras:
            line = (line + " — " if line else "") + ", ".join(extras)
        if line:
            know.append(f"{n.createdAt[:10]}: {line}")

    counts: Counter = Counter()
    for n in s.notes:
        blob = " ".join(filter(None, [n.userText, n.sleep and f"sleep {n.sleep}", n.energy and f"energy {n.energy}"]))
        if n.sleep == "poor":
            blob += " trouble sleeping"
        if n.energy == "low":
            blob += " low energy"
        for theme, pat in THEMES.items():
            if re.search(pat, blob, re.I):
                counts[theme] += 1
    starters = [
        f"You mentioned {theme} {WORD.get(c, f'{c} times')} recently. Would you like to mention that at your next visit?"
        for theme, c in counts.most_common() if c >= 2
    ]

    unsure = [n.userText for n in s.notes if n.userText and UNSURE.search(n.userText)]
    if s.plan:
        unsure += [f"{c.meta.get('clarification')} (from: \"{c.description}\")"
                   for c in s.plan.followups if c.meta.get("clarification")]

    questions = list(dict.fromkeys(s.questions)) or list(SUGGESTED_QUESTIONS)
    suggested = not s.questions

    cards: list[Card] = [
        Card(id="prep-know", kind="info", title="What I want my doctor to know",
             description="\n".join(know) or "Nothing yet. Add a check-in note to start.",
             status="ready" if know else "suggested"),
        Card(id="prep-questions", kind="question", title="Questions I want to ask",
             description="\n".join(questions), status="suggested" if suggested else "ready",
             meta={"questions": questions, "suggested": suggested}),
        Card(id="prep-unsure", kind="question", title="Things I'm unsure about",
             description="\n".join(unsure) or "Nothing marked as unsure yet.",
             status="needsConfirmation" if unsure else "suggested"),
    ]
    for i, st in enumerate(starters, start=1):
        cards.append(Card(id=f"prep-starter{i}", kind="info", title="Conversation starter", description=st, status="suggested"))

    def n(count: int, word: str) -> str:
        return f"{count} {word}{'' if count == 1 else 's'}"

    if know or s.questions:
        spoken = f"Your visit notes have {n(len(questions), 'question')}"
        spoken += f" and {n(len(know), 'check-in note')}." if know else " and no check-in notes yet."
    else:
        spoken = "Your visit notes are empty so far. I added three starter questions you can edit."
    if starters:
        spoken += " " + starters[0]
    reply = spoken + " Nothing here is a diagnosis — it's your own words, organized for your doctor."
    return {"cards": cards, "questions": questions, "know": know, "unsure": unsure,
            "starters": starters, "spoken": spoken, "reply": reply}


def as_text(s: Session) -> str:
    p = build(s)
    out = ["MY VISIT NOTES (prepared with Jarvis Care — not medical advice)", "",
           "What I want my doctor to know:"]
    out += [f"- {k}" for k in p["know"]] or ["- (nothing yet)"]
    out += ["", "Questions I want to ask:"] + [f"- {q}" for q in p["questions"]]
    out += ["", "Things I'm unsure about:"] + ([f"- {u}" for u in p["unsure"]] or ["- (nothing yet)"])
    return "\n".join(out) + "\n"


def timeline(s: Session, include_academics: bool) -> list[dict]:
    items: list[dict] = []
    for v in s.visits:
        items.append({"id": v.id, "when": v.start, "type": "Planned visit", "title": f"Follow-up visit: {v.label}",
                      "status": "Planned (demo)", "source": "You approved this time", "next": "Call the clinic to book",
                      "path": "/health/appointments", "demo": True})
    for r in s.reminders:
        items.append({"id": r.id, "when": r.dueDate, "type": "Reminder", "title": r.title,
                      "status": "Saved", "source": "From your after-visit summary" if r.sourceCardId else "You added this",
                      "next": "Mark done when finished", "path": "/health/care-plan", "demo": False})
    if s.plan:
        reminded = {r.sourceCardId for r in s.reminders}
        for c in s.plan.followups:
            if c.id in reminded:
                continue
            items.append({"id": c.id, "when": c.meta.get("dueDate"), "type": "Care task", "title": c.title,
                          "status": "Needs confirmation" if c.status == "needsConfirmation" else "To do",
                          "source": f"Quoted from {s.plan.doc.name}", "next": "Review in care plan",
                          "path": "/health/care-plan", "demo": s.plan.doc.synthetic})
    for i, q in enumerate(s.questions, start=1):
        items.append({"id": f"q{i}", "when": None, "type": "Question for doctor", "title": q, "status": "To ask",
                      "source": "You added this", "next": "Open visit prep", "path": "/health/visit-prep", "demo": False})
    for i, q in enumerate(s.bill_questions, start=1):
        items.append({"id": f"bq{i}", "when": None, "type": "Bill question", "title": q, "status": "To ask",
                      "source": "From the bill comparison", "next": "Open bills", "path": "/health/bills", "demo": True})
    if include_academics:
        for i, d in enumerate(scheduling.deadlines(), start=1):
            items.append({"id": f"ac{i}", "when": d["due"], "type": "Class deadline", "title": d["title"],
                          "status": "Demo data", "source": "Sam's demo schedule (not your real Canvas)",
                          "next": None, "path": None, "demo": True})
    dated = sorted((i for i in items if i["when"]), key=lambda i: i["when"])
    return dated + [i for i in items if not i["when"]]
