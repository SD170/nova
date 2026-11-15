"""The news tool catalog — what the brain (Hermes / Vapi) sees.

Each tool is ALSO a plain HTTP endpoint (see main.py), so the brain can register
either the endpoint or call POST /tools/call {name, arguments}.

  get_available_topics()                          GET  /topics
  fetch_news(topics, since_hours, trusted_only,   GET  /news?topics=world,Phoenix Suns,AI
             per_topic)
  fetch_asu_events(days, query, campus, limit)    GET  /events?days=7&query=career fair
  get_news_item(item_id)                          GET  /news/item/{id}
  dedupe_news(items)                              POST /news/dedupe
  get_news_health()                               GET  /health
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from . import events, outlets, push
from .models import DedupeIn
from .service import service

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_available_topics",
            "description": "List the news topics the student can ask for: built-in sections (world, politics, "
                           "science, tech, education, sports, business, health, top) with the newsrooms behind "
                           "each, plus how free-text topics work. Call this when the student asks what news "
                           "Jarvis can follow.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_news",
            "description": "Get today's news for comma-separated topics and return every story with its link. "
                           "Sections (world, politics, tech, sports, ...) read newsroom feeds; anything else "
                           "(a team, person, course subject, hobby) is searched and filtered to trusted outlets. "
                           "Each item has `url`, `source`, `published_at` and `outlets` (how many newsrooms "
                           "reported it). Read `speak` aloud; always share `url` when citing a story.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topics": {"type": "string", "description": "Comma-separated, e.g. \"world, Phoenix Suns, AI policy\""},
                    "since_hours": {"type": "integer", "description": "How far back, 1-72. Default 24 (today).", "default": 24},
                    "trusted_only": {"type": "boolean", "description": "Only established newsrooms. Default true.", "default": True},
                    "live": {"type": "boolean", "description": "true = fetch right now (data at most 60 s old) instead of the 15-min cache. Use when the student asks for the latest/breaking news.", "default": False},
                    "per_topic": {"type": "integer", "description": "Max stories per topic, 1-15. Default 5.", "default": 5},
                },
                "required": ["topics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_asu_events",
            "description": "Upcoming ASU events from ASU's official events calendar and Sun Devil Central "
                           "(student organizations), with a link to each event page. Use for \"what's happening "
                           "on campus\", \"any career fairs this week\", \"free events tonight\", club meetings, "
                           "talks, games. Read `speak` aloud; share `url` for any event you mention.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How many days ahead, 1-60. Default 7.", "default": 7},
                    "query": {"type": "string", "description": "Optional keywords, e.g. \"career fair\", \"AI\", \"free food\"."},
                    "campus": {"type": "string", "description": "Optional: Tempe, Downtown Phoenix, West, Polytechnic, Online."},
                    "limit": {"type": "integer", "description": "Max events, 1-100. Default 25.", "default": 25},
                    "live": {"type": "boolean", "description": "true = fetch right now (data at most 60 s old) instead of the 15-min cache. Use when the student asks for the what's on right now.", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news_item",
            "description": "Full details for one story from fetch_news (by its `id`), including the article text "
                           "when the publisher allows it. Use for \"tell me more about that story\".",
            "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dedupe_news",
            "description": "Group near-duplicate stories (same event, different outlets). Returns clusters with how "
                           "many independent outlets reported each one.",
            "parameters": {
                "type": "object",
                "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "string"}, "title": {"type": "string"}, "source": {"type": "string"},
                    "url": {"type": "string"}, "published_at": {"type": "string"}}, "required": ["id", "title"]}}},
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news_health",
            "description": "Status of the news service: which keyed news APIs are on, cached stories, subscribers.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_NAMES = [t["function"]["name"] for t in TOOL_DEFINITIONS]


class ToolError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _args(arguments: Any) -> dict:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return {"topics": arguments}  # a bare string is treated as the topic list
    return dict(arguments or {})


def _bool(v: Any) -> bool:
    return v.strip().lower() in ("1", "true", "yes") if isinstance(v, str) else bool(v)


async def call(name: str, arguments: Any = None) -> dict:
    a = _args(arguments)
    if name == "get_available_topics":
        return service.available_topics().model_dump()
    if name == "fetch_news":
        topics = a.get("topics")
        if isinstance(topics, list):
            topics = ",".join(map(str, topics))
        if not topics or not str(topics).strip():
            raise ToolError(422, "topics is required, e.g. \"world, Phoenix Suns, AI\"")
        out = await service.fetch_news(topics, a.get("since_hours"), _bool(a.get("trusted_only", True)),
                                       int(a.get("per_topic") or 5), _bool(a.get("live")))
        return out.model_dump()
    if name == "fetch_asu_events":
        return await events.fetch(days=max(1, min(int(a.get("days") or 7), 60)), query=str(a.get("query") or ""),
                                  campus=str(a.get("campus") or ""), limit=max(1, min(int(a.get("limit") or 25), 100)),
                                  live=_bool(a.get("live")))
    if name == "get_news_item":
        item = await service.get_item(str(a.get("item_id") or ""))
        if not item:
            raise ToolError(404, "item_not_found: ids come from fetch_news")
        return item.model_dump()
    if name == "dedupe_news":
        items = [DedupeIn(**i) for i in a.get("items") or []]
        return service.dedupe(items).model_dump()
    if name == "get_news_health":
        return health()
    raise ToolError(404, f"unknown tool: {name}. Available: {', '.join(TOOL_NAMES)}")


def health() -> dict:
    from .config import settings
    return {"ok": True, "data_source": "live", "tools": TOOL_NAMES, "keyed_sources": outlets.active_keys(),
            "cached_stories": service.cached_stories(), "push_subscribers": push.count(),
            "auth_required": bool(settings.api_key)}


# Same fn(args) -> dict shape as the mock tools in apps/voice/server.py (sync, for in-process use).
def _sync(name: str):
    return lambda args=None: asyncio.run(call(name, args))


NEWS_TOOLS = {name: _sync(name) for name in TOOL_NAMES}
