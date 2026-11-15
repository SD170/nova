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

  vapi.on('call-start', () => {
    active = true
    console.info('[vapi] call started')
  })
  vapi.on('call-end', () => {
    active = false
    console.info('[vapi] call ended')
  })
  vapi.on('error', (e: unknown) => {
    console.error('[vapi] error', e)
  })

  current = {
    vapi,
    async start() {
      if (active) return
      try {
        await vapi.start(assistantId)
      } catch (e) {
        console.error('[vapi] start failed', e)
      }
    },
    stop() {
      try {
        vapi.stop()
      } catch {
        /* ignore */
      }
      active = false
    },
    setMuted(m: boolean) {
      try {
        vapi.setMuted(m)
        // If Vapi dropped the call (e.g. silence timeout) and user hits
        // SPACE to unmute, restart the call so PTT works again.
        if (!m && !active) {
          console.info('[vapi] unmute requested but call inactive — restarting')
          vapi.start(assistantId).catch((e) =>
            console.error('[vapi] auto-restart failed', e),
          )
        }
      } catch (e) {
        console.warn('[vapi] setMuted failed', e)
      }
    },
    isActive: () => active,
    unbind,
  }
  return current
}
