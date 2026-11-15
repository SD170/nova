"""Demo backend: realistic fake Canvas data, no network, no keys.

Dates are relative to "now" so /items/next always has something to show.
Everything is labeled data_source=demo — never presented as live.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..models import Course, DataSource, Material, RawItem, SourceKind
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


MATERIALS = {
    "cse310": [
        Material(
            id="cse310-l9",
            course_id="cse310",
            title="Lecture 9 - AVL Trees",
            type="page",
            url=f"{BASE}/courses/cse310/pages/lecture-9",
            extracted_text=(
                "An AVL tree is a self-balancing binary search tree. For every node, the heights "
                "of the left and right subtrees differ by at most one. After an insert, the tree "
                "is rebalanced with single (LL, RR) or double (LR, RL) rotations. Search, insert "
                "and delete all run in O(log n)."
            ),
        ),
        Material(
            id="cse310-l10",
            course_id="cse310",
            title="Lecture 10 - Heaps",
            type="page",
            url=f"{BASE}/courses/cse310/pages/lecture-10",
            extracted_text=(
                "A binary min-heap is a complete binary tree where each parent is <= its children. "
                "Insert bubbles up, extract-min bubbles down; both are O(log n). Build-heap is O(n)."
            ),
        ),
    ],
    "mat343": [
        Material(
            id="mat343-l12",
            course_id="mat343",
            title="Lecture 12 - Eigenvalues",
            type="page",
            url=f"{BASE}/courses/mat343/pages/lecture-12",
            extracted_text=(
                "lambda is an eigenvalue of A if Av = lambda v for some nonzero v. Eigenvalues are "
                "the roots of det(A - lambda I) = 0, the characteristic polynomial."
            ),
        ),
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
        return list(MATERIALS.get(course.id, []))
