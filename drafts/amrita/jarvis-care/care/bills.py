"""BillSmart — compare a bill with an insurance EOB, line by line.

Deterministic: table rows are parsed from the documents, matched on
date + code (or date + description words), and all arithmetic is done here in
Decimal — never by a language model. Findings are neutral questions to verify,
never claims that a bill is wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

from .documents import Document
from .models import Card, Evidence

MONEY = re.compile(r"-?\$?\s*\(?(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)\)?")
DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")

LABEL_MATCH = "Matches the supplied documents"
LABEL_MISMATCH = "Possible mismatch to verify"
LABEL_MORE_INFO = "Need more information"

# Column header synonyms -> canonical field.
COLUMNS = {
    "date": ("date of service", "service date", "date"),
    "code": ("code", "cpt", "procedure"),
    "description": ("description", "service"),
    "billed": ("charges", "amount billed", "billed", "charge"),
    "allowed": ("allowed amount", "allowed"),
    "insurerPaid": ("insurance paid", "plan paid", "paid by plan", "insurer paid"),
    "adjustment": ("adjustments", "adjustment", "discount"),
    "responsibility": ("you owe", "your responsibility", "patient responsibility", "amount you owe"),
    "notes": ("notes", "remarks"),
}


@dataclass
class BillLine:
    docId: str
    filename: str
    raw: str
    date: Optional[str] = None
    code: Optional[str] = None
    description: str = ""
    billed: Optional[Decimal] = None
    allowed: Optional[Decimal] = None
    insurerPaid: Optional[Decimal] = None
    adjustment: Optional[Decimal] = None
    responsibility: Optional[Decimal] = None
    notes: str = ""

    def as_dict(self) -> dict:
        def m(v):
            return None if v is None else f"{v:.2f}"
        return {
            "date": self.date, "code": self.code, "description": self.description,
            "billed": m(self.billed), "allowed": m(self.allowed), "insurerPaid": m(self.insurerPaid),
            "adjustment": m(self.adjustment), "responsibility": m(self.responsibility),
            "notes": self.notes, "source": self.raw,
        }


@dataclass
class ParsedStatement:
    doc: Document
    role: str  # bill | eob
    lines: list[BillLine] = field(default_factory=list)
    stated_total: Optional[Decimal] = None
    total_line: Optional[str] = None


def _money(cell: str) -> Optional[Decimal]:
    cell = cell.strip()
    if not cell or not any(ch.isdigit() for ch in cell):
        return None
    m = MONEY.search(cell)
    if not m:
        return None
    try:
        value = Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    return -value if cell.startswith("-") or cell.startswith("(") else value


def _map_header(cells: list[str]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for i, cell in enumerate(cells):
        c = cell.strip().lower()
        for fieldname, names in COLUMNS.items():
            if fieldname in mapping.values():
                continue
            if any(c == n or c.startswith(n) for n in names):
                mapping[i] = fieldname
                break
    return mapping


def parse_statement(doc: Document) -> ParsedStatement:
    role = "eob" if doc.type == "eob" else "bill"
    out = ParsedStatement(doc=doc, role=role)
    header: dict[int, str] = {}
    for raw in doc.text.splitlines():
        line = raw.strip()
        if "|" in line:
            cells = [c.strip() for c in line.split("|")]
            if not DATE.search(line):
                mapped = _map_header(cells)
                if len(mapped) >= 3:
                    header = mapped
                continue
            if not header:
                continue
            row = BillLine(docId=doc.id, filename=doc.name, raw=line)
            for i, cell in enumerate(cells):
                f = header.get(i)
                if f in ("date", "code", "description", "notes"):
                    setattr(row, f, cell)
                elif f:
                    setattr(row, f, _money(cell))
            out.lines.append(row)
        elif line.lower().startswith("total") and "$" in line:
            out.stated_total = _money(line.split(":", 1)[-1])
            out.total_line = line
    return out


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower())}


def _match(bill: BillLine, eob_lines: list[BillLine]) -> Optional[BillLine]:
    for e in eob_lines:
        if bill.code and e.code and bill.code == e.code and bill.date == e.date:
            return e
    for e in eob_lines:
        if bill.date == e.date and _words(bill.description) & _words(e.description):
            return e
    return None


def _ev(line: BillLine) -> Evidence:
    return Evidence(docId=line.docId, filename=line.filename, excerpt=line.raw, verified=True)


@dataclass
class Comparison:
    bill: Optional[ParsedStatement]
    eob: Optional[ParsedStatement]
    cards: list[Card] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    complete: bool = True
    mismatch_count: int = 0
    more_info_count: int = 0
    arithmetic: list[str] = field(default_factory=list)


def _fmt(v: Optional[Decimal]) -> str:
    return "not listed" if v is None else f"${v:,.2f}"


def compare(bill_doc: Optional[Document], eob_doc: Optional[Document]) -> Comparison:
    bill = parse_statement(bill_doc) if bill_doc else None
    eob = parse_statement(eob_doc) if eob_doc else None
    cmp = Comparison(bill=bill, eob=eob)

    if not bill or not eob:
        cmp.complete = False
        have = "bill" if bill else "insurance statement (EOB)"
        missing = "insurance statement (EOB)" if bill else "bill"
        cmp.cards.append(Card(
            id="bill-incomplete", kind="billFlag", title=LABEL_MORE_INFO,
            description=f"I only have your {have}. To compare, I also need the matching {missing}. "
                        "Until then the comparison is incomplete.",
            status="needsConfirmation",
        ))
        return cmp

    # Arithmetic check: bill total vs sum of its line items (done in code).
    for st in (bill, eob):
        resp = [l.responsibility for l in st.lines if l.responsibility is not None]
        if st.stated_total is not None and resp:
            total = sum(resp, Decimal("0"))
            label = "bill" if st.role == "bill" else "EOB"
            if total == st.stated_total:
                cmp.arithmetic.append(f"The {label}'s line items add up to its stated total of {_fmt(total)}.")
            else:
                cmp.arithmetic.append(
                    f"The {label}'s line items add up to {_fmt(total)}, but it states a total of {_fmt(st.stated_total)}."
                )

    used: set[int] = set()
    for i, b in enumerate(bill.lines, start=1):
        e = _match(b, eob.lines)
        row = {"bill": b.as_dict(), "eob": e.as_dict() if e else None}
        title_desc = b.description or b.code or "Charge"
        if e is None:
            status, label = "needsConfirmation", LABEL_MORE_INFO
            desc = (f"{title_desc} on {b.date} appears on the bill ({_fmt(b.responsibility)} listed for you) "
                    "but I couldn't find a matching line on the insurance statement.")
            cmp.more_info_count += 1
            cmp.questions.append(f"Was the {title_desc.lower()} on {b.date} submitted to my insurance?")
            evidence = [_ev(b)]
        else:
            used.add(id(e))
            evidence = [_ev(b), _ev(e)]
            pending = any(k in e.notes.lower() for k in ("pending", "additional information", "denied", "not covered"))
            if pending:
                status, label = "needsConfirmation", LABEL_MORE_INFO
                desc = (f"{title_desc}: the bill lists {_fmt(b.responsibility)} for you, but the insurance statement says "
                        f"\"{e.notes}\". The final amount may not be settled yet.")
                cmp.more_info_count += 1
                cmp.questions.append(
                    f"The insurance statement says the {title_desc.lower()} claim is \"{e.notes}\". "
                    "Should I wait to pay that line until the claim is processed?"
                )
            elif b.responsibility is not None and e.responsibility is not None and b.responsibility != e.responsibility:
                diff = b.responsibility - e.responsibility
                status, label = "needsConfirmation", LABEL_MISMATCH
                desc = (f"{title_desc}: the bill lists {_fmt(b.responsibility)} for you, while the insurance statement lists "
                        f"{_fmt(e.responsibility)} as your responsibility — a difference of {_fmt(abs(diff))}. "
                        "This may have a simple explanation, so it is worth asking before you pay.")
                cmp.mismatch_count += 1
                row["difference"] = f"{diff:.2f}"
                cmp.questions.append(
                    f"For the {title_desc.lower()} on {b.date} (code {b.code or 'not listed'}), my bill says I owe "
                    f"{_fmt(b.responsibility)} but my insurance statement says {_fmt(e.responsibility)}. "
                    "Can you help me understand the difference?"
                )
            else:
                status, label = "ready", LABEL_MATCH
                desc = f"{title_desc}: both documents list {_fmt(b.responsibility)} as your share."
        row["label"] = label
        cmp.rows.append(row)
        cmp.cards.append(Card(
            id=f"bill-line{i}", kind="billFlag", title=label, description=desc,
            status=status, evidence=evidence,
            meta={"code": b.code, "date": b.date, "label": label},
        ))

    for e in eob.lines:
        if id(e) not in used:
            cmp.rows.append({"bill": None, "eob": e.as_dict(), "label": LABEL_MORE_INFO})
            cmp.cards.append(Card(
                id=f"eob-only-{len(cmp.rows)}", kind="billFlag", title=LABEL_MORE_INFO,
                description=f"{e.description} on {e.date} is on the insurance statement but not on this bill.",
                status="needsConfirmation", evidence=[_ev(e)],
            ))
            cmp.more_info_count += 1
    return cmp


GLOSSARY = [
    ("Deductible", "The amount you pay for covered care each plan year before your insurance starts paying its share."),
    ("Copay", "A set amount you pay for a type of visit or service, like $30 for an office visit."),
    ("Coinsurance", "A percentage of the allowed cost you pay after any deductible, like 20%."),
    ("Allowed amount", "The price your plan has agreed to for a service. It is often lower than the clinic's full charge."),
    ("EOB", "Explanation of Benefits: a statement from your insurer that shows what it paid. It is not a bill."),
]

HOW_TO_VERIFY = [
    "Match the date of service and the service code on both documents.",
    "Call the number on your insurance card and ask what your share is for each line.",
    "Ask the clinic's billing office whether they have the latest payment from your insurer.",
    "If a claim is pending, ask whether you should wait before paying that line.",
]
