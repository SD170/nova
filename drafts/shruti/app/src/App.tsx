import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Avatar3D, type Avatar3DHandle, type AvatarState } from './avatar/Avatar3D'
import { installTestKeys } from './avatar/testKeys'
import { bindVapi, createVoiceHooks } from './avatar/voiceBridge'
import { toggleDemo } from './tasks/demo'
import './tasks/tasks' // registers window.jarvisTasks
import { DevPanel, Hint } from './ui/Controls'
import { TaskPanel } from './ui/TaskPanel'
import { BootTitle } from './ui/BootTitle'
import { Hud } from './ui/Hud'
import { presence } from './avatar/presence'
import { installTaskChime, toggleMute, warmUpAudio } from './audio/chime'
import { PushToTalk, type SpeechHandler } from './voice/pushToTalk'

const params = new URLSearchParams(location.search)
// ?debug tints the face rig regions (red = jaw, green = mouth opening).
const AVATAR_DEBUG = params.has('debug')
// Dev builds (`npm run dev` or ?dev) answer with a sample clip when no backend is wired.
const SHOW_DEV = import.meta.env.DEV || params.has('dev')
const HINT_IDLE_MS = 4000
const IDLE_DISSOLVE_MS = 2 * 60 * 1000 // no interaction for 2 min → head dissolves
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
  const [state, setState] = useState<AvatarState>('idle')
  const [debugOpen, setDebugOpen] = useState(false) // press D
  const [hintVisible, setHintVisible] = useState(true)
  const [mode, setMode] = useState(presence.mode) // boot / awake / dissolving / dissolved / waking
  useEffect(() => presence.subscribe(setMode), [])

  // Dev fallback reply (no backend yet): think briefly, then speak the sample clip.
  const playSample = useCallback(() => {
    if (!devAudio.current) devAudio.current = new Audio(DEV_SAMPLE)
    const a = devAudio.current
    avatarRef.current?.connectAudio(a)
    a.currentTime = 0
    a.play().catch(() => {})
  }, [])

  useEffect(() => {
    // ── push-to-talk → states + speech event
    ptt.onStart = () => {
      devAudio.current?.pause() // barge-in
      avatarRef.current?.setState('listening')
    }
    ptt.onRelease = () => avatarRef.current?.setState('thinking')
    ptt.onEnd = (blob, ms) => {
      window.dispatchEvent(new CustomEvent('jarvis:user-speech-end', { detail: { blob, durationMs: ms } }))
      // TODO(backend): a handler registered via window.jarvisVoice.onUserSpeechEnd
      // should send `blob` to the orchestrator and connectAudio() the spoken reply.
      if (handlers.current.size) handlers.current.forEach((h) => h(blob, ms))
      else if (SHOW_DEV)
        setTimeout(async () => {
          if (avatarRef.current?.getState() !== 'thinking') return
          await avatarRef.current.endThinking() // symbols fully gone first…
          playSample() // …then the face starts talking
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
      setPointer: (x, y) => avatarRef.current?.setPointer(x, y),
    }
    window.jarvisAvatar = api
    // VAPI HOOK POINT: where the Vapi client is created, call window.jarvisVoice.bindVapi(vapi)
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
      if (e.code === 'KeyT' && !e.repeat && !e.metaKey && !e.ctrlKey) toggleDemo() // demo tasks (again = reset)
      if (e.code === 'KeyM' && !e.repeat && !e.metaKey && !e.ctrlKey) toggleMute() // task chime on/off
      if (e.code === 'KeyI' && !e.repeat && !e.metaKey && !e.ctrlKey) presence.dissolve() // demo the idle dissolve
      if (e.code !== 'Space') return
      e.preventDefault()
      if (e.repeat) return
      // SPACE during the boot skips it; while dissolved it only wakes NOVA
      if (presence.mode === 'boot') return presence.skipBoot()
      if (presence.mode === 'dissolving' || presence.mode === 'dissolved') return presence.wake()
      if (presence.busy) return // waking up — ignore until awake
      ptt.start()
    }
    const up = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      e.preventDefault()
      ptt.stop()
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    // head + eyes follow the cursor; recentre when it leaves the window
    const move = (e: MouseEvent) => {
      lastActivity = Date.now() // mouse movement keeps NOVA awake but never wakes it
      avatarRef.current?.setPointer((e.clientX / window.innerWidth) * 2 - 1, 1 - (e.clientY / window.innerHeight) * 2)
    }
    // idle dissolve: 2 min of no interaction while idle and nothing running
    let lastActivity = Date.now()
    const activity = () => (lastActivity = Date.now())
    const click = () => {
      activity()
      if (presence.mode === 'dissolving' || presence.mode === 'dissolved') presence.wake() // click wakes too
    }
    window.addEventListener('keydown', activity, true)
    window.addEventListener('mousedown', click, true)
    const idleTimer = setInterval(() => {
      const busy = avatarRef.current?.getState() !== 'idle' || window.jarvisTasks.getTasks().some((t) => t.status === 'running')
      if (busy) lastActivity = Date.now()
      else if (presence.mode === 'awake' && Date.now() - lastActivity > IDLE_DISSOLVE_MS) presence.dissolve()
    }, 1000)
    const leave = (e: MouseEvent) => !e.relatedTarget && avatarRef.current?.setPointer(null)
    window.addEventListener('mousemove', move)
    document.addEventListener('mouseout', leave)
    window.addEventListener('blur', () => avatarRef.current?.setPointer(null))
    const removeKeys = installTestKeys(() => avatarRef.current)
    const removeChime = installTaskChime()
    warmUpAudio() // during the black boot screen → no hitch on the first chime

    // mirror the avatar's state for the dev buttons
    const poll = setInterval(() => setState(avatarRef.current?.getState() ?? 'idle'), 150)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('mousemove', move)
      window.removeEventListener('keydown', activity, true)
      window.removeEventListener('mousedown', click, true)
      clearInterval(idleTimer)
      document.removeEventListener('mouseout', leave)
      removeKeys()
      removeChime()
      clearInterval(poll)
    }
  }, [ptt, playSample])

  const getMicLevel = useCallback(() => ptt.micLevel(), [ptt])

  // hint: shown when idle, fades out after a few seconds; hidden while talking
  useEffect(() => {
    if (state !== 'idle' || mode !== 'awake') {
      setHintVisible(false)
      return
    }
    setHintVisible(true)
    const id = setTimeout(() => setHintVisible(false), HINT_IDLE_MS)
    return () => clearTimeout(id)
  }, [state, mode])

  return (
    <div className="fixed inset-0 bg-black">
      <Avatar3D ref={avatarRef} debug={AVATAR_DEBUG} getMicLevel={getMicLevel} />
      <Hint visible={hintVisible} />
      <div className={`ui-layer ${mode === 'boot' ? 'ui-layer--hidden' : ''}`}>
        <Hud />
        <TaskPanel />
      </div>
      <BootTitle />
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
