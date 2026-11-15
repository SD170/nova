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

const POLL_MS = 1500
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
      }>
    }

    const uiTasks = getTasks()
    for (const srv of data.tasks ?? []) {
      if (srv.status !== 'done' && srv.status !== 'error') continue
      // Match to a still-running UI row by question/title prefix.
      const match = uiTasks
        .slice()
        .reverse()
        .find(
          (t) =>
            t.status === 'running' &&
            srv.question &&
            t.title &&
            (srv.question.startsWith(t.title.replace(/…$/, '')) ||
              t.title.startsWith(srv.question.slice(0, 32))),
        )
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
