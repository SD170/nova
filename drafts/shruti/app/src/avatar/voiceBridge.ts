// ─────────────────────────────────────────────────────────────────────────────
// voiceBridge — drives the avatar's BASE state from voice events.
//
//   user speech starts            → listening
//   user stops / tool call / LLM  → thinking
//   assistant audio playing       → speaking
//   otherwise                     → idle
//
// Two ways to use it:
//
// 1) Vapi web SDK (@vapi-ai/web, same events as apps/voice/static/index.html):
//      import { bindVapi } from './avatar/voiceBridge'
//      const unbind = bindVapi(vapi, window.jarvisAvatar)
//
// 2) Any other voice stack — call the hooks yourself:
//      const v = createVoiceHooks(window.jarvisAvatar)
//      v.userSpeechStart(); v.userSpeechEnd(); v.toolCallStart(); v.toolCallEnd()
//      v.assistantSpeechStart(); v.assistantSpeechEnd(); v.callEnd()
//
// ORCHESTRATOR HOOK POINT: tool calls can also drive expressions/looks directly,
// e.g. a "show_emotion" tool → window.jarvisAvatar.setExpression({ name: 'smile' }),
// or "point_at_card" → window.jarvisAvatar.lookAt({ target: 'shelf' }).
//
// NOTE: written against @vapi-ai/web 2.3.x event names; not yet run against a live
// Vapi call from this app.
// ─────────────────────────────────────────────────────────────────────────────
import type { Avatar3DHandle } from './Avatar3D'
import {
  addTask,
  completeTask,
  failTask,
  getTasks,
  type TaskType,
} from '../tasks/tasks'
import { pingTaskPoller } from '../tasks/poller'

// Bridge URL for /user_speech pings. Same base Vite env as the poller.
const BRIDGE_URL =
  (import.meta.env.VITE_BRIDGE_URL as string | undefined) ??
  'http://127.0.0.1:8000'

// Light fire-and-forget beacon. Server uses it to decide when it's safe to
// inject Nova's reply (waits for the user to be silent ≥600ms).
function pingUserSpeech(active: boolean): void {
  const cid = (window as Window & { __NOVA_CALL_ID__?: string }).__NOVA_CALL_ID__
  if (!cid) return
  // Use fetch keepalive so pings during unload still land.
  try {
    void fetch(`${BRIDGE_URL}/user_speech`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ call_id: cid, active }),
      keepalive: true,
    })
  } catch {
    // network blip — next event will try again
  }
}

export function createVoiceHooks(avatar: Pick<Avatar3DHandle, 'setState'>) {
  let userTalking = false
  let assistantTalking = false
  let toolsPending = 0
  let waitingForReply = false

  // single place that decides the base state from the flags (priority order)
  const resolve = () => {
    if (userTalking) avatar.setState('listening') // barge-in wins
    else if (assistantTalking) avatar.setState('speaking')
    else if (toolsPending > 0 || waitingForReply) avatar.setState('thinking')
    else avatar.setState('idle')
  }

  return {
    userSpeechStart() {
      userTalking = true
      resolve()
    },
    /** user finished a turn → the LLM is working until the assistant speaks */
    userSpeechEnd() {
      userTalking = false
      waitingForReply = true
      resolve()
    },
    toolCallStart() {
      toolsPending++
      resolve()
    },
    toolCallEnd() {
      toolsPending = Math.max(0, toolsPending - 1)
      resolve()
    },
    assistantSpeechStart() {
      assistantTalking = true
      waitingForReply = false
      resolve()
    },
    assistantSpeechEnd() {
      assistantTalking = false
      resolve()
    },
    callEnd() {
      userTalking = assistantTalking = waitingForReply = false
      toolsPending = 0
      resolve()
    },
  }
}

/** Minimal shape of the Vapi web client we use. */
interface VapiLike {
  on(event: string, fn: (...args: any[]) => void): void
  removeListener?(event: string, fn: (...args: any[]) => void): void
  off?(event: string, fn: (...args: any[]) => void): void
  isMuted?(): boolean
}

