# Current events & news notifications (Amrita's draft)

Owner: Amrita (AmritaSeeram). Personalized headlines for students — politics, sports teams, course subjects, tech, anything they add — with browser notifications and a spoken digest Jarvis can read aloud.

**Works with no API keys.** Starts with free public sources; a keyed source is used automatically if a key is added later.

| Source | Used for | Key needed |
|---|---|---|
| Google News RSS (search + sections) | politics, world, science, course subjects, teams, any topic | No |
| ESPN public news feed | whole leagues (NBA, NFL, college football, …) | No |
| Hacker News (Algolia API) | tech | No |
| NewsAPI.org | extra coverage | Optional `NEWSAPI_KEY` in `.env` |

Every headline links to the original publisher (`url`), matching the team's "always cite a source" rule.

## Run

```bash
cd drafts/amrita-current-events
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python server.py        # http://localhost:9003
.venv/Scripts/python -m pytest        # offline tests (network is faked)
```

Port 9003 (next free one after `RETRIEVAL_QUIZ_PORT=9002` in `shared.env`). Override with `NEWS_PORT`.

## Web page (`/`)

Interest chips (toggle / remove / add your own: topic, sports team, course subject, tech) · filter tabs · headline cards · **Turn on notifications** (browser notifications for new headlines, checked every 5 minutes) · **Read my digest aloud**. Interests are saved in the browser. Course chips are sample courses until Canvas is connected.

## API

- `POST /news/digest` — `{interests?: [{label, kind: topic|sports|course|tech, query?, league?, section?}], per_topic?, since?}` → `{items: [{id, title, url, source, published_at, topic, provider, summary}], speak, new_count, sources, interests, generated_at}`
- `GET /news/digest?topics=politics,Phoenix Suns,AI` — quick form
- `GET /news/interests` — default demo interests
- `POST /news/tools` — Vapi-style tool-calls webhook for `get_news_digest`
- Docs: `/news/docs`

## Orchestrator / voice hook

Same `fn(args) -> dict` shape as the mock tools in `apps/voice/server.py`:

```python
from news.tools import NEWS_TOOLS, VAPI_TOOL_DEFINITION
TOOLS.update(NEWS_TOOLS)   # adds get_news_digest
```

Returns `speak` (read it aloud) and `items` with source URLs.

## Next

Pull interests from the student's real profile / supermemory and courses from Canvas; push notifications through the main Jarvis UI.
