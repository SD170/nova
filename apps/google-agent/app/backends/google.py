"""Real Gmail + Google Calendar over their REST APIs (OAuth token from google_auth.py).

Safety by construction:
  - Gmail: read + drafts only. There is no send call anywhere in this file.
  - Calendar: the student's own calendar is read-only. We only ever create / change / delete
    events on the separate "Nova" calendar this app created (scope calendar.app.created).
"""

import asyncio
import base64
import html
import logging
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..config import Settings
from ..google_auth import GoogleAuth
from ..models import (
    Attachment,
    Block,
    CalendarEvent,
    DataSource,
    DraftResult,
    EventSpec,
    GoogleLoginExpired,
    MessageNotFound,
    RawEmail,
)
from .base import WorkspaceBackend

log = logging.getLogger(__name__)

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3"
BODY_CAP = 60_000


def _hdr(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\xa0]+", " ", raw)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", raw).strip()


def walk_parts(payload: dict) -> tuple[str, str, list[Attachment]]:
    """-> (plain_text, html_text, attachments) from a Gmail message payload."""
    plain, htm, atts = [], [], []

    def visit(p: dict) -> None:
        mime = p.get("mimeType", "")
        body = p.get("body", {})
        if p.get("filename") and body.get("attachmentId"):
            atts.append(Attachment(filename=p["filename"], mime_type=mime,
                                   size_bytes=body.get("size")))
        elif mime == "text/plain" and body.get("data"):
            plain.append(_b64(body["data"]))
        elif mime == "text/html" and body.get("data"):
            htm.append(_b64(body["data"]))
        for sub in p.get("parts", []) or []:
            visit(sub)

    visit(payload)
    return "\n".join(plain), "\n".join(htm), atts


def to_raw_email(m: dict, with_body: bool = False) -> RawEmail:
    payload = m.get("payload", {})
    name, addr = parseaddr(_hdr(payload, "From"))
    labels = m.get("labelIds", [])
    e = RawEmail(
        id=m["id"], thread_id=m.get("threadId", ""), from_name=name or addr, from_email=addr,
        to=_hdr(payload, "To"), subject=_hdr(payload, "Subject") or "(no subject)",
        snippet=html.unescape(m.get("snippet", "")),
        date=datetime.fromtimestamp(int(m.get("internalDate", "0")) / 1000, tz=timezone.utc),
        unread="UNREAD" in labels, labels=labels,
        has_attachments=payload.get("mimeType", "") == "multipart/mixed",
        message_id_header=_hdr(payload, "Message-ID") or _hdr(payload, "Message-Id") or None,
    )
    if with_body:
        plain, htm, atts = walk_parts(payload)
        body = plain.strip() or html_to_text(htm)
        e.body_text = body[:BODY_CAP]
        e.attachments = atts
        e.has_attachments = bool(atts)
    return e