export function bindVapi(vapi: VapiLike, avatar: Avatar3DHandle) {
  const hooks = createVoiceHooks(avatar)
  // Vapi tool-call id → our task-store id. Lets us complete the right row when
  // the async brain finishes (bridge sends 'Started task tNNN:' on dispatch).
  const toolCallToTaskId: Record<string, string> = {}

  // Classify question → task type for the UI pill icon. Cheap heuristics.
  const classify = (q: string): TaskType => {
    const s = q.toLowerCase()
    if (/\b(email|inbox|mail|gmail|reply|draft)\b/.test(s)) return 'email'
    if (/\b(calendar|schedule|event|free|study block|meeting)\b/.test(s)) return 'calendar'
    if (/\b(canvas|assignment|hw|homework|exam|quiz|due|grade|course|class|syllab)\b/.test(s)) return 'canvas'
    if (/\b(news|research|company|about [A-Z]|headline)\b/.test(s)) return 'web'
    return 'other'
  }

  // Show the full question in the task card. CSS truncates visually if needed,
  // but the raw text stays in the DOM for expanded view + screen readers.
  const titleOf = (q: string) => q

  const handlers: [string, (...a: any[]) => void][] = [
    ['speech-start', () => hooks.assistantSpeechStart()], // Vapi: assistant started talking
    ['speech-end', () => {
      hooks.assistantSpeechEnd()
      // Nova just finished speaking. If that utterance was 'the answer', the
      // bridge already marked the matching task 'done'. Nudge the poller so
      // the UI card flips to Done within ~80ms instead of waiting for the
      // next scheduled tick (would be up to 400ms lag).
      pingTaskPoller()
    }],
    ['call-end', () => hooks.callEnd()],
    // assistant output volume 0..1 → lip-sync fallback when no audio stream is connected
    ['volume-level', (v: number) => avatar.setLevel(v)],
    [
      'message',
      (m: any) => {
        // Gate user-speech signals on the mic state. Vapi's web SDK keeps
        // emitting partial transcripts + speech-update frames even while the
        // local audio track is muted (Daily VAD stays attached to the
        // suspended track), so the avatar flickers into 'listening' between
        // SPACE presses. We only trust user-speech events when the mic is
        // actually open.
        const micOpen = vapi.isMuted ? vapi.isMuted() === false : true
        if (m?.type === 'speech-update' && m.role === 'user') {
          if (!micOpen) return
          if (m.status === 'started') { hooks.userSpeechStart(); pingUserSpeech(true) }
          else if (m.status === 'stopped') { hooks.userSpeechEnd(); pingUserSpeech(false) }
        } else if (m?.type === 'transcript' && m.role === 'user' && m.transcriptType === 'partial') {
          if (!micOpen) return
          hooks.userSpeechStart()
          pingUserSpeech(true)
        } else if (m?.type === 'transcript' && m.role === 'user' && m.transcriptType === 'final') {
          if (!micOpen) return
          hooks.userSpeechEnd()
          pingUserSpeech(false)
        } else if (m?.type === 'tool-calls' || m?.type === 'function-call') {
          hooks.toolCallStart()
          // Vapi emits an array of tool-calls on 'tool-calls', or one on 'function-call'.
          const calls = m.toolCalls ?? m.toolCallList ?? (m.functionCall ? [m.functionCall] : [])
          for (const c of calls) {
            const name = c.function?.name ?? c.name
            if (name !== 'ask_brain') continue
            const argsRaw = c.function?.arguments ?? c.arguments ?? {}
            const args = typeof argsRaw === 'string' ? safeJson(argsRaw) : argsRaw
            const q = (args?.question ?? '').toString()
            if (!q) continue
            const toolCallId = c.id ?? c.toolCallId ?? ''
            const taskId = addTask({
              type: classify(q),
              title: titleOf(q),
              status: 'running',
            })
            if (toolCallId) toolCallToTaskId[toolCallId] = taskId
          }
        } else if (m?.type === 'tool-calls-result' || m?.type === 'function-call-result') {
          hooks.toolCallEnd()
          // Match the result envelope back to our task row, extract either the
          // brain's final text or the registry status, and update the UI card.
          const resultCalls = m.toolCallList ?? m.toolCalls ?? m.toolCallResults ??
            (m.functionCallResult ? [m.functionCallResult] : [])
          for (const r of resultCalls) {
            const toolCallId = r.toolCallId ?? r.id ?? ''
            const text: string = (r.result ?? r.message ?? '').toString()
            let taskId = toolCallToTaskId[toolCallId]

            // '<ACK#tNNN>' — just-dispatched internal ack. Row already
            // added above on tool-calls; nothing to do. Keep the map entry.
            if (/^<ACK#t\d+>/i.test(text)) continue

            // 'That '<q>' just finished: <reply>' — check_task delivers the done result
            const doneMatch = text.match(/just finished:\s*(.+)$/i)
            if (doneMatch) {
              // find by title substring if we don't have the id mapped
              if (!taskId) {
                const titleMatch = text.match(/That '([^']+)' just finished/)
                const title = titleMatch?.[1] ?? ''
                const hit = getTasks().slice().reverse().find(
                  (t) => t.status === 'running' && t.title.startsWith(title),
                )
                if (hit) taskId = hit.id
              }
              if (taskId) completeTask(taskId, { summary: doneMatch[1] })
              continue
            }

            // 'Still on '<q>' — Ns in.' — running update
            if (/^Still on /.test(text)) {
              // nothing to change; UI already shows 'running'
              continue
            }

            // 'No active tasks.' — nothing to do
            if (/^No active tasks/i.test(text)) continue

            // Hard failure
            if (/snag|error|couldn't reach|failed/i.test(text) && taskId) {
              failTask(taskId, text)
            }
          }
        }
      },
    ],
  ]
  for (const [e, fn] of handlers) vapi.on(e, fn)
  return () => {
    for (const [e, fn] of handlers) (vapi.removeListener ?? vapi.off)?.call(vapi, e, fn)
  }
}

function safeJson(s: string): any {
  try { return JSON.parse(s) } catch { return null }
}
