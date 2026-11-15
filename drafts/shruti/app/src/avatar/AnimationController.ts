// ─────────────────────────────────────────────────────────────────────────────
// AnimationController — blends the avatar's layers every frame.
//
//   final = base + Σ(expression × weight) + look + gesture      → head, color, fx
//   mouth (audio) is applied afterwards by the shader and is never read or
//   changed here, so no expression can fight lip sync.
//
// All weights use exponential smoothing (frame-rate independent) and are passed
// through smoothstep, so every transition eases in and out — nothing snaps.
// Every public method returns immediately; unknown names log a warning.
// ─────────────────────────────────────────────────────────────────────────────
import {
  BASE,
  BASE_STATES,
  EXPRESSIONS,
  GESTURES,
  LOOKS,
  NEUTRAL_EXPRESSION,
  type BaseParams,
  type BaseState,
  type ExpressionDef,
  type ExpressionName,
  type GestureName,
  type LookDef,
  type LookTarget,
  type RGB,
} from './expressions'
import { fbm } from './noise'

const BASE_FADE_S = 0.25
const EXPR_IN_S = 0.2
const EXPR_OUT_S = 0.3
const GREEN: RGB = [0.224, 1.0, 0.078]
const BLOOM_BASE = 1.25

// Signal waves (listening): 4 arcs per side pulse inside → out, then repeat.
// Pulses run on an accumulated phase, so louder mic = faster pulses (no jumps).
const SIG_PERIOD = 1.4 // s between pulses when quiet
const SIG_STAGGER = 0.16 // s between arcs within a pulse
const SIG_RISE = 0.1
const SIG_HOLD = 0.06
const SIG_FADE = 0.5
const SIG_EXPAND = 0.14 // model units an arc grows while it fades

/** τ so an exponential approach is ~95% done after `seconds`. */
const tau = (seconds: number) => seconds / 3
const approach = (cur: number, target: number, dt: number, seconds: number) =>
  cur + (target - cur) * (1 - Math.exp(-dt / tau(seconds)))
const ease = (w: number) => w * w * (3 - 2 * w)

interface Slot<D> {
  name: string
  def: D
  intensity: number
  w: number // raw smoothed weight 0..1
  target: 0 | 1
  endsAt: number | null // seconds; null = hold until cleared / listening
}

/** Everything the renderer needs this frame. Read-only for the renderer. */
export interface FrameValues {
  time: number
  // head (radians / model units) — applied to head + neck only
  yaw: number
  pitch: number
  roll: number
  lean: number
  breath: number
  // look + eyes
  eyeOpen: [number, number]
  eyeGlow: number
  eyeLook: [number, number]
  // subtle face motion
  emph: number // 0..1 cheek raise + nostril flare on emphasis
  brow: number // 0..1 eyebrow raise on louder moments
  // color + fx
  gridColor: RGB
  tintAmount: number
  brightness: number
  energy: number
  scanPhase: number
  glitch: number
  lipCorner: number
  bloom: number
  // particles
  particleRise: number // accumulated phase (direction-aware, never jumps)
  particleSpin: number // accumulated angle
  particleCount: number
  // thinking: question marks + grid shimmer
  thinking: number // 0..1 base-state weight (question marks spawn while > 0.5)
  // signal waves (listening)
  signalArcs: [number, number, number, number] // brightness per arc, inner → outer
  signalExpand: [number, number, number, number] // outward growth per arc
  signalMaster: number // 0..1 overall (sparkles, fade-in)
}

export interface AudioInput {
  level: number // 0..1 loudness from the mouth layer (read-only here)
  active: boolean // real audio audible right now
}

export class AnimationController {
  private state: BaseState = 'idle'
  private autoSpeaking = false
  private silentFor = 0
  private baseW: Record<BaseState, number> = { idle: 1, listening: 0, thinking: 0, speaking: 0 }
  private exprs: Slot<ExpressionDef>[] = []
  private looks: Slot<LookDef>[] = []
  private gestures: { name: GestureName; start: number }[] = []
  private now = 0

