"""News + ASU events: a thin client for Amrita's news service (drafts/amrita-current-events,
port 9004, runs on this laptop) and voice-sized answers on top of it.

Amrita's service owns the data (16 newsrooms, ASU event feeds, accuracy rules). We only
call it, shorten the result, and expose it as MCP tools next to Gmail/Calendar, so Hermes
needs no extra connection. Every story keeps its original `url` (cite it, never invent).
"""

from datetime import datetime, timezone

import httpx

from .models import NewsUnavailable
from .voice import ago, cut, plural, when_label


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compact_story(item: dict, now: datetime | None = None) -> dict:
    published = _parse(item.get("published_at"))
    now = now or datetime.now(timezone.utc)
    return {"id": item.get("id", ""), "title": cut(item.get("title", ""), 110),
            "source": item.get("source", ""), "topic": item.get("topic", ""),
            "outlets": item.get("outlets", 1), "confirmed": bool(item.get("confirmed")),
            "published": ago(published, now) if published else "", "url": item.get("url", "")}


def _ended(item: dict, now: datetime) -> bool:
    ends = _parse(item.get("ends_at")) or _parse(item.get("starts_at"))
    return bool(ends and ends < now)


def compact_event(item: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    starts, ends = _parse(item.get("starts_at")), _parse(item.get("ends_at"))
    if starts and ends and starts <= now <= ends:
        when = "happening now"
    else:
        when = when_label(starts, now) if starts else item.get("when_text", "")
    return {"id": item.get("id", ""), "title": cut(item.get("title", ""), 90), "when": when,
            "location": cut(item.get("location", ""), 50), "host": item.get("host", ""),
            "cost": item.get("cost", ""), "url": item.get("url", "")}


def speak_news(stories: list[dict]) -> str:
    if not stories:
        return "I couldn't find recent news on that."
    top = stories[0]
    out = f"Top story: {cut(top['title'], 90)}"
    out += f", confirmed by {top['outlets']} outlets." if top["confirmed"] else f", from {top['source']}."
    if len(stories) > 1:
        out += f" {len(stories) - 1} more if you want them."
    return out


def speak_asu_events(events: list[dict], total: int, days: int) -> str:
    window = "this week" if days == 7 else f"in the next {days} days"
    if not events:
        return f"I found no ASU events {window}."
    first = events[0]
    lead = "Now" if first["when"] == "happening now" else "Next"
    when = "" if first["when"] == "happening now" else f", {first['when']}"
    return f"{plural(total, 'ASU event')} {window}. {lead}: {cut(first['title'], 60)}{when}."


class NewsClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 45):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def _get(self, path: str, params: dict) -> dict:
        headers = {"X-Jarvis-Key": self.api_key} if self.api_key else {}  # Amrita's header name
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}{path}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise NewsUnavailable(
                f"Could not reach the news service at {self.base_url} ({exc}). Is "
                "drafts/amrita-current-events running on port 9004?") from exc
        if resp.status_code == 401:
            raise NewsUnavailable("The news service rejected our key (NEWS_API_KEY).")
        if resp.status_code != 200:
            raise NewsUnavailable(f"The news service returned HTTP {resp.status_code}.")
        return resp.json()

    async def headlines(self, topics: str, count: int, live: bool) -> dict:
        data = await self._get("/news", {"topics": topics, "since_hours": 24,
                                         "per_topic": max(count, 1), "live": str(live).lower()})
        now = datetime.now(timezone.utc)
        stories = [compact_story(i, now) for i in data.get("items", [])][:count]
        return {"speak": speak_news(stories), "count": len(stories), "stories": stories,
                "generated_at": data.get("generated_at"), "data_source": data.get("data_source", "")}

    async def events(self, days: int, query: str | None, limit: int) -> dict:
        params: dict = {"days": days, "limit": 25}
        if query:
            params["query"] = query
        data = await self._get("/events", params)
        now = datetime.now(timezone.utc)
        all_events = [compact_event(i, now) for i in data.get("items", [])
                      if not _ended(i, now)]  # ongoing ones stay ("happening now")
        shown = all_events[:limit]
        return {"speak": speak_asu_events(shown, len(all_events), days),
                "total": len(all_events), "events": shown,
                "data_source": data.get("data_source", "")}
