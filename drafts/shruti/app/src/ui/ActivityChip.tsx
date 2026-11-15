// Top-left API-activity chip. Mirrors the task panel's language:
// `glass glass--depth` pill with a live pulse dot. Click to expand a
// timeline of recent API calls. Four providers shown with brand accents
// (Solana purple, TinyFish teal, Supermemory amber, Gemini cyan).
//
// Data: SSE at /events on the bridge. Events are the small shape
// documented in apps/brain/bridge.py:
//   { id, provider, tool, status: 'start'|'ok'|'error', ms?, ts, note? }
//
// Why SSE: EventSource is the smallest footprint way to stream from
// FastAPI + works in Electron's Chromium without extra deps.

import { useEffect, useMemo, useRef, useState } from 'react'

// buttons never take focus — SPACE stays push-to-talk (matches TaskPanel)
const noFocus = (e: React.MouseEvent) => e.preventDefault()

// Same 3D-tilt helper as TaskPanel so the two glass cards feel identical.
const tilt = {
  onMouseMove(e: React.MouseEvent<HTMLElement>) {
    const el = e.currentTarget
    const r = el.getBoundingClientRect()
    const nx = (e.clientX - r.left) / r.width - 0.5
    const ny = (e.clientY - r.top) / r.height - 0.5
    el.style.setProperty('--ry', `${(nx * 14).toFixed(2)}deg`)
    el.style.setProperty('--rx', `${(-ny * 12).toFixed(2)}deg`)
    el.style.setProperty('--mx', `${((nx + 0.5) * 100).toFixed(1)}%`)
    el.style.setProperty('--my', `${((ny + 0.5) * 100).toFixed(1)}%`)
  },
  onMouseLeave(e: React.MouseEvent<HTMLElement>) {
    const el = e.currentTarget
    el.style.setProperty('--rx', '0deg')
    el.style.setProperty('--ry', '0deg')
  },
}

const BRIDGE_URL =
  (import.meta.env.VITE_BRIDGE_URL as string | undefined) ??
  'http://127.0.0.1:8000'

type Provider = 'solana' | 'tinyfish' | 'supermemory' | 'gemini' | 'other'
export interface ApiEvent {
  id: string
  provider: Provider | string
  tool: string
  status: 'start' | 'ok' | 'error'
  ms?: number
  ts: number
  note?: string
}

/** Tracked sponsor providers. Everything else gets filtered out of the UI. */
const TRACKED: Provider[] = ['solana', 'tinyfish', 'supermemory', 'gemini']
const isTracked = (p: string): p is Provider =>
  (TRACKED as string[]).includes(p)

/** Collapse start+ok/error into a single row keyed by (provider, tool) at ts0. */
interface Row {
  key: string
  provider: Provider | string
  tool: string
  startedAt: number
  finishedAt?: number
  ms?: number
  status: 'start' | 'ok' | 'error'
  note?: string
  /** How many identical calls (same provider+tool) are collapsed in this row. */
  count?: number
  /** True if any collapsed call failed (any error in the group). */
  anyErrored?: boolean
  /** Sum of ms for the group — for an average display. */
  totalMs?: number
  doneCount?: number
}

/** Coalesce raw events into rows. Keeps the UI stable even if start/ok land
 *  out of order on SSE reconnect (rare, but we see it on bridge restart). */
function coalesce(events: ApiEvent[]): Row[] {
  const byKey = new Map<string, Row>()
  for (const ev of events) {
    const key = `${ev.provider}|${ev.tool}`
    if (ev.status === 'start') {
      // Always open a new row on start (even if a prev row exists —
      // the user fired the action again).
      byKey.set(key + ':' + ev.ts, {
        key: key + ':' + ev.ts,
        provider: ev.provider,
        tool: ev.tool,
        startedAt: ev.ts,
        status: 'start',
        note: ev.note,
      })
    } else {
      // Find the most recent open row for this (provider,tool); update it.
      // Walk the map from newest backwards; small N (<= 200) so linear fine.
      const openRow = [...byKey.values()]
        .filter((r) => r.provider === ev.provider && r.tool === ev.tool && r.status === 'start')
        .sort((a, b) => b.startedAt - a.startedAt)[0]
      if (openRow) {
        openRow.finishedAt = ev.ts
        openRow.ms = ev.ms ?? Math.round((ev.ts - openRow.startedAt) * 1000)
        openRow.status = ev.status
        if (ev.note) openRow.note = ev.note
      } else {
        // Stand-alone ok/error (no prior start — shouldn't happen but be safe)
        byKey.set(key + ':' + ev.ts, {
          key: key + ':' + ev.ts,
          provider: ev.provider,
          tool: ev.tool,
          startedAt: ev.ts,
          finishedAt: ev.ts,
          ms: ev.ms,
          status: ev.status,
          note: ev.note,
        })
      }
    }
  }
  // Newest first, cap at 50 rows shown.
  const rows = [...byKey.values()].sort((a, b) => b.startedAt - a.startedAt)

  // Second pass — fold runs of identical (provider,tool) rows (sorted
  // newest-first) into one row with a count badge. Runs are consecutive
  // in the sort; we stop folding the moment a different (provider,tool)
  // breaks the run. This matches the user's ask: ONE Gemini-generateContent
  // chip with "×3" instead of three stacked toasts.
  const folded: Row[] = []
  for (const r of rows) {
    const head = folded[folded.length - 1]
    if (head && head.provider === r.provider && head.tool === r.tool) {
      head.count = (head.count ?? 1) + 1
      head.anyErrored = head.anyErrored || r.status === 'error'
      if (r.ms != null) {
        head.totalMs = (head.totalMs ?? head.ms ?? 0) + r.ms
        head.doneCount = (head.doneCount ?? 1) + (r.status !== 'start' ? 1 : 0)
      }
      // Keep the most recent start/finish — head is already the newer one
      // because we sorted newest-first.
    } else {
      folded.push({
        ...r,
        count: 1,
        anyErrored: r.status === 'error',
        totalMs: r.ms,
        doneCount: r.status !== 'start' ? 1 : 0,
      })
    }
  }
  return folded.slice(0, 50)
}

