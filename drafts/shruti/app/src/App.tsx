import { Component, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Avatar3D, type Avatar3DHandle, type AvatarState } from './avatar/Avatar3D'
import { installTestKeys } from './avatar/testKeys'
import { bindVapi, createVoiceHooks } from './avatar/voiceBridge'
import { toggleDemo } from './tasks/demo'
import './tasks/tasks' // registers window.jarvisTasks
import { initTaskPoller } from './tasks/poller'
import { DevPanel, Hint, ListeningBadge } from './ui/Controls'
import { TaskPanel } from './ui/TaskPanel'
import { ActivityChip } from './ui/ActivityChip'
import { BootTitle } from './ui/BootTitle'
import { Hud } from './ui/Hud'
// Nova Desk (side panel): only loads when VITE_NOVA_BASE is set, lazily, inside an error guard, so a
// problem in the desk can never take down the avatar app.
const NovaDesk = lazy(() => import('./nova/NovaDesk').then((m) => ({ default: m.NovaDesk })))
class DeskGuard extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch(err: unknown) {
    console.warn('[nova-desk] disabled:', err)
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}
import { presence } from './avatar/presence'
import { installTaskChime, toggleMute, warmUpAudio } from './audio/chime'
import { PushToTalk, type SpeechHandler } from './voice/pushToTalk'
import { initVapi, getVapi } from './voice/vapiClient'

const params = new URLSearchParams(location.search)
// ?debug tints the face rig regions (red = jaw, green = mouth opening).
const AVATAR_DEBUG = params.has('debug')
// Dev builds (`npm run dev` or ?dev) answer with a sample clip when no backend is wired.
const SHOW_DEV = import.meta.env.DEV || params.has('dev')
const HINT_IDLE_MS = 4000
const IDLE_DISSOLVE_MS = 10 * 60 * 1000 // no interaction for 10 min → head dissolves
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
  const [mode, setMode] = useState(presence.mode) // boot / awake / dissolving / dissolved / waking
  useEffect(() => presence.subscribe(setMode), [])
  const [listening, setListening] = useState(false)

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
    // Only flip into 'thinking' when there IS a pending task. Otherwise stay
    // 'idle' — a thinking animation with no task on the queue is confusing.
    ptt.onRelease = () => {
      const pending = window.jarvisTasks?.getTasks().some((t) => t.status === 'running' || t.status === 'queued')
      avatarRef.current?.setState(pending ? 'thinking' : 'idle')
    }
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
      setPointer: (x, y) => avatarRef.current?.setPointer(x, y),
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

    // Poll the bridge for background Hermes task completions. No-op when idle.
    initTaskPoller()

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
      if (vapiReady.current) {
        const v = getVapi()
        // SPACE is also the panic-interrupt key: if Nova is mid-sentence,
        // cut her off instantly (control-channel 'mute-assistant') before
        // unmuting the mic so the user can talk.
        v?.interrupt()
        v?.setMuted(false)
        // avatar state is driven by Vapi's own speech-update events via voiceBridge
      } else {
        ptt.start()
      }
      setListening(true)
    }
    const up = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      e.preventDefault()
      if (vapiReady.current) getVapi()?.setMuted(true)
      else ptt.stop()
      setListening(false)
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
        <ActivityChip />
        <TaskPanel />
        {import.meta.env.VITE_NOVA_BASE ? (
          <DeskGuard>
            <Suspense fallback={null}>
              <NovaDesk />
            </Suspense>
          </DeskGuard>
        ) : null}
      </div>
      <BootTitle />
      <ListeningBadge visible={listening} />
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
