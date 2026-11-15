"""After-visit summary extraction — deterministic and evidence-first.

Every card quotes a line that exists verbatim in the extracted document text.
Nothing is inferred beyond the source: no computed dates, no dosing, no new
instructions. Missing or vague details become "needsConfirmation" cards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .documents import Document
from .models import Card, Evidence

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
DATE_WORDS = re.compile(rf"\b({MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
DATE_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
BULLET = re.compile(r"^\s*(?:[-*•●]|\d{1,2}[.)])\s+(.*\S)\s*$")

WARNING_HINTS = ("seek care", "right away", "emergency", "911", "call the clinic", "go to the", "urgent")
FOLLOWUP_HINTS = (
    "schedule", "follow-up", "follow up", "bring", "book", "make an appointment", "return to",
    "fill out", "pick up", "get a ", "get an ", "call to", "sign up",
)
SCHEDULE_HINTS = ("schedule", "follow-up visit", "follow up visit", "make an appointment", "book")
MEDICATION_HINTS = ("medicine", "medication", "prescription", "pill", "tablet", "dose", "mg ", "inhaler")
VAGUE_PATTERNS = (
    (re.compile(r"\b(?:completed|the|your)\s+(?:\w+\s+)?form\b", re.I),
     "The note doesn't say which form this is or where to get it. Ask the clinic before your visit."),
    (re.compile(r"\bif needed\b|\bas needed\b", re.I),
     "The note doesn't say when this is needed. Ask your clinician to explain."),
)
SKIP_FIELD = re.compile(r"^\s*(patient|member|clinician|provider|visit date|reason for visit)\s*:", re.I)


def _parse_date(text: str) -> Optional[date]:
    m = DATE_WORDS.search(text)
    if m:
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                mon = m.group(1)[:3] if fmt == "%b %d %Y" else m.group(1)
                return datetime.strptime(f"{mon} {m.group(2)} {m.group(3)}", fmt).date()
            except ValueError:
                continue
    m = DATE_NUM.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _speakable_date(d: date) -> str:
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}, {d.year}"


@dataclass
class AfterVisitPlan:
    doc: Document
    visit_date: Optional[date]
    followups: list[Card] = field(default_factory=list)
    care: list[Card] = field(default_factory=list)
    warnings: list[Card] = field(default_factory=list)
    clarifications: list[Card] = field(default_factory=list)

    @property
    def all_cards(self) -> list[Card]:
        return self.followups + self.care + self.warnings + self.clarifications

    @property
    def dated_followups(self) -> list[Card]:
        return [c for c in self.followups if c.meta.get("dueDate")]

    @property
    def unclear_followups(self) -> list[Card]:
        return [c for c in self.followups if c.status == "needsConfirmation"]


def _candidate_lines(doc: Document) -> list[tuple[int, str]]:
    """Instruction-like lines with their 1-based page number."""
    out: list[tuple[int, str]] = []
    for page_no, page in enumerate(doc.pages, start=1):
        bullets = [BULLET.match(line) for line in page.splitlines()]
        found = [(page_no, m.group(1).strip()) for m in bullets if m]
        if found:
            out.extend(found)
            continue
        # No bullet list: fall back to sentences that read like instructions.
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", page):
            s = sentence.strip()
            if len(s) < 12 or SKIP_FIELD.match(s):
                continue
            first = s.split()[0].lower()
            if first in {
                "rest", "take", "put", "apply", "keep", "avoid", "continue", "schedule", "call",
                "bring", "return", "drink", "use", "book", "make", "seek", "wear", "check",
                "follow", "stop", "start", "get", "fill",
            }:
                out.append((page_no, s))
    return out


def extract(doc: Document) -> AfterVisitPlan:
    text = doc.text
    visit_line = next((l for l in text.splitlines() if l.lower().strip().startswith("visit date")), "")
    plan = AfterVisitPlan(doc=doc, visit_date=_parse_date(visit_line) if visit_line else None)

    for idx, (page, line) in enumerate(_candidate_lines(doc), start=1):
        low = line.lower()
        evidence = [Evidence(
            docId=doc.id,
            filename=doc.name,
            page=page if len(doc.pages) > 1 else None,
            excerpt=line,
            verified=line in text,
        )]
        cid = f"{doc.id}-item{idx}"
        due = _parse_date(line)
        is_med = any(h in low + " " for h in MEDICATION_HINTS)

        if any(h in low for h in WARNING_HINTS):
            plan.warnings.append(Card(
                id=cid, kind="info", title="When to get help",
                description=line, status="ready", evidence=evidence,
                meta={"category": "warning"},
            ))
            continue

        if any(h in low for h in FOLLOWUP_HINTS):
            meta: dict = {"category": "followup"}
            status = "ready"
            note = None
            if due:
                meta["dueDate"] = due.isoformat()
                meta["dueSpoken"] = _speakable_date(due)
            elif any(h in low for h in SCHEDULE_HINTS):
                status, note = "needsConfirmation", "The note doesn't give a date for this. Ask the clinic when it should happen."
            for pattern, why in VAGUE_PATTERNS:
                if pattern.search(line):
                    status, note = "needsConfirmation", why
                    break
            card = Card(
                id=cid, kind="task", title=line.rstrip("."), description=line,
                status=status, evidence=evidence, meta=meta,
            )
            plan.followups.append(card)
            if note:
                card.meta["clarification"] = note
                plan.clarifications.append(Card(
                    id=f"{cid}-q", kind="question", title="Needs confirmation",
                    description=note, status="needsConfirmation", evidence=evidence,
                    meta={"category": "clarification", "forCard": cid},
                ))
            continue

        meta = {"category": "care"}
        if is_med:
            meta["medication"] = True
            meta["note"] = (
                "Jarvis only repeats what your document says about medicine. "
                "Follow your prescription label and ask your pharmacist or clinician if anything is unclear."
            )
        plan.care.append(Card(
            id=cid, kind="task", title=line.rstrip("."), description=line,
            status="ready", evidence=evidence, meta=meta,
        ))
    return plan


def _count(n: int, one: str, many: str) -> str:
    words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
    return f"{words[n] if n < len(words) else n} {one if n == 1 else many}"


def spoken_overview(plan: AfterVisitPlan) -> str:
    f = len(plan.followups)
    if f == 0 and not plan.care:
        return "I couldn't find clear instructions in this document. Would you like to paste the text instead?"
    parts = [f"I found {_count(f, 'follow-up task', 'follow-up tasks')} in your document."]
    if f:
        bits = []
        if plan.dated_followups:
            bits.append(_count(len(plan.dated_followups), "has a date", "have dates"))
        if plan.unclear_followups:
            bits.append(_count(len(plan.unclear_followups), "needs clarification", "need clarification"))
        if bits:
            parts.append((", and ".join(bits)).capitalize() + ".")
    parts.append("Would you like me to read them?")
    return " ".join(parts)


def spoken_details(plan: AfterVisitPlan, simple: bool = True) -> str:
    lines: list[str] = []
    for i, c in enumerate(plan.followups, start=1):
        s = f"Task {i}: {c.description}"
        if c.meta.get("clarification"):
            s += f" {c.meta['clarification']}"
        lines.append(s)
    if plan.care:
        lines.append(
            f"You also have {_count(len(plan.care), 'care instruction', 'care instructions')}"
            + (" on screen." if simple else ": " + " ".join(c.description for c in plan.care))
        )
    if plan.warnings:
        lines.append("And one important note: " + plan.warnings[0].description)
    return " ".join(lines)
