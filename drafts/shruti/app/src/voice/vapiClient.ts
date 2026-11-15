// Vapi Web SDK bootstrap for the avatar.
// Spins up a Vapi client, binds its events to the avatar state (via voiceBridge),
// and exposes start/stop/toggleMute so push-to-talk in App.tsx controls the mic.
//
// Env (Vite):
//   VITE_VAPI_PUBLIC_KEY       — required
//   VITE_VAPI_ASSISTANT_ID     — required (Nova)
//   VITE_VAPI_SHRUTI_ASSISTANT_ID — optional, if we want in-app persona switch later
//
// If VITE_VAPI_PUBLIC_KEY is missing, we no-op silently so dev builds still show
// the sample-voice fallback in App.tsx.

import Vapi from '@vapi-ai/web'
import type { Avatar3DHandle } from '../avatar/Avatar3D'
import { bindVapi } from '../avatar/voiceBridge'

export type VapiHandle = {
  vapi: Vapi
  start: () => Promise<void>
  stop: () => void
  setMuted: (m: boolean) => void
  interrupt: () => void
  isActive: () => boolean
  unbind: () => void
}

let current: VapiHandle | null = null

export function getVapi(): VapiHandle | null {
  return current
}

export function initVapi(avatar: Avatar3DHandle): VapiHandle | null {
  // dedupe
  if (current) return current

  const pub = import.meta.env.VITE_VAPI_PUBLIC_KEY as string | undefined
  const assistantId = import.meta.env.VITE_VAPI_ASSISTANT_ID as string | undefined

  if (!pub || !assistantId) {
    console.warn('[vapi] VITE_VAPI_PUBLIC_KEY / VITE_VAPI_ASSISTANT_ID missing — SDK not started')
    return null
  }

  const vapi = new Vapi(pub)
  const unbind = bindVapi(vapi as unknown as Parameters<typeof bindVapi>[0], avatar)

  let active = false
  let userStopped = false   // true after explicit stop(); blocks auto-restart
  // Desired mic state. PTT is the only way to listen, so we default to muted
  // and ONLY flip to false while SPACE is held. Vapi's web SDK doesn't
  // persist setMuted() calls made before the call actually opens, and every
  // reconnect fires a fresh 'call-start' with the mic OPEN by default —
  // both footguns are fixed by re-applying `desiredMuted` on every
  // 'call-start' and inside setMuted() itself.
  let desiredMuted = true

  vapi.on('call-start', () => {
    active = true
    userStopped = false
    console.info('[vapi] call started')
    // Re-assert mute immediately so the mic can't be live before the user
    // first presses SPACE. Without this the SDK boots with mic=open.
    try { vapi.setMuted(desiredMuted) } catch { /* ignore */ }
  })
  // Vapi's 'message' event does NOT carry call.id (it's the server-sent payload
  // only — transcript, speech-update, tool-calls, etc.). The call id lives on
  // the Call object returned from vapi.start(), and we rescue a backup copy
  // from any 'call-start-success' event emitted by SDK 3.x.
  vapi.on('call-start-success', (e: any) => {
    const cid = e?.callId ?? e?.call?.id
    if (typeof cid === 'string' && cid) {
      (window as any).__NOVA_CALL_ID__ = cid
      console.info('[vapi] call id captured via call-start-success:', cid)
    }
  })
  // Last-resort backstop: some SDK message types DO include call.id (e.g.
  // status-update frames). Keep stashing the latest if present.
  vapi.on('message', (m: any) => {
    const cid = m?.call?.id ?? m?.callId
    if (typeof cid === 'string' && cid) (window as any).__NOVA_CALL_ID__ = cid
  })
  vapi.on('call-end', () => {
    active = false
    console.info('[vapi] call ended')
    // Auto-reconnect: if the call ended but the user didn't ask to stop,
    // bring it back up so the mic stays live. Small delay to avoid thrashing
    // if Vapi is in a bad state.
    if (!userStopped) {
      setTimeout(() => {
        if (!active && !userStopped) {
          console.info('[vapi] auto-reconnect after call-end')
          vapi.start(assistantId).then((call) => {
            const cid = (call as any)?.id
            if (typeof cid === 'string' && cid) {
              (window as any).__NOVA_CALL_ID__ = cid
              console.info('[vapi] call id captured via auto-reconnect:', cid)
            }
          }).catch((e) =>
            console.error('[vapi] auto-reconnect failed', e),
          )
        }
      }, 800)
    }
  })
  vapi.on('error', (e: unknown) => {
    console.error('[vapi] error', e)
  })

  current = {
    vapi,
    async start() {
      if (active) return
      userStopped = false
      try {
        const call = await vapi.start(assistantId)
        const cid = (call as any)?.id
        if (typeof cid === 'string' && cid) {
          (window as any).__NOVA_CALL_ID__ = cid
          console.info('[vapi] call id captured via start() return:', cid)
        }
      } catch (e) {
        console.error('[vapi] start failed', e)
      }
    },
    stop() {
      userStopped = true
      try {
        vapi.stop()
      } catch {
        /* ignore */
      }
      active = false
    },
    setMuted(m: boolean) {
      desiredMuted = m
      try {
        vapi.setMuted(m)
        // Defense-in-depth: Vapi.setMuted(true) is supposed to stop sending
        // audio but we've seen the server-side STT finalize partials AFTER
        // release and treat them as live user speech. Triple-stamp the mute
        // by firing it again on microtask + next frame so any racing
        // re-arm in the SDK lands in the muted state.
        if (m) {
          Promise.resolve().then(() => { try { vapi.setMuted(true) } catch { /* ignore */ } })
          setTimeout(() => { try { vapi.setMuted(true) } catch { /* ignore */ } }, 50)
        }
        // If Vapi dropped the call (e.g. silence timeout) and user hits
        // SPACE to unmute, restart the call so PTT works again.
        if (!m && !active) {
          console.info('[vapi] unmute requested but call inactive — restarting')
          userStopped = false
          vapi.start(assistantId).catch((e) =>
            console.error('[vapi] auto-restart failed', e),
          )
        }
      } catch (e) {
        console.warn('[vapi] setMuted failed', e)
      }
    },
    interrupt() {
      // Instant barge-in from the client. Uses Vapi's control-channel
      // 'mute-assistant' — stops in-flight TTS immediately. We don't
      // leave the assistant muted (that'd silence subsequent replies);
      // a short unmute follows so the next utterance plays normally.
      try {
        ;(vapi as any).send({ type: 'control', control: 'mute-assistant' })
        setTimeout(() => {
          try {
            ;(vapi as any).send({ type: 'control', control: 'unmute-assistant' })
          } catch {/* ignore */}
        }, 120)
      } catch (e) {
        console.warn('[vapi] interrupt failed', e)
      }
    },
    isActive: () => active,
    unbind,
  }
  return current
}
