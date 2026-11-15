# Jarvis Care (draft) — accessible, voice-first health module

Owner: Amrita (AmritaSeeram). Spec: [`context/jarvis-care-build-brief.md`](../../../context/jarvis-care-build-brief.md).
Lives in `drafts/amrita/` so it doesn't touch anyone else's app. Not yet wired into the orchestrator.

## Run

```bash
cd drafts/amrita/jarvis-care
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python server.py
# open http://localhost:7080/health
```

`HEALTH_PORT` (default 7080) and `JARVIS_HOME_URL` (the "Academics" link, default `http://localhost:7070/`) are optional. No API keys needed.

## What works vs. demo

| Feature | Status |
|---|---|
| Voice input (tap to talk) | Works in Chrome / Edge / Safari via browser SpeechRecognition. Other browsers: typed input (fully equivalent). |
| Spoken replies, Replay, Slower, Stop, Mute, voice + speed choice | Works via browser `speechSynthesis`; silent mode supported. |
| After-visit care plan (sample, .txt/.pdf upload, paste) | Works. Deterministic extraction; every step quotes its exact source line; unclear items marked "Needs confirmation". Photos not supported. |
| Reminders | Work, only after you confirm (dialog or saying "confirm"). Stored in server memory for the session — no phone/calendar alerts. |
| Bill vs. EOB comparison | Works on pipe-table text/PDF; arithmetic in code. Sample shows one possible mismatch ($35 vs $18) and one pending claim. |
| Visit prep (check-ins, editable questions, download) | Works. |
| Appointments | Free-time suggestions from Sam's **demo** schedule or times you type. **No real calendar or clinic booking.** |
| Timeline | Works; class deadlines are **demo** data and opt-in. |
| Accessibility panel | Text 100–200%, dark / high contrast, reduced motion, simple vs detailed language, speech settings; persisted in browser. Voice commands ("make the text bigger") change the real settings. |
| AI model | **None yet** — replies come from a rules engine (`engine: "rules"`), so the demo is repeatable offline. |

All sample documents and people are fictional and labeled "Demo data".

## Integration (for the orchestrator / Vapi)

- HTTP: `POST /api/health/handle` with the `JarvisCareRequest` shape from the brief → `JarvisCareResponse` (`replyText`, `spokenSummary`, `cards`, `actions`, `isMock`).
- Python tool registry (same signature as `apps/voice/server.py` mock tools): `from care.tools import HEALTH_TOOLS; TOOLS.update(HEALTH_TOOLS)` → one tool, `health_care(utterance, session_id)`.
- Vapi-style webhook: `POST /api/health/tools`; tool definition in `care/tools.VAPI_TOOL_DEFINITION`.

## Layout

`server.py` (FastAPI + static UI) · `care/` (agent, after-visit extraction, bills, scheduling, visit prep, session store, samples) · `static/` (HTML, CSS, ES modules: router, voice, prefs, views).

## Not done yet

Automated test suite + axe accessibility scan, LLM provider hookup, real calendar, image OCR.
