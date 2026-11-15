// ─────────────────────────────────────────────────────────────────────────────
// AvatarAudio — turns ANY audio your code is playing into mouth shapes.
//
// This does NOT generate voice. It only *listens* to audio you provide:
//
//   avatar.connectAudio(htmlAudioElement)  // <audio> / new Audio(url) — still plays out loud
//   avatar.connectAudio(mediaStream)       // e.g. Vapi / WebRTC remote stream (you play it)
//   avatar.connectAudio(audioNode)         // any Web Audio node in YOUR AudioContext
//   avatar.disconnectAudio()
//
// Every frame the avatar reads an AnalyserNode and derives:
//   jaw   0..1  overall loudness → how far the jaw opens
//   wide  0..1  share of high frequencies (s, ee, t sounds) → lips stretch
//   round 0..1  share of low frequencies (oo, oh, w sounds) → lips pucker
// Silence closes the mouth smoothly.
// ─────────────────────────────────────────────────────────────────────────────

export type AudioSourceLike = HTMLMediaElement | MediaStream | AudioNode

export interface MouthShape {
  /** jaw opening 0..1 (drives chin + lower cheeks too) */
  jaw: number
  /** viseme weights 0..1, blended smoothly */
  aa: number // open vowel
  ee: number // wide / stretched
  oo: number // rounded, pushed forward
  mm: number // lips pressed together (m, b, p)
  ff: number // lower lip tucked under the top teeth (f, v) / hiss (s)
  /** legacy names used by the shader */
  wide: number
  round: number
  /** raw 0..1 loudness, used for head "emphasis" nods */
  level: number
}

// An <audio> element can only be wrapped by createMediaElementSource ONCE per
// AudioContext, so cache the wrapper and reuse it on reconnect.
const elementSources = new WeakMap<HTMLMediaElement, MediaElementAudioSourceNode>()

export class AvatarAudio {
  private ownCtx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private source: AudioNode | null = null
  private keepAlive: HTMLAudioElement | null = null
  private freq: Uint8Array = new Uint8Array(0)
  private time: Uint8Array = new Uint8Array(0)
  private shape: MouthShape = { jaw: 0, aa: 0, ee: 0, oo: 0, mm: 0, ff: 0, wide: 0, round: 0, level: 0 }
  // first smoothing stage (second stage is `shape`) → eased S-curve, ~100 ms
  private stage1 = { jaw: 0, aa: 0, ee: 0, oo: 0, mm: 0, ff: 0 }
  // running averages of this voice's spectrum → shapes adapt to any speaker
  private avgFront = 0.4
  private avgOpen = 0.3
  private lastHeard = -Infinity
  private external = 0
  private externalAt = -Infinity

  get connected() {
    return !!this.source
  }

  /** True if real audio was audible in the last ~300ms. */
  isActive(now = performance.now()) {
    return now - this.lastHeard < 300
  }

  connect(src: AudioSourceLike) {
    this.disconnect()

    let ctx: BaseAudioContext
    let node: AudioNode

    if (src instanceof AudioNode) {
      // Caller's own graph: tap it with an analyser in the SAME context.
      // We don't touch their routing — they still connect it to the speakers.
      ctx = src.context
      node = src
    } else if (src instanceof MediaStream) {
      ctx = this.getCtx()
      // Chrome/Electron quirk: a remote WebRTC stream only delivers samples to
      // Web Audio if it's also attached to a media element. Muted = no double audio.
      this.keepAlive = new Audio()
      this.keepAlive.muted = true
      this.keepAlive.srcObject = src
      this.keepAlive.play().catch(() => {})
      node = (ctx as AudioContext).createMediaStreamSource(src)
    } else {
      ctx = this.getCtx()
      let el = elementSources.get(src)
      if (!el) {
        el = (ctx as AudioContext).createMediaElementSource(src)
        // createMediaElementSource re-routes the element into Web Audio, so we
        // must forward it to the speakers or it would go silent.
        el.connect(ctx.destination)
        elementSources.set(src, el)
      }
      node = el
    }

    const analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    analyser.smoothingTimeConstant = 0.35
    node.connect(analyser)

    this.analyser = analyser
    this.source = node
    this.freq = new Uint8Array(analyser.frequencyBinCount)
    this.time = new Uint8Array(analyser.fftSize)
    if (ctx instanceof AudioContext && ctx.state === 'suspended') ctx.resume().catch(() => {})
  }

  disconnect() {
    if (this.source && this.analyser) {
      try {
        this.source.disconnect(this.analyser)
      } catch {
        /* already disconnected */
      }
    }
    if (this.keepAlive) {
      this.keepAlive.srcObject = null
      this.keepAlive = null
    }
    this.source = null
    this.analyser = null
  }