export function ActivityChip() {
  const [events, setEvents] = useState<ApiEvent[]>([])
  const [open, setOpen] = useState(false)
  // Shimmer on new event (same visual language as the TaskPanel count bump)
  const [bump, setBump] = useState(0)
  const prevCount = useRef(0)

  useEffect(() => {
    // SSE connect. EventSource reconnects automatically on drop.
    const es = new EventSource(`${BRIDGE_URL}/events`)
    es.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data) as ApiEvent
        if (!isTracked(ev.provider)) return // scope: 4 providers only
        setEvents((xs) => {
          // Dedupe by event id in case SSE replays
          if (xs.some((x) => x.id === ev.id)) return xs
          const next = [...xs, ev].slice(-200) // match server ring size
          return next
        })
      } catch {
        /* ignore malformed */
      }
    }
    es.onerror = () => { /* EventSource retries on its own; no-op */ }
    return () => es.close()
  }, [])

  const rows = useMemo(() => coalesce(events), [events])

  useEffect(() => {
    if (rows.length > prevCount.current) setBump((b) => b + 1)
    prevCount.current = rows.length
  }, [rows.length])

  const inFlight = rows.filter((r) => r.status === 'start').length
  const hasAny = rows.length > 0
  const total = rows.length

  return (
    <div className="activity">
      <button
        className={`glass glass--depth activity-head ${!hasAny ? 'activity-head--empty' : ''} ${open ? 'activity-head--open' : ''}`}
        {...tilt}
        onClick={() => hasAny && setOpen((o) => !o)}
        onMouseDown={noFocus}
        tabIndex={-1}
        aria-expanded={open}
      >
        <span className="glass-sweep" />
        <span className={`activity-dot ${inFlight > 0 ? 'activity-dot--live' : ''}`} />
        <span>
          <span key={bump} className={bump ? 'activity-count activity-count--bump' : 'activity-count'}>
            {total}
          </span>{' '}
          API {total === 1 ? 'call' : 'calls'}
        </span>
        {hasAny && <Chevron open={open} />}
      </button>

      {open && (
        <div className="activity-stack">
          <div className="activity-scroll">
            {rows.map((r, i) => (
              <EventCard key={r.key} row={r} index={i} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function EventCard({ row, index }: { row: Row; index: number }) {
  const count = row.count ?? 1
  const avgMs = row.totalMs != null && row.doneCount && row.doneCount > 0
    ? Math.round(row.totalMs / row.doneCount) : row.ms
  const effectiveStatus = row.anyErrored && row.status !== 'start' ? 'error' : row.status
  // Hover copy for the four provider families so judges + users understand
  // what each API call actually accomplishes. Keep it short + plain-English.
  const tipText = tipFor(row.tool)
  return (
    <div
      className={`glass glass--depth activity-card activity-card--${effectiveStatus} activity-card--${row.provider}`}
      style={{ animationDelay: `${index * 50}ms`, ['--sweep-delay' as string]: `${index * 50 + 160}ms` }}
      {...tilt}
      title={tipText}
    >
      <span className="glass-sweep" />
      <div className="activity-row">
        <span className={`activity-icon activity-icon--${row.provider}`}>
          <ProviderIcon provider={row.provider as Provider} />
        </span>
        <div className="activity-main">
          <div className="activity-tool">
            {row.tool}
            {count > 1 && <span className="activity-badge">×{count}</span>}
          </div>
          <div className="activity-meta">
            <span className={`activity-provider activity-provider--${row.provider}`}>
              {prettyName(row.provider)}
            </span>
            <span className="activity-sep">·</span>
            <span className={`activity-status activity-status--${effectiveStatus}`}>
              {statusLabel(effectiveStatus, avgMs, count)}
            </span>
          </div>
          {row.note && <div className="activity-note">{row.note}</div>}
        </div>
      </div>
    </div>
  )
}

function statusLabel(status: Row['status'], ms?: number, count: number = 1): string {
  if (status === 'start') return 'in flight…'
  if (status === 'error') return `failed${ms != null ? ` in ${fmtMs(ms)}` : ''}${count > 1 ? ` (avg)` : ''}`
  return ms != null ? `${fmtMs(ms)}${count > 1 ? ' avg' : ''}` : 'done'
}

function fmtMs(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** Plain-English explanation for each tool label. Shown as a hover
 *  tooltip so a stage demo viewer or judge can hover any pill and read
 *  what the API call actually does. */
function tipFor(tool: string): string {
  const t = tool.toLowerCase()
  if (t.includes('hash anchor') || t.includes('memo'))
    return 'Writes the SHA-256 of your signed credential onto Solana devnet (Memo program). Anyone can look it up and prove the credential existed at that moment.'
  if (t.includes('mint credential nft') || t.includes('metaplex'))
    return 'Mints a Metaplex NFT whose metadata URI points at your R2-hosted credential JSON. The NFT is the portable on-chain anchor — share its mint address and anyone can verify.'
  if (t.includes('screenshot') || t.includes('myasu'))
    return 'Opens your MyASU grades page via TinyFish-powered Playwright and screenshots the grade details div. The PNG becomes the witness inside the signed credential.'
  if (t.includes('ask gemini') || t.includes('classify canvas'))
    return 'Sends a prompt to Google Gemini with a strict JSON schema. The response is either a classification of your Canvas items (to-do vs info) or structured quiz rows.'
  if (t.includes('recall from supermemory'))
    return 'Semantic search across everything Nova has saved about you — weak exam topics, preferences, prior quiz performance.'
  if (t.includes('save fact to supermemory'))
    return "Fire-and-forget write of a durable fact into Nova's long-term memory. You don't wait for it; the UI just shows it landed."
  if (t.includes('mint queued for retry'))
    return "The mint pipeline hit a snag (usually Canvas offline or Solana degraded). Nova wrote your request to a disk queue and will retry every 60s until it lands."
  if (t.includes('mint retry succeeded'))
    return 'A queued mint request went through on a later attempt. Credential is now anchored on devnet.'
  return 'Sponsor-track API call Nova just made. Hover any pill to see what it means.'
}

function prettyName(p: string): string {
  switch (p) {
    case 'solana': return 'Solana'
    case 'tinyfish': return 'TinyFish'
    case 'supermemory': return 'Supermemory'
    case 'gemini': return 'Gemini'
    default: return p
  }
}

function ProviderIcon({ provider }: { provider: Provider }) {
  const p = {
    viewBox: '0 0 24 24', width: 18, height: 18, fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.5,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
  }
  switch (provider) {
    case 'solana':
      // three stacked skewed bars — the Solana wordmark feel
      return (
        <svg {...p}>
          <path d="M5 7.5l12 0-2 -2.5l-12 0z" fill="currentColor" stroke="none" />
          <path d="M5 13l12 0-2 -2.5l-12 0z" fill="currentColor" stroke="none" />
          <path d="M5 18.5l12 0-2 -2.5l-12 0z" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'tinyfish':
      // stylised tiny fish
      return (
        <svg {...p}>
          <path d="M3 12c3-5 9-5 12 0-3 5-9 5-12 0z" />
          <circle cx="8.5" cy="12" r="0.8" fill="currentColor" stroke="none" />
          <path d="M15 12l5-3v6z" />
        </svg>
      )
    case 'supermemory':
      // brain-ish concentric loops
      return (
        <svg {...p}>
          <path d="M8 6a4 4 0 0 0-3.5 6c-.8 2 .8 4.5 3.5 4.5a3.5 3.5 0 0 0 4-1" />
          <path d="M16 6a4 4 0 0 1 3.5 6c.8 2-.8 4.5-3.5 4.5a3.5 3.5 0 0 1-4-1" />
          <path d="M12 7v10" />
        </svg>
      )
    case 'gemini':
      // 4-point diamond (Gemini mark)
      return (
        <svg {...p}>
          <path d="M12 3c0 5 4 9 9 9-5 0-9 4-9 9 0-5-4-9-9-9 5 0 9-4 9-9z" />
        </svg>
      )
    default:
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="8" />
        </svg>
      )
  }
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg className={`activity-chevron ${open ? 'activity-chevron--open' : ''}`}
         viewBox="0 0 16 16" width="12" height="12" fill="none"
         stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M4 6l4 4 4-4" />
    </svg>
  )
}
