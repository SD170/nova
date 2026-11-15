"""Orchestrator / Vapi hook. Same `fn(args) -> dict` signature as the mock tools in
apps/voice/server.py, so the orchestrator can do:

    from news.tools import NEWS_TOOLS
    TOOLS.update(NEWS_TOOLS)
"""
from __future__ import annotations

import asyncio

from . import digest


def get_news_digest(args: dict) -> dict:
    """args: {interests?: [{label, kind, query?, league?}], topics?: ["politics", ...], per_topic?: int}"""
    interests = args.get("interests")
    if not interests and args.get("topics"):
        interests = [{"label": t, "kind": "topic", "query": t} for t in args["topics"]]
    result = asyncio.run(digest.build(interests, per_topic=int(args.get("per_topic") or 3)))
    return {
        "speak": result["speak"],
        "items": [{k: i[k] for k in ("id", "title", "source", "url", "published_at", "topic")} for i in result["items"]],
        "source_url_required": True,
    }


NEWS_TOOLS = {"get_news_digest": get_news_digest}

VAPI_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_news_digest",
        "description": "Get current news headlines matched to the student's interests (politics, sports teams, "
                       "course subjects, tech, anything). Read the `speak` text aloud; every item has a source URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"},
                           "description": "Optional topics the student asked about, e.g. ['Suns', 'AI policy']."},
            },
        },
    },
}