  // motion state
  private talk = 0
  private slowLevel = 0
  private nod = 0
  private nodVel = 0
  private lastEmphasis = 0
  private blink = 0
  private nextBlink = 2.5
  private blinkStart = -1
  private doubleBlink = false
  private emph = 0
  private brow = 0
  private saccade = { x: 0, y: 0, tx: 0, ty: 0, next: 0.6 }
  private scanPhase = 0
  private rise = 0
  private spin = 0
  private lean = 0
  private motionT = 0 // idle-motion clock; runs slower while thinking (no jumps)
  private sig = { active: false, phase: 0, stopPhase: null as number | null, master: 0, mic: 0 }

  readonly out: FrameValues = {
    time: 0, yaw: 0, pitch: 0, roll: 0, lean: 0, breath: 0,
    eyeOpen: [1, 1], eyeGlow: 1, eyeLook: [0, 0], emph: 0, brow: 0,
    gridColor: [...GREEN], tintAmount: 0, brightness: 1, energy: 0,
    scanPhase: 0, glitch: 0, lipCorner: 0, bloom: BLOOM_BASE,
    particleRise: 0, particleSpin: 0, particleCount: 1,
    thinking: 0,
    signalArcs: [0, 0, 0, 0], signalExpand: [0, 0, 0, 0], signalMaster: 0,
  }

  // ── public API ────────────────────────────────────────────────────────────

  getState() {
    return this.state
  }

  setState(state: BaseState, opts: { auto?: boolean } = {}) {
    if (!BASE_STATES.includes(state)) return warn(`setState: unknown state "${state}"`)
    this.autoSpeaking = !!opts.auto
    if (state === this.state) return
    // thinking → speaking: turn back to face the user before talking
    if (this.state === 'thinking' && state === 'speaking') this.lookAt({ target: 'user', duration_ms: 1600 })
    this.state = state
    // the user started talking → drop anything that was held "until cleared"
    if (state === 'listening') {
      for (const s of [...this.exprs, ...this.looks]) if (s.endsAt === null) s.target = 0
    }
  }

  setExpression({ name, duration_ms, intensity }: { name: string; duration_ms?: number | null; intensity?: number }) {
    const def = EXPRESSIONS[name as ExpressionName]
    if (!def) return warn(`setExpression: unknown expression "${name}"`)
    // last call wins: everything current fades out while the new one fades in
    for (const s of this.exprs) s.target = 0
    this.exprs.push(this.slot(name, def, duration_ms, intensity))
  }

  clearExpression() {
    for (const s of this.exprs) s.target = 0
  }

  lookAt({ target, duration_ms }: { target: string; duration_ms?: number | null }) {
    const def = LOOKS[target as LookTarget]
    if (!def) return warn(`lookAt: unknown target "${target}"`)
    for (const s of this.looks) s.target = 0
    this.looks.push(this.slot(target, def, duration_ms, 1))
  }

  clearLook() {
    for (const s of this.looks) s.target = 0
  }

  playGesture({ name }: { name: string }) {
    if (!GESTURES[name as GestureName]) return warn(`playGesture: unknown gesture "${name}"`)
    this.gestures.push({ name: name as GestureName, start: this.now })
  }

  // ── per frame ────────────────────────────────────────────────────────────

