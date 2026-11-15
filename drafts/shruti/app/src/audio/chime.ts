// The ONLY sound in the app: a soft chime when a task finishes (status → done).
// Generated with the Web Audio API — no audio files. Press M to mute/unmute
// (remembered between launches).
import { getTasks, subscribe } from '../tasks/tasks'

let ctx: AudioContext | null = null
let muted = (() => {
  try {
    return localStorage.getItem('nova.muted') === '1'
  } catch {
    return false
  }
})()

export function isMuted() {
  return muted
}

export function toggleMute() {
  muted = !muted
  try {
    localStorage.setItem('nova.muted', muted ? '1' : '0')
  } catch {
    /* storage unavailable — fine, just not remembered */
  }
  return muted
}

/** Gentle two-note chime (C6 → E6), soft attack, long smooth decay, a hint of echo. */
export function playChime() {
  if (muted) return
  ctx ??= new AudioContext()
  if (ctx.state === 'suspended') ctx.resume().catch(() => {})
  const now = ctx.currentTime

  const out = ctx.createGain()
  out.gain.value = 0.07 // quiet
  const lp = ctx.createBiquadFilter()
  lp.type = 'lowpass'
  lp.frequency.value = 3200
  // tiny echo for a glassy, airy tail
  const delay = ctx.createDelay()
  delay.delayTime.value = 0.13
  const fb = ctx.createGain()
  fb.gain.value = 0.22
  const wet = ctx.createGain()
  wet.gain.value = 0.25
  lp.connect(out)
  lp.connect(delay)
  delay.connect(fb)
  fb.connect(delay)
  delay.connect(wet)
  wet.connect(out)
  out.connect(ctx.destination)

  const note = (freq: number, at: number, level: number) => {
    for (const [mult, gain] of [
      [1, level],
      [2, level * 0.18], // soft octave shimmer
    ] as const) {
      const o = ctx!.createOscillator()
      o.type = 'sine'
      o.frequency.value = freq * mult
      const g = ctx!.createGain()
      g.gain.setValueAtTime(0, now + at)
      g.gain.linearRampToValueAtTime(gain, now + at + 0.012)
      g.gain.exponentialRampToValueAtTime(0.0001, now + at + 1.5)
      o.connect(g)
      g.connect(lp)
      o.start(now + at)
      o.stop(now + at + 1.6)
    }
  }
  note(1046.5, 0, 0.9) // C6
  note(1318.5, 0.09, 0.75) // E6

  // tidy up the graph after the tail has faded
  setTimeout(() => out.disconnect(), 2600)
}

/** Create the audio engine up front (during the black boot screen) and run one
 *  silent note through it, so the first real chime doesn't cause a frame hitch. */
export function warmUpAudio() {
  try {
    ctx ??= new AudioContext()
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    g.gain.value = 0 // silent
    o.connect(g)
    g.connect(ctx.destination)
    o.start()
    o.stop(ctx.currentTime + 0.05)
  } catch {
    /* audio unavailable — chimes just won't play */
  }
}

/** Watch the task list and chime once whenever task(s) become done. */
export function installTaskChime() {
  const prev = new Map(getTasks().map((t) => [t.id, t.status]))
  let pending = 0
  return subscribe(() => {
    let finished = false
    for (const t of getTasks()) {
      if (t.status === 'done' && prev.get(t.id) !== 'done') finished = true
      prev.set(t.id, t.status)
    }
    if (finished && !pending) {
      // several finishing in the same moment → one chime
      pending = window.setTimeout(() => {
        pending = 0
        playChime()
      }, 60)
    }
  })
}
