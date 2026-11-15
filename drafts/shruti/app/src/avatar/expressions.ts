// ─────────────────────────────────────────────────────────────────────────────
// Animation data. Everything the layers blend is defined here as plain objects,
// so tuning a look is a data change, not a code change.
//
//   LAYER 1  BASE        idle | listening | thinking | speaking   (always one active)
//   LAYER 2  EXPRESSION  smile, laugh, angry, …                    (optional, timed)
//   LAYER 2b LOOK        left | right | up | down | user | shelf   (optional, timed)
//   GESTURE              nod | shake | tilt                        (one-shot, additive)
//   LAYER 3  MOUTH       audio-driven, applied last (see AvatarAudio.ts) — nothing
//                        here can touch the jaw.
// Angles are radians. Positive pitch = head tips forward/down, positive yaw = head
// turns to the viewer's right, positive roll = tilts toward the viewer's left.
// ─────────────────────────────────────────────────────────────────────────────

export type BaseState = 'idle' | 'listening' | 'thinking' | 'speaking'
export const BASE_STATES: BaseState[] = ['idle', 'listening', 'thinking', 'speaking']

export type ExpressionName =
  | 'smile'
  | 'laugh'
  | 'angry'
  | 'sad'
  | 'surprised'
  | 'confused'
  | 'excited'
  | 'wink'
  | 'glitch'
  | 'power_up'

export type LookTarget = 'left' | 'right' | 'up' | 'down' | 'user' | 'shelf'
export type GestureName = 'nod' | 'shake' | 'tilt'

export type RGB = [number, number, number]

/** Base-state parameters. Cross-faded by weight (~250 ms). */
export interface BaseParams {
  swayAmp: number // multiplier on the idle noise sway
  motionSpeed: number // how fast the idle motion plays (thinking slows down)
  pitch: number
  yaw: number
  roll: number
  lean: number // head forward (model units)
  particleSpeed: number // multiplier
  particleSpin: number // rad/s
  scanSpeed: number // multiplier
  eyeX: number // gaze offset -1..1 (x+ = viewer's right)
  eyeY: number // gaze offset -1..1 (y+ = up)
  emphasisNods: number // 0..1 → nods on loudness peaks
}

const NEUTRAL_BASE: BaseParams = {
  swayAmp: 1,
  motionSpeed: 1,
  pitch: 0,
  yaw: 0,
  roll: 0,
  lean: 0,
  particleSpeed: 1,
  particleSpin: 0.04,
  scanSpeed: 1,
  eyeX: 0,
  eyeY: 0,
  emphasisNods: 0,
}

export const BASE: Record<BaseState, BaseParams> = {
  idle: { ...NEUTRAL_BASE },
  listening: { ...NEUTRAL_BASE, swayAmp: 0.55, pitch: 0.06, roll: 0.05, lean: 0.35 },
  // thinking: pondering — head tilts to one side and up, eyes glance up and away,
  // everything slows down
  thinking: { ...NEUTRAL_BASE, swayAmp: 0.55, motionSpeed: 0.4, pitch: -0.1, yaw: 0.12, roll: 0.1, particleSpeed: 0.35, particleSpin: 0.01, eyeX: 0.6, eyeY: 0.8 },
  speaking: { ...NEUTRAL_BASE, swayAmp: 1.4, emphasisNods: 1 },
}

/** Expression targets. Every field is optional; missing = neutral (no change). */
export interface ExpressionDef {
  duration: number // default ms
  intensity: number // default 0..1
  tint?: RGB // neon grid color this expression shifts toward
  tintAmount?: number // 0..1 how far toward `tint`
  brightness?: number // grid brightness multiplier
  eyeScale?: [number, number] // eye opening L/R (1 = normal, 0 = closed, 1.3 = wide)
  eyeGlow?: number // eye glow multiplier
  pitch?: number // added to head pitch
  roll?: number // added to head roll (tilt)
  yaw?: number
  bob?: number // rhythmic head bounce amplitude (laugh)
  particleSpeed?: number // multiplier
  particleCount?: number // 0..1 fraction of particles visible
  particleDir?: 1 | -1 // +1 rise, -1 fall
  particleSpin?: number // extra rad/s
  scanSpeed?: number // multiplier
  bloom?: number // multiplier on bloom intensity
  lipCorner?: number // -1..1 additive mouth-corner lift (smile/laugh/angry only)
  glitch?: number // 0..1 slice jitter + chroma flicker
  energy?: number // 0..1 extra grid/eye power
}

