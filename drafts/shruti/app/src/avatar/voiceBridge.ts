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
}

export function bindVapi(vapi: VapiLike, avatar: Avatar3DHandle) {
  const hooks = createVoiceHooks(avatar)
  const handlers: [string, (...a: any[]) => void][] = [
    ['speech-start', () => hooks.assistantSpeechStart()], // Vapi: assistant started talking
    ['speech-end', () => hooks.assistantSpeechEnd()],
    ['call-end', () => hooks.callEnd()],
    // assistant output volume 0..1 → lip-sync fallback when no audio stream is connected
    ['volume-level', (v: number) => avatar.setLevel(v)],
    [
      'message',
      (m: any) => {
        if (m?.type === 'speech-update' && m.role === 'user') {
          if (m.status === 'started') hooks.userSpeechStart()
          else if (m.status === 'stopped') hooks.userSpeechEnd()
        } else if (m?.type === 'transcript' && m.role === 'user' && m.transcriptType === 'partial') {
          hooks.userSpeechStart()
        } else if (m?.type === 'transcript' && m.role === 'user' && m.transcriptType === 'final') {
          hooks.userSpeechEnd()
        } else if (m?.type === 'tool-calls' || m?.type === 'function-call') {
          hooks.toolCallStart()
        } else if (m?.type === 'tool-calls-result' || m?.type === 'function-call-result') {
          hooks.toolCallEnd()
        }
      },
    ],
  ]
  for (const [e, fn] of handlers) vapi.on(e, fn)
  return () => {
    for (const [e, fn] of handlers) (vapi.removeListener ?? vapi.off)?.call(vapi, e, fn)
  }
}
