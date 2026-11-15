"""The contract every browser backend (mock / tinyfish) must follow.

Backends only FETCH. They return raw, unclassified data.
Classification happens once, in classify.py, the same for every backend.

Per sync the service calls:
    start_sync() -> fetch_courses() -> fetch_raw_items(c) -> fetch_item_detail(r)
    -> fetch_materials(c) -> end_sync()        (end_sync always runs, even on error)
"""

from abc import ABC, abstractmethod

from ..models import Course, DataSource, Material, RawItem


class CanvasLoginExpired(Exception):
    """Canvas answered 'not logged in'. The user must sign in again (Duo once)."""


class BrowserBackend(ABC):
    name: str
    data_source: DataSource = DataSource.live

    async def start_sync(self) -> None:
        """Open browser / sessions needed for one sync. Default: nothing."""

    async def end_sync(self) -> None:
        """Close what start_sync opened. Must never raise."""

    @abstractmethod
    async def fetch_courses(self) -> list[Course]:
        """Current courses for the logged-in student."""

    @abstractmethod
    async def fetch_raw_items(self, course: Course) -> list[RawItem]:
        """Assignments, quizzes, discussions, events for one course."""

    async def fetch_item_detail(self, raw: RawItem) -> RawItem:
        """Fill in instructions/submission types. Default: no-op."""
        return raw

    @abstractmethod
    async def fetch_materials(self, course: Course) -> list[Material]:
        """Lecture files/pages for one course."""

    async def close(self) -> None:
        """Release long-lived resources at app shutdown."""
