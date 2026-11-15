// Task poller: watches the bridge for Hermes tasks that finished and flips
// the matching UI row to 'done'. Runs while any task is 'running'; stops when
// the queue is empty to save battery.
//
// The bridge exposes GET /tasks?call_id=<id> → {tasks: [{id,question,status,result,...}]}.
// Vapi SDK stashes the active call id on window.__NOVA_CALL_ID__ (see vapiClient.ts).
// We match server task.question → UI task.title (startsWith) to resolve ids.

import { completeTask, failTask, getTasks, subscribe } from './tasks'

const BRIDGE_URL =
  (import.meta.env.VITE_BRIDGE_URL as string | undefined) ??
  'http://127.0.0.1:8000'

// Fast poll while a task is running. Nova usually speaks the answer right
// around when the bridge flips the task to done; we want the UI card to
// catch up within ~half a second so the two land together visually.
// 400ms × 2.5 round-trips on localhost = ~1s worst case. Battery hit is
// negligible — the poller stops the moment the queue drains.
const POLL_MS = 400
let timer: number | null = null

async function tick(): Promise<void> {
  try {
    const cid = (window as Window & { __NOVA_CALL_ID__?: string })
      .__NOVA_CALL_ID__
    if (!cid) return

    const r = await fetch(`${BRIDGE_URL}/tasks?call_id=${encodeURIComponent(cid)}`, {
      cache: 'no-store',
    })
    if (!r.ok) return
    const data = (await r.json()) as {
      tasks?: Array<{
        id: string
        question: string
        status: 'running' | 'done' | 'error'
        result?: string
        result_full?: string
        started_at?: number
        finished_at?: number
      }>
    }

    const uiTasks = getTasks()
    const runningUi = uiTasks.filter((t) => t.status === 'running')
    for (const srv of data.tasks ?? []) {
      if (srv.status !== 'done' && srv.status !== 'error') continue
      // Match strategy, best → worst:
      //   (1) exact server-question == UI title
      //   (2) prefix match either direction
      //   (3) single-running fallback — if only one task is running and server
       //       just finished one, they're the same task. This is what keeps the
       //       UI card from stalling 'Working…' when the title string mismatches
       //       after a tool re-ask or trailing whitespace drift.
      // Match strategy, best → worst. NO 'single-running' fallback because
      // it mis-completes a fresh task with a stale server 'done' entry from
      // a previous turn. Require a real title/question match.
      const match =
        runningUi.find((t) => srv.question && t.title === srv.question) ??
        runningUi
          .slice()
          .reverse()
          .find(
            (t) =>
              srv.question &&
              t.title &&
              (srv.question.startsWith(t.title.replace(/…$/, '')) ||
                t.title.startsWith(srv.question.slice(0, 32))),
          )
      // Second guard: only complete tasks where the server's finished_at is
      // AFTER the UI row's startedAt. Prevents a stale server 'done' event
      // from leaking into a UI row the user just added.
      if (match && srv.finished_at && (srv.finished_at * 1000) < match.createdAt) {
        continue
      }
      if (!match) continue
      const full = srv.result_full ?? srv.result ?? ''
      if (srv.status === 'done') {
        completeTask(match.id, { summary: full })
      } else {
        failTask(match.id, full || 'errored')
      }
    }
  } catch {
    // network blip — try again next tick
  }
}

function hasRunning(): boolean {
  return getTasks().some((t) => t.status === 'running')
}

function start(): void {
  if (timer != null) return
  timer = window.setInterval(tick, POLL_MS)
  // one immediate tick so completion lands fast
  void tick()
}

function stop(): void {
  if (timer != null) window.clearInterval(timer)
  timer = null
}

/** Call this once at app startup. Listens to the task store and only polls
 *  while at least one task is running. */
export function initTaskPoller(): void {
  subscribe(() => {
    if (hasRunning()) start()
    else stop()
  })
}

/** Force a one-off poll from outside (e.g. Vapi 'speech-end' — Nova just
 *  finished saying the answer, the bridge has almost certainly flipped the
 *  task to done already, so an immediate tick closes the UI lag). */
export function pingTaskPoller(): void {
  void tick()
}
