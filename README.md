# Student Jarvis

Voice-enabled agentic student assistant. SunHacks 2026, ASU Tempe.

Core demo: "Jarvis, I have an exam on Monday. Check what I need to study, test my knowledge, and find time to revise around my commitments."

## Team

4 people, <24h, deadline Nov 15 2026 @ 11:00am MST.

## Stack targets (sponsor prizes)

- Maritime — per-user agent VM hosting
- supermemory — academic context memory
- TinyFish — web research when Canvas misses
- Gemini — long-context reasoning over course material
- MongoDB Atlas — vector search over notes
- JFF Ventures — future-of-work / student productivity angle
- AWS — generic compute / Bedrock fallback
- Cursor + Grok Bot — dev workflow (free raffle entry)

## Repo layout

```
.
├── AGENTS.md              # auto-loaded team context for Hermes/Claude/Cursor
├── context/               # shared team brain, markdown + source docs
│   ├── 01-project-brief.md
│   └── gpt.pdf
├── apps/                  # per-component (added as work starts)
└── README.md
```

## Getting started (teammates)

```bash
git clone git@github.com:SD170/student-jarvis.git
cd student-jarvis
# any AI tool run from this directory auto-ingests AGENTS.md
```

## Context discipline

Drop new context into `context/` as markdown. Commit. Teammates `git pull` → their AI has the new context on next session. No re-pasting the same docs.
