import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Avatar3D, type Avatar3DHandle, type AvatarState } from './avatar/Avatar3D'
import { installTestKeys } from './avatar/testKeys'
import { bindVapi, createVoiceHooks } from './avatar/voiceBridge'
import { DevPanel, Hint } from './ui/Controls'
import { PushToTalk, type SpeechHandler } from './voice/pushToTalk'
import { initVapi, getVapi } from './voice/vapiClient'

const params = new URLSearchParams(location.search)
// ?debug tints the face rig regions (red = jaw, green = mouth opening).
const AVATAR_DEBUG = params.has('debug')
// Dev builds (`npm run dev` or ?dev) answer with a sample clip when no backend is wired.
const SHOW_DEV = import.meta.env.DEV || params.has('dev')
const HINT_IDLE_MS = 4000
const DEV_SAMPLE = `${import.meta.env.BASE_URL}dev/sample-voice.m4a`

declare global {
  interface Window {
    /** The avatar API for teammates' code — see src/avatar/Avatar3D.tsx. */
    jarvisAvatar: Avatar3DHandle
    jarvisVoice: {
      /** Vapi → avatar state wiring (see voiceBridge.ts). */
      bindVapi: (vapi: Parameters<typeof bindVapi>[0]) => () => void
      hooks: ReturnType<typeof createVoiceHooks>
      /** Called with the recorded audio every time the student releases push-to-talk. */
      onUserSpeechEnd: (handler: SpeechHandler) => () => void
    }
  }
}

export default function App() {
  const avatarRef = useRef<Avatar3DHandle>(null)
  const ptt = useMemo(() => new PushToTalk(), [])
  const handlers = useRef(new Set<SpeechHandler>())
  const devAudio = useRef<HTMLAudioElement | null>(null)
  const vapiReady = useRef(false)
  const [state, setState] = useState<AvatarState>('idle')
  const [debugOpen, setDebugOpen] = useState(false) // press D
  const [hintVisible, setHintVisible] = useState(true)

  // Dev fallback reply (no backend yet): think briefly, then speak the sample clip.
  const playSample = useCallback(() => {
    if (!devAudio.current) devAudio.current = new Audio(DEV_SAMPLE)
    const a = devAudio.current
    avatarRef.current?.connectAudio(a)
    a.currentTime = 0
    a.play().catch(() => {})
  }, [])

  useEffect(() => {
    // Push-to-talk callbacks remain wired for environments WITHOUT Vapi
    // (dev builds, teammates who haven't pulled the key). When Vapi is live
    // the SPACE key toggles vapi.setMuted and PTT is not driving the mic.
    ptt.onStart = () => {
      devAudio.current?.pause() // barge-in
      avatarRef.current?.setState('listening')
    }
    ptt.onRelease = () => avatarRef.current?.setState('thinking')
    ptt.onEnd = (blob, ms) => {
      window.dispatchEvent(new CustomEvent('jarvis:user-speech-end', { detail: { blob, durationMs: ms } }))
      if (handlers.current.size) handlers.current.forEach((h) => h(blob, ms))
      else if (SHOW_DEV)
        setTimeout(async () => {
          if (avatarRef.current?.getState() !== 'thinking') return
          await avatarRef.current.endThinking()
          playSample()
        }, 2500)
      else setTimeout(() => avatarRef.current?.getState() === 'thinking' && avatarRef.current?.setState('idle'), 8000)
    }
    ptt.onError = (err) => {
      console.warn('[push-to-talk] mic unavailable', err)
      avatarRef.current?.setState('idle')
    }

    // ── public API for teammates
    const api: Avatar3DHandle = {
      getState: () => avatarRef.current?.getState() ?? 'idle',
      connectAudio: (s) => avatarRef.current?.connectAudio(s),
      disconnectAudio: () => avatarRef.current?.disconnectAudio(),
      setLevel: (v) => avatarRef.current?.setLevel(v),
      setState: (s) => avatarRef.current?.setState(s),
      setExpression: (o) => avatarRef.current?.setExpression(o),
      clearExpression: () => avatarRef.current?.clearExpression(),
      lookAt: (o) => avatarRef.current?.lookAt(o),
      playGesture: (o) => avatarRef.current?.playGesture(o),
      endThinking: () => avatarRef.current?.endThinking() ?? Promise.resolve(),
    }
    window.jarvisAvatar = api
    // VAPI: try to spin up the client. If creds are set, this call goes to Nova
    // and bindVapi() wires call-events to the avatar automatically. If not
    // configured, we fall back to the local push-to-talk + sample-voice path.
    const handle = initVapi(api)
    vapiReady.current = !!handle
    if (handle) {
      // Fire-and-forget: start the call. User doesn't see anything until they
      // press SPACE (which unmutes).
      handle.setMuted(true)
      handle.start().catch((e) => console.error('[vapi] start error', e))
    }

    window.jarvisVoice = {
      bindVapi: (vapi) => bindVapi(vapi, api),
      hooks: createVoiceHooks(api),
      onUserSpeechEnd: (h) => {
        handlers.current.add(h)
        return () => handlers.current.delete(h)
      },
    }

    // ── hold SPACE to talk (the only way to talk); D toggles the hidden debug panel
    const down = (e: KeyboardEvent) => {
      if (e.code === 'KeyD' && !e.repeat && !e.metaKey && !e.ctrlKey) setDebugOpen((v) => !v)
      if (e.code !== 'Space') return
      e.preventDefault()
      if (e.repeat) return
      if (vapiReady.current) {
        getVapi()?.setMuted(false)
        // avatar state is driven by Vapi's own speech-update events via voiceBridge
      } else {
        ptt.start()
      }
    }
    const up = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      e.preventDefault()
      if (vapiReady.current) getVapi()?.setMuted(true)
      else ptt.stop()
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    const removeKeys = installTestKeys(() => avatarRef.current)

    // mirror the avatar's state for the dev buttons
    const poll = setInterval(() => setState(avatarRef.current?.getState() ?? 'idle'), 150)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      removeKeys()
      clearInterval(poll)
    }
  }, [ptt, playSample])

  const getMicLevel = useCallback(() => ptt.micLevel(), [ptt])

  // hint: shown when idle, fades out after a few seconds; hidden while talking
  useEffect(() => {
    if (state !== 'idle') {
      setHintVisible(false)
      return
    }
    setHintVisible(true)
    const id = setTimeout(() => setHintVisible(false), HINT_IDLE_MS)
    return () => clearTimeout(id)
  }, [state])

  return (
    <div className="fixed inset-0 bg-black">
      <Avatar3D ref={avatarRef} debug={AVATAR_DEBUG} getMicLevel={getMicLevel} />
      <Hint visible={hintVisible} />
      {debugOpen && (
        <DevPanel
          state={state}
          onState={(s) => {
            devAudio.current?.pause()
            avatarRef.current?.setState(s)
          }}
          onSpeakSample={playSample}
        />
      )}
    </div>
  )
}