export const NEUTRAL_EXPRESSION: Required<Omit<ExpressionDef, 'duration' | 'intensity' | 'tint'>> & { tint: RGB } = {
  tint: [0.224, 1.0, 0.078],
  tintAmount: 0,
  brightness: 1,
  eyeScale: [1, 1],
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

const GOLD: RGB = [1.0, 0.78, 0.18]

export const EXPRESSIONS: Record<ExpressionName, ExpressionDef> = {
  smile: {
    duration: 3000, intensity: 0.85,
    tint: GOLD, tintAmount: 0.55, brightness: 1.1,
    eyeScale: [0.82, 0.82], eyeGlow: 1.25, roll: 0.05, pitch: -0.02,
    particleSpeed: 1.3, bloom: 1.15, lipCorner: 0.7,
  },
  laugh: {
    duration: 2500, intensity: 1,
    tint: [1.0, 0.68, 0.12], tintAmount: 0.7, brightness: 1.25,
    eyeScale: [0.55, 0.55], eyeGlow: 1.4, pitch: -0.1, bob: 0.035,
    particleSpeed: 2.2, particleSpin: 0.35, scanSpeed: 1.6, bloom: 1.35, lipCorner: 1,
  },
  angry: {
    duration: 3000, intensity: 0.9,
    tint: [1.0, 0.22, 0.05], tintAmount: 0.8, brightness: 1.15,
    eyeScale: [0.6, 0.6], eyeGlow: 1.6, pitch: 0.08,
    particleSpeed: 2.6, particleDir: -1, scanSpeed: 2.6, bloom: 1.3, lipCorner: -0.6,
  },
  sad: {
    duration: 4000, intensity: 0.85,
    tint: [0.36, 0.34, 0.95], tintAmount: 0.75, brightness: 0.62,
    eyeScale: [0.72, 0.72], eyeGlow: 0.55, pitch: 0.14, roll: -0.06,
    particleSpeed: 0.35, particleCount: 0.45, particleDir: -1, scanSpeed: 0.45, bloom: 0.75,
  },
  surprised: {
    duration: 2000, intensity: 1,
    tint: [0.55, 1.0, 1.0], tintAmount: 0.5, brightness: 1.25,
    eyeScale: [1.35, 1.35], eyeGlow: 1.7, pitch: -0.1,
    particleSpeed: 1.8, particleSpin: 0.25, scanSpeed: 2, bloom: 1.3,
  },
  confused: {
    duration: 3000, intensity: 0.85,
    tint: [0.85, 0.4, 1.0], tintAmount: 0.55,
    eyeScale: [1.15, 0.78], eyeGlow: 1.1, roll: 0.16, yaw: -0.06,
    particleSpeed: 0.8, particleSpin: -0.2, scanSpeed: 0.7,
  },
  excited: {
    duration: 2500, intensity: 1,
    tint: [0.75, 1.0, 0.2], tintAmount: 0.45, brightness: 1.35,
    eyeScale: [1.2, 1.2], eyeGlow: 1.6, pitch: -0.06, bob: 0.02,
    particleSpeed: 2.6, particleSpin: 0.5, scanSpeed: 2.2, bloom: 1.45, energy: 0.4,
  },
  wink: {
    duration: 2000, intensity: 1,
    tint: [1.0, 0.55, 0.85], tintAmount: 0.35,
    eyeScale: [1, 0.05], eyeGlow: 1.2, roll: 0.07, lipCorner: 0,
    bloom: 1.05,
  },
  glitch: {
    duration: 2000, intensity: 1,
    tint: [0.4, 0.95, 1.0], tintAmount: 0.4,
    eyeGlow: 1.3, particleSpeed: 1.6, scanSpeed: 3.5, bloom: 1.2, glitch: 1,
  },
  power_up: {
    duration: 3500, intensity: 1,
    tint: [0.8, 1.0, 0.95], tintAmount: 0.5, brightness: 1.4,
    eyeScale: [1.15, 1.15], eyeGlow: 2.2, pitch: -0.05,
    particleSpeed: 3.2, particleSpin: 0.9, scanSpeed: 3, bloom: 1.6, energy: 0.8,
  },
}

/** Look targets: head yaw/pitch offsets + where the eye glow points. */
export interface LookDef {
  duration: number // default ms
  yaw: number
  pitch: number
  eyes: [number, number] // -1..1 x/y (x+ = viewer's right, y+ = up)
  steady: number // 0..1 how much it calms the idle sway (look *at* someone)
}

export const LOOKS: Record<LookTarget, LookDef> = {
  left: { duration: 1600, yaw: -0.38, pitch: 0, eyes: [-0.7, 0], steady: 0.3 },
  right: { duration: 1600, yaw: 0.38, pitch: 0, eyes: [0.7, 0], steady: 0.3 },
  up: { duration: 1600, yaw: 0, pitch: -0.22, eyes: [0, 0.7], steady: 0.3 },
  down: { duration: 1600, yaw: 0, pitch: 0.24, eyes: [0, -0.7], steady: 0.3 },
  user: { duration: 2500, yaw: 0, pitch: 0, eyes: [0, 0], steady: 0.75 },
  // "shelf": the empty space above the head, reserved for future hologram cards
  shelf: { duration: 2000, yaw: 0.05, pitch: -0.3, eyes: [0.1, 1], steady: 0.5 },
}

/** One-shot gestures. Offsets follow an envelope over `duration` (ms). */
export const GESTURES: Record<GestureName, { duration: number; axis: 'pitch' | 'yaw' | 'roll'; amp: number; cycles: number }> = {
  nod: { duration: 900, axis: 'pitch', amp: 0.13, cycles: 2 },
  shake: { duration: 1000, axis: 'yaw', amp: 0.17, cycles: 2.5 },
  tilt: { duration: 1200, axis: 'roll', amp: 0.15, cycles: 0.5 },
}