class GoogleBackend(WorkspaceBackend):
    name = "google"
    data_source = DataSource.live

    def __init__(self, settings: Settings):
        self.auth = GoogleAuth(settings)
        self.tz = ZoneInfo(settings.timezone)
        self.tz_name = settings.timezone
        self.nova_name = settings.nova_calendar_name
        self.http = httpx.AsyncClient(timeout=30)
        self._account: str | None = None
        self._nova_id: str | None = None
        self._nova_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.http.aclose()

    async def login_status(self) -> str:
        return self.auth.status()

    # ---------------- http ----------------

    async def _req(self, method: str, url: str, **kw: Any) -> dict:
        token = await self.auth.access_token()
        resp = await self.http.request(method, url, headers={"Authorization": f"Bearer {token}"},
                                       **kw)
        if resp.status_code == 401:
            self.auth.expired = True
            raise GoogleLoginExpired("Google rejected the token. Run "
                                     "`python -m scripts.google_login` again.")
        if resp.status_code == 404 and "/messages/" in url:
            raise MessageNotFound(url.rsplit("/", 1)[-1])
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", {}).get("message", resp.text[:200])
            except ValueError:
                msg = resp.text[:200]
            raise RuntimeError(f"Google API {resp.status_code}: {msg}")
        return resp.json() if resp.content else {}

    async def account(self) -> str:
        if not self._account:
            self._account = (await self._req("GET", f"{GMAIL}/profile")).get("emailAddress", "")
        return self._account

    # ---------------- Gmail ----------------

    async def search_messages(self, query: str, max_results: int) -> list[RawEmail]:
        listing = await self._req("GET", f"{GMAIL}/messages",
                                  params={"q": query, "maxResults": max_results})
        ids = [m["id"] for m in listing.get("messages", [])]
        sem = asyncio.Semaphore(8)

        async def meta(mid: str) -> RawEmail | None:
            async with sem:
                try:
                    m = await self._req(
                        "GET", f"{GMAIL}/messages/{mid}",
                        params=[("format", "metadata"), ("metadataHeaders", "From"),
                                ("metadataHeaders", "To"), ("metadataHeaders", "Subject"),
                                ("metadataHeaders", "Message-ID")])
                    return to_raw_email(m)
                except MessageNotFound:
                    return None

        found = [e for e in await asyncio.gather(*(meta(i) for i in ids)) if e]
        found.sort(key=lambda e: e.date, reverse=True)
        return found

    async def get_message(self, message_id: str) -> RawEmail:
        m = await self._req("GET", f"{GMAIL}/messages/{message_id}", params={"format": "full"})
        return to_raw_email(m, with_body=True)

    async def create_draft(self, to: str, subject: str, body: str,
                           reply_to_message_id: str | None) -> DraftResult:
        thread_id = ""
        msg = EmailMessage()
        in_reply_to = None
        if reply_to_message_id:
            orig = await self._req(
                "GET", f"{GMAIL}/messages/{reply_to_message_id}",
                params=[("format", "metadata"), ("metadataHeaders", "From"),
                        ("metadataHeaders", "Reply-To"), ("metadataHeaders", "Subject"),
                        ("metadataHeaders", "Message-ID"), ("metadataHeaders", "References")])
            p = orig.get("payload", {})
            thread_id = orig.get("threadId", "")
            to = to or _hdr(p, "Reply-To") or _hdr(p, "From")
            orig_subject = _hdr(p, "Subject")
            if not subject:
                subject = orig_subject if orig_subject.lower().startswith("re:") \
                    else f"Re: {orig_subject}"
            mid = _hdr(p, "Message-ID") or _hdr(p, "Message-Id")
            if mid:
                msg["In-Reply-To"] = mid
                msg["References"] = f"{_hdr(p, 'References')} {mid}".strip()
                in_reply_to = reply_to_message_id
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload: dict[str, Any] = {"message": {"raw": raw}}
        if thread_id:
            payload["message"]["threadId"] = thread_id
        d = await self._req("POST", f"{GMAIL}/drafts", json=payload)
        return DraftResult(
            draft_id=d.get("id", ""), thread_id=d.get("message", {}).get("threadId", thread_id),
            to=to, subject=subject, body=body, in_reply_to=in_reply_to,
            gmail_url="https://mail.google.com/mail/u/0/#drafts", data_source=DataSource.live)

    # ---------------- Calendar ----------------

    @staticmethod
    def _rfc(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _parse_event(self, e: dict, calendar: str) -> CalendarEvent | None:
        if e.get("status") == "cancelled":
            return None
        s, en = e.get("start", {}), e.get("end", {})
        all_day = "date" in s
        try:
            if all_day:
                start = datetime.fromisoformat(s["date"]).replace(tzinfo=self.tz)
                end = datetime.fromisoformat(en["date"]).replace(tzinfo=self.tz)
            else:
                start = datetime.fromisoformat(s["dateTime"])
                end = datetime.fromisoformat(en["dateTime"])
        except (KeyError, ValueError):
            return None
        priv = e.get("extendedProperties", {}).get("private", {})
        return CalendarEvent(
            id=e["id"], title=e.get("summary", "(no title)"), start=start, end=end,
            all_day=all_day, location=e.get("location", ""),
            description=e.get("description", ""), calendar=calendar,
            html_link=e.get("htmlLink", ""), canvas_item_id=priv.get("canvas_item_id"))

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        data = await self._req("GET", f"{CAL}/calendars/primary/events", params={
            "timeMin": self._rfc(start), "timeMax": self._rfc(end), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": 100})
        return [ev for it in data.get("items", []) if (ev := self._parse_event(it, "primary"))]

    async def _find_nova(self) -> str | None:
        if self._nova_id:
            return self._nova_id
        data = await self._req("GET", f"{CAL}/users/me/calendarList",
                               params={"minAccessRole": "owner"})
        for c in data.get("items", []):
            if c.get("summary") == self.nova_name:
                self._nova_id = c["id"]
                break
        return self._nova_id

    async def _ensure_nova(self) -> str:
        async with self._nova_lock:
            found = await self._find_nova()
            if found:
                return found
            c = await self._req("POST", f"{CAL}/calendars", json={
                "summary": self.nova_name, "timeZone": self.tz_name,
                "description": "Canvas deadlines and study blocks added by Nova."})
            self._nova_id = c["id"]
            log.info("Created the '%s' calendar", self.nova_name)
            return self._nova_id

    async def free_busy(self, start: datetime, end: datetime) -> list[Block]:
        items = [{"id": "primary"}]
        nova = await self._find_nova()
        if nova:
            items.append({"id": nova})
        data = await self._req("POST", f"{CAL}/freeBusy", json={
            "timeMin": self._rfc(start), "timeMax": self._rfc(end), "items": items})
        blocks = []
        for cal in data.get("calendars", {}).values():
            for b in cal.get("busy", []):
                blocks.append(Block(start=datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
                                    end=datetime.fromisoformat(b["end"].replace("Z", "+00:00"))))
        return sorted(blocks, key=lambda b: b.start)

    async def list_nova_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        cal = await self._find_nova()
        if not cal:
            return []
        out: list[CalendarEvent] = []
        token = None
        while True:
            params: dict[str, Any] = {"timeMin": self._rfc(start), "timeMax": self._rfc(end),
                                      "singleEvents": "true", "maxResults": 250}
            if token:
                params["pageToken"] = token
            data = await self._req("GET", f"{CAL}/calendars/{cal}/events", params=params)
            out += [ev for it in data.get("items", []) if (ev := self._parse_event(it, "nova"))]
            token = data.get("nextPageToken")
            if not token:
                return out

    def _body(self, spec: EventSpec) -> dict[str, Any]:
        priv = {"nova_source": "canvas" if spec.canvas_item_id else "nova"}
        if spec.canvas_item_id:
            priv["canvas_item_id"] = spec.canvas_item_id
        return {
            "summary": spec.title, "description": spec.description, "location": spec.location,
            "start": {"dateTime": spec.start.astimezone(self.tz).isoformat(),
                      "timeZone": self.tz_name},
            "end": {"dateTime": spec.end.astimezone(self.tz).isoformat(),
                    "timeZone": self.tz_name},
            "reminders": {"useDefault": False,
                          "overrides": [{"method": "popup", "minutes": m}
                                        for m in spec.reminders_minutes]},
            "extendedProperties": {"private": priv},
        }

    async def create_nova_event(self, spec: EventSpec) -> CalendarEvent:
        cal = await self._ensure_nova()
        e = await self._req("POST", f"{CAL}/calendars/{cal}/events", json=self._body(spec))
        return self._parse_event(e, "nova")  # type: ignore[return-value]

    async def update_nova_event(self, event_id: str, spec: EventSpec) -> CalendarEvent:
        cal = await self._ensure_nova()
        e = await self._req("PUT", f"{CAL}/calendars/{cal}/events/{event_id}",
                            json=self._body(spec))
        return self._parse_event(e, "nova")  # type: ignore[return-value]

    async def delete_nova_event(self, event_id: str) -> None:
        cal = await self._ensure_nova()
        await self._req("DELETE", f"{CAL}/calendars/{cal}/events/{event_id}")