  /** Fallback when no stream can be tapped: feed a 0..1 output volume
   *  (e.g. Vapi's `volume-level` event). Ignored while an analyser is connected. */
  setLevel(v: number) {
    this.external = Math.max(0, Math.min(1, v))
    this.externalAt = performance.now()
    if (this.external > 0.04) this.lastHeard = this.externalAt
  }

  /** Call once per frame. `dt` in seconds. Audio → viseme weights.
   *
   *  Bands (roughly speech formants):
   *    80–300 Hz   voicing        300–900 Hz  F1 → how OPEN the vowel is ("aa")
   *    900–2500 Hz F2 → front/back (high = "ee", low = "oo")
   *    2.5–4.5 kHz + 4.5–8 kHz  hiss / friction → "ss" / "ff"
   *  Silence after speech → "mm" (lips pressed) for a moment, then relaxed closed. */
  read(dt: number): MouthShape {
    const s = this.shape
    const t = { jaw: 0, aa: 0, ee: 0, oo: 0, mm: 0, ff: 0 }
    let level = 0
    const now = performance.now()

    const a = this.analyser
    if (!a && now - this.externalAt < 250 && this.external > 0.04) {
      // volume-only fallback (no spectrum): open vowel shaped by loudness
      level = this.external
      t.aa = Math.min(1, level * 1.4)
      t.jaw = Math.min(1, level * 1.3)
      t.ee = 0.25
    }
    if (a) {
      a.getByteTimeDomainData(this.time as any)
      a.getByteFrequencyData(this.freq as any)

      let sum = 0
      for (let i = 0; i < this.time.length; i++) {
        const v = (this.time[i] - 128) / 128
        sum += v * v
      }
      const rms = Math.sqrt(sum / this.time.length)
      level = Math.min(1, rms * 5)

      const hz = a.context.sampleRate / a.fftSize
      const band = (lo: number, hi: number) => {
        let acc = 0
        const i0 = Math.max(1, Math.floor(lo / hz))
        const i1 = Math.min(this.freq.length - 1, Math.ceil(hi / hz))
        for (let i = i0; i <= i1; i++) acc += this.freq[i]
        return acc / ((i1 - i0 + 1) * 255)
      }
      const voicing = band(80, 300)
      const f1 = band(300, 900)
      const f2 = band(900, 2500)
      const hiss = band(2500, 4500) * 0.5 + band(4500, 8000)
      const voiced = voicing + f1 + f2 + 1e-4

      const gate = 0.035 // ignore room noise
      if (rms > gate) {
        this.lastHeard = now
        const loud = Math.min(1, (rms - gate) * 6)
        const openFrac = f1 / voiced // more F1 → more open
        const front = f2 / (f1 + f2 + 1e-4) // more F2 → "ee", less → "oo"
        const hissFrac = hiss / (voiced + hiss)
        // compare against this speaker's own averages (~2 s), so a deep or bright
        // voice still produces both "ee" and "oo"
        const avgK = 1 - Math.exp(-dt / 2)
        this.avgFront += (front - this.avgFront) * avgK
        this.avgOpen += (openFrac - this.avgOpen) * avgK
        const frontRel = front - this.avgFront
        const openRel = openFrac - this.avgOpen
        const fric = smooth(0.28, 0.55, hissFrac)
        t.ff = fric * Math.min(1, loud * 2)
        t.aa = loud * smooth(-0.04, 0.08, openRel) * (1 - fric)
        t.ee = loud * smooth(0.0, 0.07, frontRel) * (1 - fric)
        t.oo = loud * smooth(0.0, 0.07, -frontRel) * (1 - fric)
        t.jaw = Math.min(1, loud * (0.45 + 1.4 * Math.max(0, openRel + 0.08)) * (1 - 0.65 * fric))
      } else if (now - this.lastHeard < 220) {
        t.mm = 1 // brief closure between syllables: m / b / p
      }
    }

    // Two-stage smoothing = eased S-curve (no jitter), ~80–120 ms to settle.
    const k = (tau: number) => 1 - Math.exp(-dt / tau)
    const s1 = this.stage1
    for (const key of ['jaw', 'aa', 'ee', 'oo', 'mm', 'ff'] as const) {
      const tau = key === 'jaw' && t.jaw > s1.jaw ? 0.026 : 0.034 // opening a touch quicker
      s1[key] += (t[key] - s1[key]) * k(tau)
      s[key] += (s1[key] - s[key]) * k(tau)
    }
    s.wide = s.ee
    s.round = s.oo
    s.level += (level - s.level) * k(level > s.level ? 0.03 : 0.15)
    return s
  }

  private getCtx(): AudioContext {
    if (!this.ownCtx) this.ownCtx = new AudioContext()
    return this.ownCtx
  }
}

function smooth(e0: number, e1: number, x: number) {
  const t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0)))
  return t * t * (3 - 2 * t)
}
