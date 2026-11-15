"""Demo backend: realistic fake Canvas data, no network, no keys.

Dates are relative to "now" so /items/next always has something to show.
Everything is labeled data_source=demo — never presented as live.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..models import Course, DataSource, Material, MaterialType, RawItem, SourceKind, TextStatus
from .base import BrowserBackend

PHX = ZoneInfo("America/Phoenix")
BASE = "https://canvas.asu.edu"


def _at(days: int, hour: int, minute: int = 0) -> datetime:
    day = datetime.now(PHX) + timedelta(days=days)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


COURSES = [
    Course(id="cse310", code="CSE 310", name="Data Structures and Algorithms", term="Fall 2026"),
    Course(id="mat343", code="MAT 343", name="Applied Linear Algebra", term="Fall 2026"),
]


def _raw_items() -> dict[str, list[RawItem]]:
    return {
        "cse310": [
            RawItem(
                id="cse310-a3",
                submitted=False,
                course_id="cse310",
                source_kind=SourceKind.assignment_list,
                title="Homework 3: AVL Trees",
                url=f"{BASE}/courses/cse310/assignments/3",
                due_at=_at(2, 23, 59),
                points=50,
                submission_types=["online_upload"],
                steps=[
                    "Read chapter 5 (balanced BSTs)",
                    "Implement AVL insert with rotations",
                    "Submit a .zip with code and README",
                ],
            ),
            RawItem(
                id="cse310-a4",
                submitted=False,
                course_id="cse310",
                source_kind=SourceKind.assignment_list,
                title="Final Project Proposal",
                url=f"{BASE}/courses/cse310/assignments/4",
                due_at=_at(5, 23, 59),
                points=20,
                submission_types=["online_text_entry"],
                steps=["Pick a data-structure topic", "Write a 1-page proposal"],
            ),
            RawItem(
                id="cse310-e2",
                course_id="cse310",
                source_kind=SourceKind.calendar_event,
                title="Midterm 2",
                url=f"{BASE}/calendar?event_id=cse310-e2",
                due_at=_at(6, 10, 30),
                body_text="Midterm 2 in class. Covers AVL trees, heaps and hashing.",
                topics=["AVL trees", "heaps", "hashing"],
            ),
            RawItem(
                id="cse310-n1",
                course_id="cse310",
                source_kind=SourceKind.announcement,
                title="Office hours moved",
                url=f"{BASE}/courses/cse310/discussion_topics/91",
                body_text="This week's office hours are on Thursday 3-4pm in BYENG 210.",
            ),
            RawItem(
                id="cse310-a2",
                submitted=True,
                course_id="cse310",
                source_kind=SourceKind.assignment_list,
                title="Homework 2: Heaps",
                url=f"{BASE}/courses/cse310/assignments/2",
                due_at=_at(-3, 23, 59),  # already past — must not show in /items/next
                points=50,
            ),
        ],
        "mat343": [
            RawItem(
                id="mat343-q5",
                submitted=False,
                course_id="mat343",
                source_kind=SourceKind.quiz_list,
                title="Quiz 5: Eigenvalues",
                url=f"{BASE}/courses/mat343/quizzes/5",
                due_at=_at(3, 10, 30),
                points=10,
            ),
            RawItem(
                id="mat343-c7",
                submitted=True,
                course_id="mat343",
                source_kind=SourceKind.assignment_list,
                title="Weekly Check-in 7",
                url=f"{BASE}/courses/mat343/assignments/7",
                due_at=_at(1, 23, 59),
                points=2,
                submission_types=["online_quiz"],
            ),
            RawItem(
                id="mat343-h6",
                submitted=False,
                course_id="mat343",
                source_kind=SourceKind.assignment_list,
                title="Homework 6",
                url=f"{BASE}/courses/mat343/assignments/6",
                due_at=_at(4, 23, 59),
                points=30,
                steps=["Problems 6.1 #3, #7, #12", "Show all row reductions"],
            ),
        ],
    }


def _week(offset_days: int) -> tuple[date, date]:
    start = datetime.now(PHX).date() + timedelta(days=offset_days)
    return start, start + timedelta(days=6)


MOCK_TEXT = {
    "syllabus-cse310": (
        "CSE 310 Syllabus. Midterm exam in week 9 covers trees (BST, AVL) and heaps. "
        "Final exam covers graphs and hashing.", None),
    "page-cse310-lecture-9": (
        "An AVL tree is a self-balancing binary search tree. For every node, the heights "
        "of the left and right subtrees differ by at most one. After an insert, the tree "
        "is rebalanced with single (LL, RR) or double (LR, RL) rotations. Search, insert "
        "and delete all run in O(log n).", None),
    "file-310010": (
        "[page 1]\nA binary min-heap is a complete binary tree where each parent is <= its "
        "children.\n\n[page 2]\nInsert bubbles up, extract-min bubbles down; both are "
        "O(log n). Build-heap is O(n).", 2),
    "file-343012": (
        "[page 1]\nlambda is an eigenvalue of A if Av = lambda v for some nonzero v. "
        "Eigenvalues are the roots of det(A - lambda I) = 0, the characteristic polynomial.", 1),
}


def _materials() -> dict[str, list[Material]]:
    w_now, w_next = _week(-2), _week(5)
    cse = Course(id="cse310", code="CSE 310", name="", term="")
    mat = Course(id="mat343", code="MAT 343", name="", term="")

    def m(course: Course, mid: str, title: str, mtype: MaterialType, module: str,
          week: tuple[date, date] | None, **kw) -> Material:
        return Material(id=mid, course_id=course.id, course_code=course.code, title=title,
                        type=mtype, url=f"{BASE}/courses/{course.id}/{mid}", module=module,
                        week_start=week[0] if week else None, week_end=week[1] if week else None,
                        **kw)

    return {
        "cse310": [
            Material(id="syllabus-cse310", course_id="cse310", course_code="CSE 310",
                     title="CSE 310 Syllabus", type=MaterialType.syllabus,
                     url=f"{BASE}/courses/cse310/assignments/syllabus"),
            m(cse, "page-cse310-lecture-9", "Lecture 9 - AVL Trees", MaterialType.page,
              "Module 4: Balanced Trees", w_now, module_position=4, position=1),
            m(cse, "file-310010", "Lecture 10 - Heaps.pdf", MaterialType.pdf,
              "Module 5: Heaps", w_next, module_position=5, position=1,
              content_type="application/pdf", size_bytes=820_000),
            m(cse, "file-310099", "Textbook (full).pdf", MaterialType.pdf,
              "Module 0: Readings", None, module_position=0, position=1,
              content_type="application/pdf", size_bytes=48_000_000,
              text_status=TextStatus.too_large),
            m(cse, "link-cse310-77", "Visualgo: AVL demo", MaterialType.link,
              "Module 4: Balanced Trees", w_now, module_position=4, position=2,
              text_status=TextStatus.link_only),
        ],
        "mat343": [
            m(mat, "file-343012", "Lecture 12 - Eigenvalues.pdf", MaterialType.pdf,
              "Week 12: Eigenvalues", w_now, module_position=12, position=1,
              content_type="application/pdf", size_bytes=410_000),
        ],
    }


# Mock "Weekly Check-in 7" is submitted=True, so it must NOT appear in the to-do list.


class MockBackend(BrowserBackend):
    name = "mock"
    data_source = DataSource.demo

    async def fetch_courses(self) -> list[Course]:
        return list(COURSES)

    async def fetch_raw_items(self, course: Course) -> list[RawItem]:
        return _raw_items().get(course.id, [])

    async def fetch_materials(self, course: Course) -> list[Material]:
        return _materials().get(course.id, [])

    async def fetch_material_text(self, material: Material) -> tuple[str, int | None]:
        if material.id not in MOCK_TEXT:
            raise ValueError(f"No mock text for {material.id}")
        return MOCK_TEXT[material.id]
