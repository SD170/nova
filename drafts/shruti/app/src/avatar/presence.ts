// ─────────────────────────────────────────────────────────────────────────────
// presence.ts — timed "scene" sequences, in one place:
//
//   boot      launch: black → scanline draws the grid face bottom→top → eyes ignite
//             → "NOVA" types in, holds, fades → liquid background fades in → idle
//   dissolve  idle 2 min (or press I): grid breaks into drifting particles
//   wake      SPACE / click while dissolved: particles rush back, then the SAME
//             scanline redraw as boot (short), eyes ignite → idle
//
// Avatar3D reads `presence.frame` every frame (uniforms); React UI subscribes for
// mode changes (NOVA text, HUD fade). Everything is a pure function of time.
// ─────────────────────────────────────────────────────────────────────────────

export type PresenceMode = 'boot' | 'awake' | 'dissolving' | 'dissolved' | 'waking'

// world (model) y range the scanline sweeps: bottom of the shoulders → above the head
const Y_BOTTOM = -4.1
const Y_TOP = 4.6

// boot timeline (seconds)
const BOOT = {
  scanStart: 0.25,
  scanEnd: 1.95,
  ignite: 1.95, // eyes flash on
  textStart: 2.15, // "NOVA" types in
  textEnd: 3.75, // starts fading out
  bgStart: 2.6,
  bgEnd: 3.7,
  done: 4.0,
}
// wake timeline: particles rush back, then short redraw
const WAKE = { rushEnd: 0.8, scanEnd: 1.8, ignite: 1.8, done: 2.15 }
const DISSOLVE_TIME = 2.0

export interface PresenceFrame {
  revealOn: number // 1 = scanline drawing in progress (hide above it)
  revealY: number // model-space y of the scanline
  eyeIgnite: number // 0 off … 1 normal (briefly >1 = flash)
  bgFade: number // liquid background + ambient particles
  dissolve: number // 0 solid head … 1 fully dissolved into particles
  spread: number // particle drift distance 0..1 (+ gentle floating)
  particleAlpha: number
  hud: number // HUD / status overlay opacity
}

const ease = (x: number) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x))
const span = (t: number, a: number, b: number) => ease((t - a) / (b - a))

class Presence {
  mode: PresenceMode = 'boot'
  private t = 0 // time in current mode
  private wakeFrom = 1 // particle spread when the wake started
  private listeners = new Set<(m: PresenceMode) => void>()
  readonly frame: PresenceFrame = { revealOn: 1, revealY: Y_BOTTOM, eyeIgnite: 0, bgFade: 0, dissolve: 0, spread: 0, particleAlpha: 0, hud: 0 }

  /** Seconds since the current mode started (for the NOVA text). */
  get time() {
    return this.t
  }
  get bootText() {
    return BOOT
  }
  /** True while SPACE should NOT start push-to-talk. */
  get busy() {
    return this.mode !== 'awake'
  }

  subscribe(fn: (m: PresenceMode) => void): () => void {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }
  private set(mode: PresenceMode) {
    this.mode = mode
    this.t = 0
    this.listeners.forEach((l) => l(mode))
  }

  /** Skip the boot (SPACE during boot). */
  skipBoot() {
    if (this.mode === 'boot') this.set('awake')
  }
  dissolve() {
    if (this.mode === 'awake') this.set('dissolving')
  }
  /** SPACE / click while dissolved (or dissolving) → reassemble. */
  wake() {
    if (this.mode === 'dissolved' || this.mode === 'dissolving') {
      this.wakeFrom = Math.max(0.3, this.frame.spread)
      this.set('waking')
    }
  }

  update(dt: number): PresenceFrame {
    this.t += dt
    const t = this.t
    const f = this.frame
    switch (this.mode) {
      case 'boot': {
        const s = span(t, BOOT.scanStart, BOOT.scanEnd)
        f.revealOn = 1
        f.revealY = Y_BOTTOM + (Y_TOP - Y_BOTTOM) * s
        f.eyeIgnite = igniteCurve(t - BOOT.ignite)
        f.bgFade = span(t, BOOT.bgStart, BOOT.bgEnd)
        f.hud = f.bgFade
        f.dissolve = 0
        f.particleAlpha = 0
        f.spread = 0
        if (t >= BOOT.done) this.set('awake')
        break
      }
      case 'awake':
        f.revealOn = 0
        f.eyeIgnite = 1
        f.bgFade = 1
        f.hud = 1
        f.dissolve = 0
        f.particleAlpha = 0
        f.spread = 0
        break
      case 'dissolving': {
        const p = t / DISSOLVE_TIME
        f.revealOn = 0
        f.dissolve = ease(p)
        f.particleAlpha = ease(Math.min(1, p * 2.5))
        f.spread = ease(p) // drifting outward…
        f.eyeIgnite = 1 - ease(p * 1.5)
        f.hud = 1
        if (t >= DISSOLVE_TIME) this.set('dissolved')
        break
      }
      case 'dissolved':
        f.dissolve = 1
        f.particleAlpha = 1
        f.spread = 1 + Math.min(0.25, t * 0.01) // …then just float gently
        f.eyeIgnite = 0
        break
      case 'waking': {
        if (t < WAKE.rushEnd) {
          // particles rush back to their places on the head
          const p = t / WAKE.rushEnd
          f.spread = this.wakeFrom * (1 - p * p) // accelerate inward
          f.particleAlpha = 1
          f.dissolve = 1
          f.revealOn = 1
          f.revealY = Y_BOTTOM
        } else {
          // same scanline redraw as boot, short; particles give way to the grid
          const s = span(t, WAKE.rushEnd, WAKE.scanEnd)
          f.spread = 0
          f.dissolve = 0
          f.revealOn = 1
          f.revealY = Y_BOTTOM + (Y_TOP - Y_BOTTOM) * s
          f.particleAlpha = 1 - s
        }
        f.eyeIgnite = igniteCurve(t - WAKE.ignite)
        if (t >= WAKE.done) this.set('awake')
        break
      }
    }
    return f
  }
}

/** Eyes: off → soft flash (1.9) → settle at 1. */
function igniteCurve(dt: number) {
  if (dt <= 0) return 0
  if (dt < 0.12) return (dt / 0.12) * 1.9
  return 1 + 0.9 * Math.exp(-(dt - 0.12) / 0.18)
}

export const presence = new Presence()
export const PRESENCE_Y = { bottom: Y_BOTTOM, top: Y_TOP }
