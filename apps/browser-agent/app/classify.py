"""Turn a RawItem into a classified Item. Same logic for every backend.

Three layers, each one explainable:

1. RULES (Canvas's own data, no AI)
   - exam keyword in the title (not announcements)       -> exam        (keyword)
   - quiz list / submission type online_quiz             -> quiz        (rule)
   - discussion                                          -> discussion  (rule)
   - assignment                                          -> assignment  (rule)
   - calendar event                                      -> event       (rule)
   - anything else (announcements)                       -> unknown     (none)

2. LLM (Gemini, optional) — reads title + instructions and can:
   - decide the type of items the rules left as `unknown`
   - upgrade a quiz/assignment/event to `exam` ("Midterm" posted as a quiz)
   - write `what_to_do` steps, `topics`, `notes` (e.g. "needs LockDown Browser")
   - drop an item from the to-do list if it isn't real work (e.g. an optional survey)
   Results below LLM_CONFIDENCE_THRESHOLD are ignored. Never guess.

3. TO-DO FILTER (hard rule, the LLM can NOT override it)
   - submitted / excused / marked complete in Canvas -> NOT in the to-do list
   - only assignment / quiz / exam / discussion can be in the to-do list
"""

import re
from dataclasses import dataclass, field

from .models import (
    ClassifiedBy,
    DataSource,
    Item,
    ItemType,
    RawItem,
    SourceKind,
    SuggestedAction,
)

EXAM_PATTERN = re.compile(r"\b(mid-?terms?|exams?|final exam)\b", re.IGNORECASE)

ACTION_FOR_TYPE = {
    ItemType.assignment: SuggestedAction.summarize_steps,
    ItemType.discussion: SuggestedAction.summarize_steps,
    ItemType.quiz: SuggestedAction.schedule_block,
    ItemType.exam: SuggestedAction.exam_prep,
    ItemType.event: SuggestedAction.none,
    ItemType.unknown: SuggestedAction.none,
}

TODO_TYPES = {ItemType.assignment, ItemType.quiz, ItemType.exam, ItemType.discussion}


@dataclass
class LLMResult:
    type: ItemType
    confidence: float
    reason: str
    include_in_todo: bool = True
    what_to_do: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def rule_type(raw: RawItem) -> tuple[ItemType, ClassifiedBy, str]:
    """Layer 1. Exam keywords are checked first (but never on announcements, whose
    titles mention exams all the time: 'Calculator policy for quizzes and exams')."""
    if raw.source_kind != SourceKind.announcement and (m := EXAM_PATTERN.search(raw.title)):
        return ItemType.exam, ClassifiedBy.keyword, f"Title contains '{m.group(0)}'"
    if raw.source_kind == SourceKind.quiz_list:
        return ItemType.quiz, ClassifiedBy.rule, "Canvas type: quiz"
    if "online_quiz" in raw.submission_types:
        return ItemType.quiz, ClassifiedBy.rule, "Submission type is online_quiz"
    if raw.source_kind == SourceKind.discussion:
        return ItemType.discussion, ClassifiedBy.rule, "Canvas type: discussion"
    if raw.source_kind == SourceKind.assignment_list:
        return ItemType.assignment, ClassifiedBy.rule, "Canvas type: assignment"
    if raw.source_kind == SourceKind.calendar_event:
        return ItemType.event, ClassifiedBy.rule, "Canvas type: calendar event"
    return ItemType.unknown, ClassifiedBy.none, "No rule matched"


def is_done(raw: RawItem) -> tuple[bool, str]:
    if raw.submitted:
        return True, "Already submitted in Canvas"
    if raw.excused:
        return True, "Excused in Canvas"
    if raw.marked_complete:
        return True, "Marked complete in the Canvas planner"
    return False, ""


def classify(
    raw: RawItem,
    course_code: str,
    data_source: DataSource,
    llm: LLMResult | None = None,
    threshold: float = 0.7,
) -> Item:
    item_type, by, reason = rule_type(raw)
    confidence = None
    use_llm = llm is not None and llm.confidence >= threshold

    # Layer 2: the LLM refines, it doesn't override Canvas's hard facts.
    if use_llm:
        if item_type == ItemType.unknown:
            item_type, by, reason = llm.type, ClassifiedBy.llm, llm.reason
            confidence = llm.confidence
        elif llm.type == ItemType.exam and item_type in (ItemType.quiz, ItemType.assignment, ItemType.event):
            item_type, by, reason = ItemType.exam, ClassifiedBy.llm, llm.reason
            confidence = llm.confidence
    elif llm is not None and item_type == ItemType.unknown:
        reason = f"LLM not confident enough ({llm.confidence:.2f} < {threshold})"
        by, confidence = ClassifiedBy.llm, llm.confidence

    # Layer 3: to-do filter. Submitted/excused/complete always wins.
    done, done_reason = is_done(raw)
    if done:
        in_todo, todo_reason = False, done_reason
    elif item_type not in TODO_TYPES:
        in_todo, todo_reason = False, f"Type '{item_type.value}' is not a to-do"
    elif use_llm and not llm.include_in_todo:
        in_todo, todo_reason = False, f"LLM: {llm.reason}"
    else:
        in_todo, todo_reason = True, "Not submitted yet"

    notes = list(llm.notes) if use_llm else []
    needs_lockdown = raw.requires_lockdown or "lockdown" in raw.title.lower()
    if needs_lockdown and not any("lockdown" in n.lower() for n in notes):
        notes.append("Requires Respondus LockDown Browser")

    return Item(
        id=raw.id,
        course_id=raw.course_id,
        course_code=course_code,
        type=item_type,
        title=raw.title,
        due_at=raw.due_at,
        points=raw.points,
        source_url=raw.url,
        submitted=raw.submitted,
        in_todo=in_todo,
        todo_reason=todo_reason,
        what_to_do=raw.steps or (llm.what_to_do if use_llm else []),
        topics=raw.topics or (llm.topics if use_llm else []),
        notes=notes,
        suggested_action=ACTION_FOR_TYPE[item_type],
        classified_by=by,
        confidence=confidence,
        reason=reason,
        data_source=data_source,
    )
