# apps/linkedin-extension — Nova for LinkedIn

Chrome / Brave extension (Manifest V3). While the student scrolls LinkedIn it reads the
posts **already on their screen** and what they do with them (like, "… more", comment
box, repost, profile click, how long they read). It sends that to the browser agent
(`apps/browser-agent`, port 9001). The **side panel is Nova's LinkedIn screen**: Nova
(a loop of Shruti's avatar) on top, then whatever Nova drafted or researched, then
activity, people, companies, posts and interests.

**It never posts, comments, likes, connects or messages.** The student copies and sends
everything themselves. It doesn't crawl LinkedIn: it only reads what the student's
browser already rendered.

Owner: Abishek (Abishek1801).

## Flow

```
linkedin.com tab
  content.js + parse.js   visible posts + engagement + which post is on screen, every 4 s
  background.js           POST /linkedin/observe  (X-Canvas-Key)
        ▼
browser-agent :9001
  linkedin.py             session store, activity feed, people/companies rules,
                          humanized Gemini drafts (2 options), Nova cards
  li_research.py          company + CEO research (TinyFish search/fetch + Gemini)
        ▲                                   ▲
sidepanel (polls cards every 3 s)     Nova brain (voice) via MCP:
  Nova video · Nova card · activity     linkedin_draft_message, linkedin_research_company,
  people · companies · posts            linkedin_get_research, linkedin_session_summary,
  (Draft / Research buttons)            linkedin_recent_posts
```

Voice and clicks go through the same endpoints, so a draft or research Nova makes by
voice pops up in the panel within about 3 seconds, ready to copy.

## Files

| File | What |
|---|---|
| `manifest.json` | MV3 "Nova for LinkedIn"; permissions `storage`, `sidePanel`; hosts linkedin.com, localhost, 127.0.0.1, `*.trycloudflare.com` |
| `parse.js` | every LinkedIn selector (new 2026 layout + old one as fallback) |
| `content.js` | dwell time, clicks, new posts, on-screen post; scrolls to a post when the panel asks |
| `background.js` | forwards batches to the agent and pings the panel |
| `api.js` | settings in `chrome.storage.local` + `fetch` with `X-Canvas-Key` |
| `sidepanel.*` | the Nova UI; untrusted text rendered with `textContent` only |
| `media/nova-{idle,thinking}.webm` | avatar loops recorded from Shruti's app (`drafts/shruti/app`) |
| `fonts/` | Orbitron + Inter (OFL, from Shruti's app) |

## How to test (step by step)

**0. Restart what changed**
- Browser agent: stop uvicorn (Ctrl+C) and start it again from `apps/browser-agent`:
  `.venv/bin/uvicorn app.main:app --port 9001`
  Research needs `TINYFISH_API_KEY` and drafts need `GEMINI_API_KEY` in `apps/browser-agent/.env`.
- Extension: in `brave://extensions`, click ↻ on the extension. It's now called **Nova for LinkedIn**, version 0.2.0.
  If the name hasn't changed, click **Remove**, then **Load unpacked** on this folder again, and re-enter URL + key in ⚙.
- Close every LinkedIn tab and open `https://www.linkedin.com/feed/` fresh.

**1. Panel and Nova figure**
- Click the extension icon. Nova's head should loop at the top, with **NOVA · READING LINKEDIN** and a green dot.
- If it says NOT CONNECTED: open ⚙, check the URL and key, then click **Save & test**.

**2. Activity**
- Like a post, click "… more" on another, and stay on a third for 10+ seconds.
- Within about 8 s, **Activity** shows "Liked …", "Read more of …" and "Read …" with times.
- Click an activity line. LinkedIn should scroll to that post and outline it in blue.

**3. Reach out to + Companies**
- Like or read a post from a recruiter or founder. They appear under **Reach out to** with a badge.
- Click the person. You see why, plus **Draft reach-out**, **Draft comment**, **Research <company>** and **Profile ↗**.
- **Draft comment** → Nova shows "thinking", and a card pops up with **2** comment options and Copy buttons.
- **Draft reach-out** → a card with a connection note and a message.
- Check the wording: plain, no em dashes, no "Great post!" or "thrilled to".

**4. Research**
- Under **Companies**, click a company (or **Research <company>** on a person).
- A **RESEARCH** card shows a spinner, then in about 20 s: 3–4 sentences on the company and CEO, the CEO's name with a **LinkedIn ↗** button (only if one was found), and 2 messages to copy.
- Older cards stay as small chips under the main card. Click one to bring it back.

**5. Posts you engaged with**
- Open the section and click a post. It scrolls to the post. **Comment** drafts for that post.

**6. Voice through Nova** (after merge: pull, restart the brain bridge, and re-run `apps/brain/setup_vapi.py` so the router knows to send LinkedIn questions to the brain)
- Scroll so one post is in the middle of the screen, then say: *"Nova, what should I comment on this post?"*
  Nova reads the first option, and the card with both options pops up in the panel.
- *"Nova, help me reach out to Priya."* → a reach-out card for Priya's post.
- *"Nova, research Ramp."* → Nova says it's on it, and the research card fills in about 20 s later.
  Then: *"What did you find?"* → Nova reads the short brief.
- *"Nova, who should I reach out to?"* → Nova names the top people.

**7. Pause**
- Click ❚❚. The dot turns amber, and scrolling no longer adds activity. Click ▶ to resume.

**Debugging**
- In the LinkedIn tab Console, filter `[Nova]`. You should see `[Nova] watching N LinkedIn posts`.
- `http://localhost:9001/docs` → **linkedin** section to inspect `/linkedin/cards`, `/linkedin/activity` and the rest.