  update(dt: number, t: number, audio: AudioInput, micLevel = 0): FrameValues {
    this.now = t
    const o = this.out

    // automatic "speaking" while connected audio is audible (unless set otherwise)
    if (audio.active) {
      this.silentFor = 0
      // assistant audio playing → speaking (from idle, or when the reply arrives while thinking)
      if (this.state === 'idle' || this.state === 'thinking') this.setState('speaking', { auto: true })
    } else {
      this.silentFor += dt
      // 1.3 s bridges natural pauses between sentences without flickering to idle
      if (this.autoSpeaking && this.state === 'speaking' && this.silentFor > 1.3) this.setState('idle')
    }

    // ── LAYER 1: base — cross-fade weights, then weighted average of params
    let wSum = 0
    for (const s of BASE_STATES) {
      this.baseW[s] = approach(this.baseW[s], s === this.state ? 1 : 0, dt, BASE_FADE_S)
      wSum += this.baseW[s]
    }
    const base = {} as BaseParams
    for (const k of Object.keys(BASE.idle) as (keyof BaseParams)[]) {
      let v = 0
      for (const s of BASE_STATES) v += BASE[s][k] * this.baseW[s]
      base[k] = v / wSum
    }

    // ── LAYER 2: expressions (timed slots, cross-faded)
    const ex = this.blendExpressions(dt, t)

    // ── LAYER 2b: look direction
    let lookYaw = 0
    let lookPitch = 0
    let eyeX = 0
    let eyeY = 0
    let steady = 0
    for (const s of this.tick(this.looks, dt, t)) {
      const w = ease(s.w)
      lookYaw += s.def.yaw * w
      lookPitch += s.def.pitch * w
      eyeX += s.def.eyes[0] * w
      eyeY += s.def.eyes[1] * w
      steady = Math.max(steady, s.def.steady * w)
    }

    // ── gestures (one-shot, additive)
    let gPitch = 0
    let gYaw = 0
    let gRoll = 0
    this.gestures = this.gestures.filter((g) => {
      const def = GESTURES[g.name]
      const p = (t - g.start) / (def.duration / 1000)
      if (p >= 1) return false
      const v = def.amp * Math.sin(Math.PI * 2 * def.cycles * p) * Math.sin(Math.PI * p)
      if (def.axis === 'pitch') gPitch += v
      else if (def.axis === 'yaw') gYaw += v
      else gRoll += v
      return true
    })

    // ── idle motion: layered noise, livelier while talking, calmer when "looking at" someone
    this.talk = approach(this.talk, audio.level > 0.06 ? 1 : 0, dt, 1.2)
    const amp = base.swayAmp * (1 + this.talk * 0.9) * (1 - steady)
    this.motionT += dt * base.motionSpeed
    const m = this.motionT

    // emphasis nods: sudden loudness rise kicks a damped spring (speaking base layer)
    this.slowLevel = approach(this.slowLevel, audio.level, dt, 1)
    if (base.emphasisNods > 0.3 && audio.level - this.slowLevel > 0.16 && t - this.lastEmphasis > 0.45) {
      this.nodVel += (0.55 + Math.random() * 0.35) * base.emphasisNods
      this.emph = 1 // cheeks lift, nostrils flare
      this.lastEmphasis = t
    }
    this.nodVel += (-60 * this.nod - 9 * this.nodVel) * dt
    this.nod += this.nodVel * dt

    const bob = ex.bob * Math.abs(Math.sin(t * Math.PI * 4.2))
    const glitchJitter = ex.glitch > 0.01 ? (fbm(t * 9) * 0.05 + (Math.random() - 0.5) * 0.02) * ex.glitch : 0

    // final = base + expression·weight + look (+ gesture)
    o.yaw = fbm(m * 0.11) * 0.11 * amp + fbm(m * 0.6 + 40) * 0.025 * this.talk + base.yaw + ex.yaw + lookYaw + gYaw + glitchJitter
    o.pitch =
      fbm(m * 0.09 + 10) * 0.05 * amp + Math.sin(m * 1.4) * 0.004 - this.nod * 0.12 +
      base.pitch + ex.pitch - bob + lookPitch + gPitch
    o.roll = fbm(m * 0.07 + 20) * 0.04 * amp + base.roll + ex.roll + gRoll
    this.lean = approach(this.lean, base.lean, dt, 0.6)
    o.lean = this.lean
    o.breath = Math.sin((t / 4.6) * Math.PI * 2) * 0.05

    // emphasis decays softly; brows follow loud moments
    this.emph *= Math.exp(-dt / 0.35)
    o.emph = this.emph * this.emph * (3 - 2 * this.emph)
    this.brow = approach(this.brow, Math.min(1, Math.max(0, audio.level - 0.42) * 2.4), dt, 0.25)
    o.brow = this.brow

    // ── blinks (random, sometimes double) × expression eye opening
    if (t > this.nextBlink && this.blinkStart < 0) this.blinkStart = t
    if (this.blinkStart >= 0) {
      const p = (t - this.blinkStart) / 0.16
      this.blink = p < 0.45 ? p / 0.45 : Math.max(0, 1 - (p - 0.45) / 0.55)
      if (p >= 1) {
        this.blink = 0
        this.blinkStart = -1
        this.doubleBlink = !this.doubleBlink && Math.random() < 0.2
        this.nextBlink = t + (this.doubleBlink ? 0.12 : 3 + Math.random() * 3) // every 3–6 s
      }
    }
    o.eyeOpen[0] = ex.eyeScale[0] * (1 - this.blink)
    o.eyeOpen[1] = ex.eyeScale[1] * (1 - this.blink)
    o.eyeGlow = ex.eyeGlow * (1 + ex.energy * 0.5)
    // micro-saccades: tiny quick eye jumps every ~0.4–1.4 s
    const sc = this.saccade
    if (t > sc.next) {
      sc.tx = (Math.random() - 0.5) * 0.24
      sc.ty = (Math.random() - 0.5) * 0.16
      sc.next = t + 0.4 + Math.random() * 1.0
    }
    sc.x = approach(sc.x, sc.tx, dt, 0.06)
    sc.y = approach(sc.y, sc.ty, dt, 0.06)
    // eyes ride with the head, except while speaking: then they stay on the camera
    const onCam = this.baseW.speaking
    o.eyeLook[0] = eyeX + base.eyeX + o.yaw * 1.2 * (1 - onCam) - o.yaw * 1.0 * onCam + sc.x
    o.eyeLook[1] = eyeY + base.eyeY - o.pitch * 1.2 * (1 - onCam) + o.pitch * 1.0 * onCam + sc.y

    // ── color + fx
    o.gridColor = ex.tint
    o.tintAmount = ex.tintAmount
    o.brightness = ex.brightness
    o.energy = Math.min(1.5, ex.energy + (this.state === 'listening' ? micLevel : 0))
    o.glitch = ex.glitch
    o.lipCorner = ex.lipCorner
    o.bloom = BLOOM_BASE * ex.bloom
    // phases accumulate so speed/direction changes never make things jump
    this.scanPhase += dt * 1.43 * base.scanSpeed * ex.scanSpeed
    o.scanPhase = this.scanPhase
    this.rise += dt * base.particleSpeed * ex.particleSpeed * ex.particleDir
    o.particleRise = this.rise
    this.spin += dt * (base.particleSpin + ex.particleSpin)
    o.particleSpin = this.spin
    o.particleCount = ex.particleCount
    this.updateSignal(dt, micLevel)

    o.thinking = this.baseW.thinking

    o.time = t
    return o
  }

