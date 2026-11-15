"""Daily, accuracy-first news digest built from a student's interests.

Interest kinds:
  section  -> reputable outlet feeds for that section (world, politics, science, tech,
              education, sports, business, health, top) + every keyed API that is configured
  topic / course / sports / tech with a query -> keyword search (Google News + keyed APIs),
              filtered to trusted newsrooms by default
  sports with a league and no team -> ESPN league feed

Accuracy rules:
  * only stories published in the last `window_hours` (default 24 = "today's news")
  * keyword results from unknown sites are dropped unless trusted_only=False
  * the same story from different outlets is merged; `outlets` counts independent
    newsrooms reporting it and `confirmed` is true when 2+ did
  * every item links to the original publisher
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import outlets, sources

DEFAULT_INTERESTS: list[dict] = [
    {"label": "Top stories", "kind": "section", "section": "top"},
    {"label": "US politics", "kind": "section", "section": "politics"},
    {"label": "World", "kind": "section", "section": "world"},
    {"label": "Science", "kind": "section", "section": "science"},
    {"label": "Tech", "kind": "section", "section": "tech"},
    {"label": "Education", "kind": "section", "section": "education"},
    {"label": "Sports", "kind": "section", "section": "sports"},
    {"label": "ASU Sun Devils", "kind": "sports", "query": "Arizona State Sun Devils"},
    # Sample courses until Canvas is connected (mirror apps/voice/server.py mocks).
    {"label": "CSE 310 · Data Structures", "kind": "course", "query": "computer science algorithms research"},
    {"label": "MAT 243 · Discrete Math", "kind": "course", "query": "mathematics research"},
]

MAX_INTERESTS = 20
KINDS = ("section", "topic", "sports", "course", "tech")


def normalize(interests: Optional[list[dict]]) -> list[dict]:
    out = []
    for i in (interests or DEFAULT_INTERESTS)[:MAX_INTERESTS]:
        label = str(i.get("label") or i.get("query") or "").strip()[:80]
        if not label:
            continue
        kind = i.get("kind") if i.get("kind") in KINDS else "topic"
        section = i.get("section") if i.get("section") in outlets.SECTIONS else None
        if kind == "tech" and not i.get("query"):
            kind, section = "section", "tech"
        if kind == "section" and not section:
            kind = "topic"
        out.append({"label": label, "kind": kind, "query": str(i.get("query") or label)[:120],
                    "league": i.get("league"), "section": section})
    return out


def _fetchers(it: dict, per: int):
    label, q, section = it["label"], it["query"], it["section"]
    if it["kind"] == "section":
        for name, url in outlets.FEEDS[section]:
            yield outlets.outlet_feed(name, url, label, per)
        for fn in outlets.keyed_fetchers():
            yield fn(label, None, section, per)
        if outlets.active_keys()["nyt"]:
            yield outlets.nyt(label, section, per)
        return
    is_whole_league = re.sub(r"[^a-z]+", "-", label.lower()).strip("-") == it.get("league")
    if it["kind"] == "sports" and it.get("league") in sources.ESPN_LEAGUES and is_whole_league:
        yield sources.espn_news(it["league"], label, per)
        return
    yield sources.google_news(q, label, per * 2)
    for fn in outlets.keyed_fetchers():
        yield fn(label, q, None, per)


# ───────────────────────── story clustering (corroboration) ─────────────────────────

STOP = set("""a an the and or but of to in on at for from by with as is are was were be been has have had it its
this that these those after before over under into about amid than then new says say said will would could
can may might not no yes who what when where why how his her their they them he she we you your our us vs""".split())


def _tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", title.lower()) if len(w) > 2 and w not in STOP}


def _same_story(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    shared = len(a & b)
    return shared / len(a | b) >= 0.4 or (shared >= 4 and shared / min(len(a), len(b)) >= 0.45)


def cluster(items: list[sources.Item]) -> list[dict]:
    groups: list[dict] = []
    for item in items:
        toks = _tokens(item.title)
        for g in groups:
            if _same_story(toks, g["tokens"]):
                g["members"].append(item)
                g["tokens"] |= toks
                break
        else:
            groups.append({"tokens": set(toks), "members": [item]})
    out = []
    for g in groups:
        m = g["members"]
        # Prefer a trusted outlet's version with a summary as the headline we show.
        lead = sorted(m, key=lambda i: (not outlets.is_trusted(i.source), not i.summary, -(len(i.published_at or ""))))[0]
        names = []
        for i in m:
            if i.source not in names:
                names.append(i.source)
        d = lead.as_dict()
        d["outlets"] = len(names)
        d["confirmed"] = len(names) >= 2
        also, seen_src = [], {lead.source}
        for i in m:
            if i.source not in seen_src:
                seen_src.add(i.source)
                also.append({"source": i.source, "url": i.url})
        d["also_reported_by"] = also[:6]
        d["trusted"] = outlets.is_trusted(lead.source)
        d["published_at"] = max((i.published_at for i in m if i.published_at), default=lead.published_at)
        votes: dict[str, int] = {}
        for i in m:
            votes[i.topic] = votes.get(i.topic, 0) + 1
        d["_topics"], d["_votes"] = list(votes), votes
        out.append(d)
    return out


# ───────────────────────── build ─────────────────────────

FETCH_DEADLINE = 12  # seconds per source; a slow feed never holds up the digest
COURSE_WINDOW = 72   # research/university news moves slower than daily headlines
ACADEMIC = re.compile(r"\b(university|college|institute|school of|academy|lab(?:oratory)?)\b", re.I)


async def _bounded(coro):
    return await asyncio.wait_for(coro, FETCH_DEADLINE)


def _cutoff(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds").replace("+00:00", "Z")


async def build(interests: Optional[list[dict]] = None, per_topic: int = 5, since: Optional[str] = None,
                window_hours: int = 24, trusted_only: bool = True) -> dict:
    ints = normalize(interests)
    jobs, owners = [], []
    for it in ints:
        for coro in _fetchers(it, max(per_topic, 6)):
            jobs.append(_bounded(coro))
            owners.append(it["label"])
    results = await asyncio.gather(*jobs, return_exceptions=True)

    kind_of = {it["label"]: it["kind"] for it in ints}
    order = {it["label"]: n for n, it in enumerate(ints)}
    status: dict[str, dict] = {it["label"]: {"topic": it["label"], "ok": False, "count": 0, "providers": [],
                                             "window_hours": COURSE_WINDOW if it["kind"] == "course" else window_hours}
                               for it in ints}
    pool: list[sources.Item] = []
    for owner, res in zip(owners, results):
        st = status[owner]
        if isinstance(res, BaseException):
            continue
        st["ok"] = True
        course = kind_of[owner] == "course"
        cutoff = _cutoff(max(window_hours, COURSE_WINDOW) if course else window_hours)
        for item in res:
            if not item.published_at or item.published_at < cutoff:
                continue  # current only: nothing stale, nothing undated
            if trusted_only and not item.provider.endswith("RSS") and not outlets.is_trusted(item.source) \
                    and not (course and ACADEMIC.search(item.source)):
                continue
            pool.append(item)
            if item.provider not in st["providers"]:
                st["providers"].append(item.provider)

    # Cluster across ALL topics so a story reported by NPR (politics) and BBC (world)
    # counts as one story confirmed by two outlets, shown once.
    stories = cluster(pool)
    for s in stories:
        s["topic"] = min(s.pop("_topics"), key=lambda t: (-s["_votes"][t], order[t]))
        s.pop("_votes")
    stories.sort(key=lambda s: (s["outlets"], s["published_at"] or ""), reverse=True)
    final: list[dict] = []
    for it in ints:
        kept = [s for s in stories if s["topic"] == it["label"]][:per_topic]
        status[it["label"]]["count"] = len(kept)
        final.extend(kept)

    new = [s for s in final if since and s["published_at"] and s["published_at"] > since]
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "window_hours": window_hours,
        "trusted_only": trusted_only,
        "interests": ints,
        "items": final,
        "new_count": len(new),
        "sources": list(status.values()),
        "keys": outlets.active_keys(),
        "speak": spoken_digest(final, ints),
    }


def spoken_digest(items: list[dict], interests: list[dict], topics: int = 4) -> str:
    if not items:
        return "I couldn't find any news from the last day for your interests right now."
    today = datetime.now().strftime("%A, %B ") + str(datetime.now().day)
    lines = []
    for it in interests:
        top = next((i for i in items if i["topic"] == it["label"]), None)
        if top:
            conf = f", reported by {top['outlets']} outlets" if top["outlets"] >= 2 else f", from {top['source']}"
            lines.append(f"In {it['label']}: {top['title']}{conf}.")
        if len(lines) >= topics:
            break
    return f"Here's your news for {today}. " + " ".join(lines) + " Want me to read more on any of these?"
