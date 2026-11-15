"""Backend contract: mock (demo data) and google (real Gmail + Calendar) implement this."""

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Block, CalendarEvent, DataSource, DraftResult, EventSpec, RawEmail


class WorkspaceBackend(ABC):
    name: str
    data_source: DataSource

    @abstractmethod
    async def login_status(self) -> str:
        """'ok' | 'not_set_up' | 'expired' | 'demo'"""

    @abstractmethod
    async def account(self) -> str: ...

    # ---- Gmail ----
    @abstractmethod
    async def search_messages(self, query: str, max_results: int) -> list[RawEmail]:
        """Gmail search syntax. Newest first. Metadata only (no body)."""

    @abstractmethod
    async def get_message(self, message_id: str) -> RawEmail:
        """Full message with body_text. Raises MessageNotFound."""

    @abstractmethod
    async def create_draft(self, to: str, subject: str, body: str,
                           reply_to_message_id: str | None) -> DraftResult:
        """Saves to Gmail Drafts. NEVER sends."""

    # ---- Calendar ----
    @abstractmethod
    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """The student's own primary calendar (read-only)."""

    @abstractmethod
    async def free_busy(self, start: datetime, end: datetime) -> list[Block]: ...

    @abstractmethod
    async def list_nova_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Events on the Nova calendar (empty if it does not exist yet)."""

    @abstractmethod
    async def create_nova_event(self, spec: EventSpec) -> CalendarEvent: ...

    @abstractmethod
    async def update_nova_event(self, event_id: str, spec: EventSpec) -> CalendarEvent: ...

    @abstractmethod
    async def delete_nova_event(self, event_id: str) -> None: ...

    async def close(self) -> None:
        return None