  /** Listening → signal waves, driven by the mic. Leaving listening lets the
   *  current pulse finish travelling outward, then it fades. */
  private updateSignal(dt: number, mic: number) {
    const s = this.sig
    const stagger = SIG_STAGGER / SIG_PERIOD // in pulse units
    if (this.state === 'listening') {
      if (!s.active) {
        s.active = true
        s.phase = 0
      }
      s.stopPhase = null
    } else if (s.active && s.stopPhase === null) {
      s.stopPhase = s.phase
    }
    s.mic = approach(s.mic, this.state === 'listening' ? mic : 0, dt, 0.15)
    s.phase += (dt / SIG_PERIOD) * (1 + 1.8 * s.mic) // louder → faster pulses

    const pulseLen = (SIG_RISE + SIG_HOLD + SIG_FADE) / SIG_PERIOD
    const lastPulse = s.stopPhase === null ? Infinity : Math.floor(s.stopPhase)
    const gain = Math.min(1.6, 0.95 + 1.0 * s.mic) // louder → brighter
    for (let i = 0; i < 4; i++) {
      const local = s.phase - i * stagger
      let b = 0
      let e = 0
      if (s.active && local >= 0) {
        const cycle = Math.floor(local)
        const u = local - cycle
        if (cycle <= lastPulse && u < pulseLen) {
          const sec = u * SIG_PERIOD
          b = sec < SIG_RISE ? ease(sec / SIG_RISE) : sec < SIG_RISE + SIG_HOLD ? 1 : ease(1 - (sec - SIG_RISE - SIG_HOLD) / SIG_FADE)
          e = (u / pulseLen) * SIG_EXPAND * (1 + s.mic)
        }
      }
      this.out.signalArcs[i] = b * gain
      this.out.signalExpand[i] = e
    }
    if (s.stopPhase !== null && s.phase > lastPulse + 1 + 3 * stagger) s.active = false
    s.master = approach(s.master, s.active ? 1 : 0, dt, s.active ? 0.3 : 0.5)
    this.out.signalMaster = s.master
  }

