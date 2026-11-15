# Voice-turn latency: harness options for the Nova bridge

**Measured baseline on this machine (Nov 15):**
`HERMES_HOME=…shruti hermes chat -q "say hi"` → **real 6.4 s / user 1.9 s** for a trivial 2-word reply with no tool call. So the fixed cost per turn right now is roughly:

- Python interpreter + Hermes import + skill/profile load: **~1.9 s CPU**
- MCP discovery + first-token on Haiku 4.5: **~2.5–3 s wall**
- Subprocess spawn + stdout parse overhead in bridge: **~0.3–0.5 s**

The 1.9 s of CPU is almost pure *cold-boot tax* — it happens every single turn because the bridge shells out. That is the fat you want to cut, not the LLM call.

---

## The honest framing

The latency problem is **not** that Hermes is a slow harness. It's that we're running it in subprocess-per-turn mode. Any Python harness we bootstrap per turn will pay ~0.5–2 s. The question is just which long-lived shape is cheapest to ship in a hackathon.

## Harness survey

| Harness | In-proc lib? | Import cold | Native MCP (streamable-HTTP) | OpenAI-shape streaming out | Keep SOUL.md / profile? |
|---|---|---|---|---|---|
| **Hermes (long-lived)** | sort of — via `hermes acp` socket or `hermes serve` JSON-RPC | one-time ~1.9 s, then 0 per turn | yes (its MCP client) | not natively; bridge converts | **yes, 100% kept** |
| **LangGraph** | yes | ~0.8–1.2 s (langchain is heavy) | via `langchain-mcp-adapters` | manual `astream_events` → SSE | rewrite SOUL/tools as graph nodes |
| **PydanticAI** | yes | ~0.3–0.5 s | yes, `MCPServerStreamableHTTP` first-class | yes, `agent.run_stream()` | rewrite SOUL as system prompt (easy) |
| **OpenAI Agents SDK** (`openai-agents`) | yes | ~0.3–0.5 s | yes (SSE + streamable-HTTP as of mid-2025) | yes, `Runner.run_streamed()` | rewrite; Anthropic requires LiteLLM shim |
| **smolagents** | yes | ~0.3 s | yes (MCP tool wrapper) | no native OAI stream, code-agent paradigm is the wrong shape for voice | rewrite + paradigm mismatch |
| **Mastra** (TS) | yes, in Node | ~0.2 s | yes, native | yes | **full rewrite** of bridge in TS |
| **DSPy** | yes | — | — | — | wrong tool, skip |
| **Direct Anthropic SDK** | n/a | ~0.1 s | you write the MCP client (~80 LOC) | you write SSE (~30 LOC) | SOUL.md becomes a string literal |

## Where the ~2 s actually goes in Hermes today

Not in the LLM call. In order: Python startup → importing hermes + anthropic + MCP clients → reading `config.yaml` / `profile.yaml` → scanning skills dir → connecting to the Canvas MCP server and listing tools → session restore from SQLite. **All of that is one-time if the process stays warm.**

So a long-lived Hermes (option A below) buys back basically all of the 1.9 s for free.

---

## The three options, ranked by time-to-ship

### A) Keep Hermes, make it long-lived — **PICK THIS**

Two concrete shapes, pick one:

**A1. Thin socket daemon** (~2–3 hrs)
Write a tiny Python daemon that imports Hermes once, keeps the agent + MCP connections warm, and exposes a Unix socket (or localhost HTTP) the bridge calls per turn. The bridge becomes a pure translator: Vapi SSE ↔ socket. SOUL.md, profile, memory, MCP — all untouched.

**A2. Use `hermes acp` directly** (~3–5 hrs)
`hermes acp` is already the long-lived JSON-RPC-over-stdio shape (built for VS Code/Zed). Spawn it once at bridge startup, speak ACP, translate to/from OpenAI SSE. More protocol work than A1 but zero custom daemon code.

**Expected latency after:** 2.5–3 s per turn (just the LLM + MCP round trip). Cuts ~1.5–2 s off every turn.

**Dev cost:** 2–5 hrs.
**Risk:** low. We keep every design doc, every skill, memory, SOUL, the whole brain shape.

### B) Swap to PydanticAI — **the "clean-rewrite" option**

If we wanted a cleaner codebase and don't mind tossing Hermes-as-runtime: PydanticAI is the right harness for this job specifically. Native streaming, native MCP streamable-HTTP, works with Anthropic directly, trivial import. The bridge collapses to ~150 LOC.

**Expected latency:** 2–2.5 s per turn (slightly faster than A because no Hermes skill/profile scan).
**Dev cost:** 6–10 hrs. SOUL.md → system prompt (5 min). Memory → write our own tiny file-backed thing or drop for the hackathon (1–2 hrs). Toolset wiring (2–3 hrs). Session-per-call state (1 hr). Testing (2 hrs).
**Risk:** medium. You lose the Hermes ecosystem (skills, memory, curator, kanban) — all the things that make Nova "Nova" on the operator side, not the voice side.

### C) Nuclear: direct Anthropic SDK + 80-LOC MCP client

Totally doable. `anthropic.AsyncAnthropic().messages.stream()` + a tool loop + an MCP streamable-HTTP client (literally just POST + SSE parse). ~250 LOC total including the FastAPI handler.

**Expected latency:** 1.8–2.3 s per turn (fastest).
**Dev cost:** 8–14 hrs. The MCP client is the sneaky part — streamable-HTTP transport has session IDs, resumption, notification streams. You'll spend half a day on edge cases that Hermes/PydanticAI have already debugged.
**Risk:** high in a hackathon. Every bug is yours. No fallback path.

---

## If I were you

**Do A1 (thin socket daemon). Tonight. 2–3 hrs.**

Why:
1. The problem statement is "voice turn is 4.5 s and we want it lower." A1 removes 1.5–2 s and ships before dinner.
2. SOUL.md, memory, MCP, profile all keep working unchanged. No cascading rewrites with 2 days left.
3. If after A1 the turn is still too slow, *then* the bottleneck is actually the LLM/MCP round-trip, and no harness swap would have helped anyway.
4. B and C are only worth it if we also want a cleaner architecture story — that's a post-hackathon rewrite, not a 24-hr judges-are-coming decision.

**Do NOT do B or C unless A1 ships and you still need another second off.** Those are strict upgrades on paper and strict regressions on hackathon risk.

## A1 sketch (so you can judge the work)

```python
# apps/brain/brain_daemon.py — started once, speaks a tiny JSON protocol over a UDS
# Imports Hermes agent + MCP once. Keeps one agent per Vapi call_id (LRU, 50 calls).
# Protocol: { "call_id": str, "persona": str, "text": str } -> streams {"delta": "..."} lines, then {"done": true}
# Bridge replaces subprocess_exec with: asyncio.open_unix_connection("/tmp/nova.sock")
```

The 100-LOC bridge shrinks to ~70 LOC. The daemon is ~120 LOC. No Hermes internals need to be understood — we can keep driving it via the same `hermes.chat` entry point the CLI uses, just inside a persistent asyncio loop.
