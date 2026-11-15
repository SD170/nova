# Current events & phone news alerts (Amrita's draft)

Owner: Amrita (AmritaSeeram). Today's news for students — politics, world, science, tech, education, sports, their teams, their course subjects, anything they add — as a web page, a spoken digest for Jarvis, and **push notifications on their phone** matched to their interests.

## Accuracy first

- **Today only:** stories from the last 24 hours. Undated stories are dropped. Course topics look back 3 days, since research news moves slower.
- **Straight from newsrooms:** RSS feeds from NPR, BBC, The New York Times, PBS NewsHour, The Guardian, CBS, ABC, Al Jazeera, The Washington Post, ESPN, BBC Sport, Nature, ScienceDaily, Inside Higher Ed, Ars Technica and The Verge (each feed checked live).
- **Trusted only (default on):** keyword search results (Google News and the keyed APIs) only count if they come from an established newsroom, or a university newsroom for course topics.
- **Cross-checked:** the same story from different outlets is merged, so each story shows **"Confirmed by N outlets"** or **"Single source so far"**, with links to every version.
- **Alerts only for confirmed stories:** phone notifications are only sent for stories that 2 or more outlets have reported.
- Every item links to the original article.

## Sources and keys

Works with **no keys**. Each key added to `.env` switches on another provider automatically (see `.env.example`):

| Provider | Key | Free tier |
|---|---|---|
| Newsroom RSS feeds (16 outlets) | none | unlimited |
| Google News search | none | — |
| ESPN league feeds | none | — |
| The Guardian Open Platform | `GUARDIAN_API_KEY` | free developer key |
| New York Times Top Stories | `NYT_API_KEY` | free |
| GNews | `GNEWS_API_KEY` | 100 requests/day |
| NewsData.io | `NEWSDATA_API_KEY` | 200 credits/day |
| NewsAPI.org | `NEWSAPI_KEY` | free plan is localhost-only |

## Phone notifications (Web Push)

- **Android (Chrome):** open the site and tap **Get phone alerts**.
- **iPhone (iOS 16.4+):** open in Safari, tap Share, choose **Add to Home Screen**, open *Jarvis News* from the home screen, then tap **Get phone alerts**.
- New subscribers get one welcome alert (today's top confirmed story). After that, the server checks each subscriber's personal digest every 10 minutes (`PUSH_INTERVAL_SECONDS`) and sends up to 3 **new confirmed** stories.
- Nothing is sent during quiet hours (default 10pm to 7am, the student's local time; adjustable on the page).
- Changing interests or the trusted toggle on the page updates that phone's alerts.
- The push signing keys are generated locally on first run (`.vapid_private.pem`). Subscriptions are stored in `subscriptions.json`. Both are gitignored, and no push account or signup is needed.
- **The phone needs an HTTPS address.** Phones only allow push on secure sites, and they can't open `localhost`. Use the team's deployed host, or a tunnel while testing:
  `cloudflared tunnel --url http://localhost:9003` (Cloudflare quick tunnel; it prints an `https://….trycloudflare.com` link to open on the phone).
  Subscriptions are tied to the site address, so if the tunnel URL changes, turn alerts on again.

## Run

```bash
cd drafts/amrita-current-events
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python server.py        # http://localhost:9003
.venv/Scripts/python -m pytest        # 15 offline tests (network and push are faked)
```

## API

- `POST /news/digest`: `{interests?, per_topic?, since?, window_hours?=24, trusted_only?=true}` returns `{items: [{id, title, url, source, published_at, topic, outlets, confirmed, also_reported_by, summary}], speak, sources, keys, ...}`. An interest is `{label, kind: section|topic|sports|course|tech, section?, query?, league?}`, where section is one of top, politics, world, science, tech, education, sports, business or health.
- `GET /news/digest?topics=world,Phoenix Suns,AI`: quick form. Section names map to newsroom feeds; anything else is a keyword search.
- `GET /news/interests`: default demo interests.
- Push: `GET /push/public-key`, `POST /push/subscribe`, `POST /push/unsubscribe`, `POST /push/test`, `GET /push/status`.
- `POST /news/tools`: voice-assistant (Vapi-style) webhook for `get_news_digest`. Docs at `/news/docs`.

## Orchestrator / voice hook

```python
from news.tools import NEWS_TOOLS   # same fn(args) -> dict shape as apps/voice/server.py mock tools
TOOLS.update(NEWS_TOOLS)            # adds get_news_digest -> {speak, items[...] with url + outlets}
```

## Next

Pull interests from the student's real profile or supermemory, and courses from Canvas. Host behind the team's HTTPS domain so phone alerts work without a tunnel.