  // ── internals ────────────────────────────────────────────────────────────

  private slot<D>(name: string, def: D & { duration: number }, duration_ms: number | null | undefined, intensity?: number): Slot<D> {
    const dur = duration_ms === undefined ? def.duration : duration_ms
    const i = intensity ?? (def as unknown as ExpressionDef).intensity ?? 1
    return {
      name,
      def,
      intensity: Math.max(0, Math.min(1, i)),
      w: 0,
      target: 1,
      endsAt: dur === null ? null : this.now + Math.max(0, dur) / 1000,
    }
  }

  /** Advance timers + weights; drop slots that have fully faded out. */
  private tick<D>(slots: Slot<D>[], dt: number, t: number): Slot<D>[] {
    for (const s of slots) {
      if (s.endsAt !== null && t >= s.endsAt) s.target = 0
      s.w = approach(s.w, s.target, dt, s.target ? EXPR_IN_S : EXPR_OUT_S)
    }
    const alive = slots.filter((s) => s.target === 1 || s.w > 0.002)
    slots.length = 0
    slots.push(...alive)
    return slots
  }

  private blendExpressions(dt: number, t: number) {
    const N = NEUTRAL_EXPRESSION
    const r = {
      tint: [...GREEN] as RGB,
      tintAmount: 0,
      brightness: 1,
      eyeScale: [1, 1] as [number, number],
      eyeGlow: 1,
      pitch: 0,
      roll: 0,
      yaw: 0,
      bob: 0,
      particleSpeed: 1,
      particleCount: 1,
      particleDir: 1,
      particleSpin: 0,
      scanSpeed: 1,
      bloom: 1,
      lipCorner: 0,
      glitch: 0,
      energy: 0,
    }
    const tintAcc = [0, 0, 0]
    let tintW = 0
    for (const s of this.tick(this.exprs, dt, t)) {
      const k = ease(s.w) * s.intensity
      const d = s.def
      const add = (key: keyof typeof N & keyof typeof r, value: number | undefined) => {
        if (value === undefined) return
        ;(r[key] as number) += (value - (N[key] as number)) * k
      }
      add('brightness', d.brightness)
      add('eyeGlow', d.eyeGlow)
      add('pitch', d.pitch)
      add('roll', d.roll)
      add('yaw', d.yaw)
      add('bob', d.bob)
      add('particleSpeed', d.particleSpeed)
      add('particleCount', d.particleCount)
      add('particleDir', d.particleDir)
      add('particleSpin', d.particleSpin)
      add('scanSpeed', d.scanSpeed)
      add('bloom', d.bloom)
      add('lipCorner', d.lipCorner)
      add('glitch', d.glitch)
      add('energy', d.energy)
      if (d.eyeScale) {
        r.eyeScale[0] += (d.eyeScale[0] - 1) * k
        r.eyeScale[1] += (d.eyeScale[1] - 1) * k
      }
      if (d.tint && d.tintAmount) {
        const a = d.tintAmount * k
        tintAcc[0] += d.tint[0] * a
        tintAcc[1] += d.tint[1] * a
        tintAcc[2] += d.tint[2] * a
        tintW += a
      }
    }
    if (tintW > 0) {
      const amt = Math.min(1, tintW)
      // grid color moves from neon green toward the (weighted) expression tint
      for (let i = 0; i < 3; i++) r.tint[i] = GREEN[i] + (tintAcc[i] / tintW - GREEN[i]) * amt
      r.tintAmount = amt
    }
    r.eyeScale[0] = Math.max(0, r.eyeScale[0])
    r.eyeScale[1] = Math.max(0, r.eyeScale[1])
    r.particleCount = Math.max(0, Math.min(1, r.particleCount))
    r.brightness = Math.max(0.2, r.brightness)
    return r
  }
}

function warn(msg: string) {
  console.warn(`[avatar] ${msg} — ignored`)
}
