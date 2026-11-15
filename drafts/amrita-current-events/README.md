# News & ASU events tools (Amrita)

Today's accurate news for each student's interests, ASU campus events, and phone news alerts — as **tool calls** for the Jarvis brain on **port 9004** (the `news_*` slot in the locked design).
Full design, tool catalog and source list for teammates: `context/amrita.md`.

## Owner

Amrita (GitHub: AmritaSeeram)

## Run locally

```bash
cd drafts/amrita-current-events
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                 # works with every key blank
uvicorn app.main:app --port 9004                     # docs: http://localhost:9004/docs
```
Student page with phone alerts: http://localhost:9004/
**Tests:** `pytest` (31 tests, network faked).

## Tools (port 9004)

Auth: if `NEWS_AGENT_API_KEY` is set, send header `X-Jarvis-Key` on every tool endpoint (`/health`, the page and push routes stay open).

| Tool | Method + path | Returns |
|---|---|---|
| `get_available_topics` | `GET /topics` | sections with their newsrooms + how custom topics work |
| `fetch_news` | `GET /news?topics=world,Phoenix Suns,AI policy&since_hours=24` | `{count, links: [...], items: [...], by_topic, speak}` |
| `fetch_asu_events` | `GET /events?days=7&query=career fair&campus=Tempe` | `{count, links: [...], items: [...], sources, speak}` |
| `get_news_item` | `GET /news/item/{id}` | one story + article text (when the publisher allows) |
| `dedupe_news` | `POST /news/dedupe` | clusters of the same story across outlets |
| `get_news_health` | `GET /health` | tools, keyed sources on/off, cache, subscribers |
| (contract alias) | `GET /news/candidates?topics=…&since=24h` | raw pool for the brain to rank |

One-URL tool calling: `GET /tools` (OpenAI-style function definitions) · `POST /tools/call {"name": "fetch_news", "arguments": {"topics": "world, tech"}}` · `POST /tools/vapi` (Vapi tool-calls envelope).

Example:
```bash
curl "http://localhost:9004/news?topics=world,Phoenix%20Suns,AI%20policy"
curl -X POST localhost:9004/tools/call -H "Content-Type: application/json" \
     -d '{"name":"fetch_asu_events","arguments":{"days":7,"query":"career"}}'
```

## Accuracy rules

1. Last 24 hours only (`since_hours`, max 72); undated stories dropped.
2. Trusted newsrooms only by default (`trusted_only=false` to widen); newsroom RSS feeds are trusted by definition.
3. The same story from several outlets is merged → `outlets` count, `confirmed` when 2+, `also_reported_by` links.
4. Every story and event has `url` to the original page. Failed sources are reported (`ok: false`), never filled in.

## Sources

- **No key:** 16 newsroom RSS feeds (NPR, BBC, NYT, PBS, The Guardian, CBS, ABC, Al Jazeera, Washington Post, ESPN, BBC Sport, Nature, ScienceDaily, Inside Higher Ed, Ars Technica, The Verge), Google News search, ESPN league feeds.
- **ASU events (ASU's public feeds; ASU offers students no API key):** `asuevents.asu.edu/feed-json` (official calendar) and Sun Devil Central / CampusGroups public event list (student orgs).
- **Keyed, optional:** Guardian, NYT, GNews, NewsData.io, NewsAPI — set the key in `.env` and it's used automatically. Links in `.env.example`.

## Env vars (`.env.example`)

| Var | Default | Meaning |
|---|---|---|
| `NEWS_AGENT_API_KEY` | empty | Shared secret for `X-Jarvis-Key` (set before going public) |
| `GUARDIAN_API_KEY` / `NYT_API_KEY` / `GNEWS_API_KEY` / `NEWSDATA_API_KEY` / `NEWSAPI_KEY` | empty | Extra news providers |
| `NEWS_PORT` | `9004` | Port for `python -m app.main` |
| `NEWS_CACHE_TTL_MINUTES` | `15` | How long fetched news counts as fresh |
| `PUSH_INTERVAL_SECONDS` / `PUSH_ENABLED` | `600` / `1` | Phone-alert check interval / on-off |

## Code map

```
app/
  main.py         HTTP routes, X-Jarvis-Key auth, error mapping only
  tools.py        tool catalog: definitions + dispatcher (+ NEWS_TOOLS for in-process use)
  service.py      fetch_news / topics / item / dedupe; comma-topic parsing; non-blocking cache
  digest.py       fetch all sources in parallel, 24h + trusted filters, cross-outlet clustering
  outlets.py      newsroom RSS catalog, trusted-outlet list, keyed news APIs
  sources.py      Google News, ESPN, Hacker News, shared HTTP client
  events.py       ASU Events + Sun Devil Central
  extract.py      article text for get_news_item
  push.py         Web Push phone alerts (VAPID, subscribers, background loop)
  models.py       all JSON shapes
  config.py       env settings
static/           student page (PWA): index.html, app.js, style.css, sw.js, manifest, icons
tests/unit, tests/api, tests/conftest.py   31 tests, no network
```

## Public URL (Cloudflare quick tunnel, same as browser-agent)

```bash
uvicorn app.main:app --port 9004                                   # terminal 1
cloudflared tunnel --no-autoupdate --url http://localhost:9004      # terminal 2 → https://xxx.trycloudflare.com
```
Put it in repo-root `shared.env` as `PUBLIC_NEWS_BASE` (changes every restart). Set `NEWS_AGENT_API_KEY` first. Phones need this HTTPS URL for push alerts.
