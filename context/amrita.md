# Amrita — context + notes

Owner: Amrita (GitHub: AmritaSeeram)
Role: **News & ASU events tools — today's accurate news for each student's interests, ASU campus events, and phone news alerts**
Code: `drafts/amrita-current-events/` (FastAPI, port **9004** — the `news_*` slot in Saswata's locked design)

**Not my scope (changed):** course materials, retrieval, quiz generation, study plans. The `materials_*` / retrieval-quiz service (`:9003` in the design, `RETRIEVAL_QUIZ_PORT=9002` in `shared.env`) currently has **no owner** — team needs to decide who takes it or drop it.

## Status (Nov 15, early)

- ✅ **Tool catalog** (6 tools) — every capability is one tool call, also exposed as a plain HTTP endpoint (Abishek's pattern) and as OpenAI-style function definitions at `GET /tools`.
- ✅ **News from 16 newsrooms + news search**, no keys needed; 5 keyed news APIs switch on automatically when a key is added.
- ✅ **ASU events** from ASU's own public feeds (official calendar + Sun Devil Central student orgs).
- ✅ **Accuracy rules**: today's news only (since the student's local midnight), newest first, trusted newsrooms only (default), same story across outlets merged → "confirmed by N outlets".
- ✅ **Phone push alerts** per student's interests (Web Push / PWA), confirmed stories only, quiet hours. Tested through a real push service.
- ✅ **UI tool file** `client/newsTools.ts` + React hooks `client/useNews.ts` — typed, live data by default (≤60 s old).
- ✅ 36 offline tests (network faked).
- ⏳ Public HTTPS tunnel for `:9004` (needed for phones + remote brain) — not started on my machine yet.

## Decisions (locked)

1. **Data layer only.** Curation/ranking against the student's memory happens in the brain (Saswata's rule). This service never writes to supermemory.
2. **Separate HTTP service**, same shape as `apps/browser-agent`: `app/main.py` routes only, `app/service.py` logic, `app/models.py` shapes, `app/config.py` env.
3. **Every item has `url`** to the original article / event page (team's source_url rule) and `data_source: "live"`.
4. **Reads never block for long:** fresh cache (15 min) → instant; stale → instant + background refresh; first call ~1–3 s (all sources fetched in parallel).
5. **Auth:** `X-Jarvis-Key` header (same scheme as Abishek) on all tool endpoints when `NEWS_AGENT_API_KEY` is set. `/health`, the student web page and push routes stay open.
6. **No fake data.** If a source fails, its topic shows `ok: false`; nothing is invented.

## Tool catalog — the brain's view (port 9004)

| Brain tool | Method + path | Returns |
|---|---|---|
| `get_available_topics()` | `GET /topics` | `{sections: [{id, label, outlets[]}], custom_topics, examples}` |
| `fetch_news(topics, since_hours?, tz_offset_minutes?, trusted_only=true, per_topic=5, live=false)` | `GET /news?topics=world,Phoenix Suns,AI policy` | `{topics, count, links: [url...], items: [NewsItem], by_topic, speak}` |
| `fetch_asu_events(days=7, query?, campus?, limit=25, live=false)` | `GET /events?days=7&query=career fair` | `{count, links: [url...], items: [Event], sources, speak}` |
| `get_news_item(item_id)` | `GET /news/item/{id}` | one `NewsItem` + `text` (article text when the publisher allows) — 404 `item_not_found` |
| `dedupe_news(items)` | `POST /news/dedupe` body `[{id, title, source, url}]` | `{clusters: [{lead_id, ids, sources, outlets, confirmed}]}` |
| `get_news_health()` | `GET /health` | `{ok, tools, keyed_sources, cached_stories, push_subscribers, auth_required}` |
| (Saswata's contract name) | `GET /news/candidates?topics=...&since=24h` | same as `fetch_news`, up to 15 per topic (raw pool for ranking) |

Default window = **today** in the student's timezone (Arizona unless `tz_offset_minutes` is sent), newest first, each item has `age_minutes`; `since_hours` = rolling window instead.
`live=true` → fetched right now (never older than 60 s) instead of the 15-min cache; use for "latest" / "breaking".

Tool-call routes (if the brain prefers one URL): `GET /tools` (function definitions), `POST /tools/call {name, arguments}`, `POST /tools/vapi` (Vapi tool-calls envelope).

**`topics` is comma-separated.** Section names (`top, politics, world, science, tech, education, sports, business, health` + aliases like `technology`, `us politics`, `economy`) read newsroom feeds; anything else (a team, a person, a course subject, a hobby) is a news search filtered to trusted outlets.

System-prompt policy for the brain:
```
"what's in the news", "news about X"         → fetch_news(topics="X")
"what news can you follow"                   → get_available_topics
"what's happening on campus / at ASU"        → fetch_asu_events(days=7)
"career fair", "free events", "club meeting" → fetch_asu_events(query=...)
"tell me more about that story"              → get_news_item(id)
Always cite `url` when mentioning a story or event. Prefer stories with confirmed=true.
```

### NewsItem (real example, trimmed)
```json
{
  "id": "3f1c9a2b7d10",
  "title": "Italy fines Meta €805m over accessing users' photos",
  "url": "https://www.bbc.co.uk/news/articles/cwn83gxemk35o",
  "source": "BBC News",
  "published_at": "2026-11-14T18:33:08Z",
  "topic": "World",
  "outlets": 2,
  "confirmed": true,
  "also_reported_by": [{"source": "CBS News", "url": "https://www.cbsnews.com/..."}],
  "summary": "...",
  "trusted": true,
  "data_source": "live"
}
```

### Event (real example, trimmed)
```json
{
  "id": "sdc-413945",
  "title": "sunhacks 9.0",
  "starts_at": "2026-11-14T16:00:00Z",
  "ends_at": "2026-11-15T19:00:00Z",
  "location": "...",
  "host": "sunhacks",
  "category": "...",
  "cost": "Free",
  "url": "https://sundevilcentral.eoss.asu.edu/rsvp_boot?id=413945",
  "source": "Sun Devil Central",
  "data_source": "live"
}
```

## Sources — full list

**News, no key needed (RSS feeds straight from the newsroom, each checked live):**

| Section | Outlets |
|---|---|
| top | NPR, The New York Times, BBC News, PBS NewsHour, CBS News, ABC News |
| politics | NPR, NYT, The Washington Post, The Guardian, PBS NewsHour, CBS News, BBC (US & Canada) |
| world | BBC News, NPR, NYT, The Guardian, Al Jazeera, PBS NewsHour, CBS News |
| science | NPR, NYT, BBC, The Guardian, Nature, ScienceDaily |
| tech | NPR, NYT, BBC, Ars Technica, The Verge |
| education | NPR, NYT, BBC, The Guardian, Inside Higher Ed |
| sports | ESPN, BBC Sport (+ ESPN league JSON for NBA/NFL/college football/...) |
| business | NPR, NYT, BBC |
| health | NPR, NYT, BBC |

**News search, no key:** Google News RSS search (any topic, filtered to the trusted-outlet list in `app/outlets.py`).

**Keyed news APIs (optional, auto-enabled when the key is in `.env`):**

| Provider | Env var | Free tier | Where to get it |
|---|---|---|---|
| The Guardian Open Platform | `GUARDIAN_API_KEY` | free developer key | open-platform.theguardian.com/access |
| New York Times Top Stories | `NYT_API_KEY` | free | developer.nytimes.com |
| GNews | `GNEWS_API_KEY` | 100 req/day | gnews.io |
| NewsData.io | `NEWSDATA_API_KEY` | 200 credits/day | newsdata.io |
| NewsAPI.org | `NEWSAPI_KEY` | localhost-only dev plan | newsapi.org |

**ASU events — ASU publishes no public API key for students**, so these are ASU's own public feeds:

| Source | URL | What |
|---|---|---|
| ASU Events (official calendar) | `https://asuevents.asu.edu/feed-json` | ~500 upcoming university events: talks, arts, athletics, Barrett, career services |
| Sun Devil Central (CampusGroups / SunDevilSync) | `https://sundevilcentral.eoss.asu.edu/mobile_ws/v17/mobile_events_list` | student-organization events (the list logged-out visitors see) |

Not used: the CampusGroups Data Export API (needs an admin-only `X-CG-API-Secret`), Stova @ ASU (department API keys only).

## Phone alerts (Web Push)

Student page at `/` → "Get phone alerts" (Android Chrome; iPhone after "Add to Home Screen"). Server checks each subscriber's interests every 10 min and pushes **new stories confirmed by 2+ outlets**, max 3 per check, never during quiet hours (default 10 pm–7 am local). VAPID keys generated locally (`.vapid_private.pem`, gitignored). Phones need an HTTPS URL → Cloudflare tunnel like Abishek's.

## Setup

```bash
cd drafts/amrita-current-events
python -m venv .venv && .venv/Scripts/activate        # macOS: source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env
uvicorn app.main:app --port 9004                       # docs: http://localhost:9004/docs
pytest                                                 # 36 tests, no network
```

## Handoffs

- **Saswata (brain):** register the 6 tools (definitions at `GET /tools`, or map names → endpoints from the table). Base URL `http://localhost:9004` (tunnel URL → `shared.env` `PUBLIC_NEWS_BASE` once up). Header `X-Jarvis-Key` if I set `NEWS_AGENT_API_KEY` (I'll send the key privately). Daily Pulse "interests" lane → `fetch_news(topics=<from supermemory>)` + `fetch_asu_events`.
- **Shruti / UI team:** copy `drafts/amrita-current-events/client/newsTools.ts` and `useNews.ts` into `src/tools/`. Use `useLiveNews(topics)` / `useAsuEvents({days})` or `fetchNews(...)`; route LLM tool calls with `callNewsTool(name, args)`. Set `VITE_NEWS_BASE` if not on localhost. Render `items` with `url`, `source`, `published_at`, and the `confirmed` / `outlets` badge; events with `starts_at`, `location`, `url`. CORS already allows Vite `:5173` and Electron.
- **Team:** decide who owns course materials / retrieval-quiz (no longer me).

## Open questions

- Public tunnel for `:9004` on demo day, or run everything on one laptop?
- Should the brain push its curated Daily Pulse through my push channel (`POST /push/...`), or keep alerts news-only?
