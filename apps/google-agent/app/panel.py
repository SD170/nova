"""One call for the side panel: every tab's data, each section independent.

GET /panel/summary -> {today, mail, courses, news, linkedin, memory, saved, quiz}. A section
that fails returns {"ok": false, "error": "..."} and never blanks the others. The UI polls
this every ~45 s and polls /panel/feed (a few seconds) for notifications.
Everything is compact and display-ready (short course codes, spoken-style due times).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from .models import DocumentResult
from .quiz_models import Quiz
from .voice import (
    ago,
    compact_email,
    compact_event,
    cut,
    short_course,
    short_title,
    when_label,
)

log = logging.getLogger(__name__)
SECTION_TIMEOUT = 15


def _parse(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


async def _today(svc) -> dict:
    brief = await svc.canvas._get("/brief", {"days": 7})
    due = [{"id": i["id"], "course": short_course(i.get("course_code")),
            "title": short_title(i.get("title")), "due": when_label(_parse(i["due_at"])) if _parse(i.get("due_at")) else "no due date",
            "points": i.get("points"), "type": i.get("type"), "source_url": i.get("source_url", "")}
           for i in brief.get("items", [])[:8]]
    events = await svc.events(1)
    return {"due": due, "count": len(brief.get("items", [])),
            "events": [compact_event(e) for e in events.events[:6]],
            "data_source": brief.get("data_source", "")}


async def _mail(svc) -> dict:
    r = await svc.inbox(72, 20)
    return {"total": r.total, "important_count": r.important_count,
            "needs_reply_count": r.needs_reply_count,
            "emails": [compact_email(e) for e in r.emails[:6]], "data_source": r.data_source.value}


async def _courses(svc) -> dict:
    courses, _ = await svc.canvas.courses()
    out = []
    for c in courses:
        info = svc.exam._cache_get(str(c["id"]))     # cached only: never triggers Gemini here
        exam = info.exams[0] if info and info.exams else None
        out.append({"id": c["id"], "code": short_course(c.get("code")), "name": cut(c.get("name", ""), 60),
                    "exam": {"name": exam.name, "date": exam.date_text} if exam else None})
    return {"courses": out}


async def _news(svc) -> dict:
    n = await svc.headlines("top", 4)
    return {"stories": n["stories"]}


async def _linkedin(svc) -> dict:
    s = await svc.canvas._get("/linkedin/summary", {"max_people": 3})
    return {"posts_seen": s.get("posts_seen", 0), "engaged_posts": s.get("engaged_posts", 0),
            "people": [{"name": p.get("name", ""), "headline": cut(p.get("headline", ""), 70),
                        "why": (p.get("reasons") or [""])[0], "action": p.get("suggested_action", ""),
                        "url": p.get("profile_url", "")} for p in s.get("people", [])[:3]],
            "companies": [c.get("name", "") for c in s.get("companies", [])[:4]],
            "interests": [i.get("topic", "") for i in s.get("interests", [])[:5]]}


async def _memory(svc) -> dict:
    if not svc.memory.enabled:
        return {"enabled": False, "facts": [], "recent": []}
    p, recent = await asyncio.gather(svc.memory.profile(), svc.memory.recent(6))
    return {"enabled": True, "facts": (p["static"] + p["dynamic"])[:6], "recent": recent}


def _saved(svc) -> list[dict]:
    """Files Nova saved (quiz cards, documents), newest first, with where they live."""
    quiz_by_doc: dict[str, Quiz] = {}
    for f in svc.exam.dir.glob("*.json") if svc.exam.dir.exists() else []:
        try:
            q = Quiz(**json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
        if q.pdf:
            quiz_by_doc[q.pdf.id] = q
    out = []
    for d in svc.docs.list(20):
        q = quiz_by_doc.get(d.id)
        out.append({"id": d.id, "title": d.title, "filename": d.filename, "format": d.format,
                    "kind": "quiz_cards" if q else "document", "course": q.course_code if q else "",
                    "download_url": d.download_url, "saved_path": q.saved_path if q else None,
                    "size_bytes": d.size_bytes, "created_at": d.created_at.isoformat(),
                    "when": ago(d.created_at)})
    return out


async def build_summary(svc) -> dict:
    async def run(name, coro):
        try:
            return name, {"ok": True, **await asyncio.wait_for(coro, SECTION_TIMEOUT)}
        except Exception as exc:  # one broken source must not blank the panel
            log.info("panel section %s failed: %s", name, exc)
            return name, {"ok": False, "error": str(exc)[:140]}

    pairs = await asyncio.gather(run("today", _today(svc)), run("mail", _mail(svc)),
                                 run("courses", _courses(svc)), run("news", _news(svc)),
                                 run("linkedin", _linkedin(svc)), run("memory", _memory(svc)))
    out = dict(pairs)
    quiz = svc.exam.latest()
    out["saved"] = _saved(svc)
    out["quiz"] = svc.exam.view(quiz).model_dump() if quiz else None
    out["data_source"] = svc.backend.data_source.value
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    return out
