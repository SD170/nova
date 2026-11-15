// ─────────────────────────────────────────────────────────────────────────────
// Thinking symbols: question marks "?", exclamation marks "!" and light bulbs,
// all drawn as glowing wireframes (grid lines along + around each surface).
//
// • Spread across the WHOLE screen — left, right, top corners, upper area — at
//   different depths: closer = bigger/brighter, farther = smaller/dimmer.
// • Never over the face: every spawn is projected to screen space and rejected
//   if it (or where it will drift to) overlaps the head or shoulders.
// • 16 slots with staggered lifetimes → ~10-16 visible at once; each drifts up
//   slowly, rotates gently, fades in and out.
// • Light bulbs occasionally "flicker on" — a quick spark then a soft glow pulse.
// • When thinking ends, everything fades out completely in ≤ 0.6 s.
// ─────────────────────────────────────────────────────────────────────────────
import * as THREE from 'three'

const COLORS = [
  new THREE.Color(0.224, 1.0, 0.078), // #39FF14 neon green
  new THREE.Color(0.486, 0.227, 0.929), // #7C3AED purple
  new THREE.Color(0.655, 0.545, 0.98), // #A78BFA violet
  new THREE.Color(0.231, 0.51, 0.965), // #3B82F6 electric blue
]
const COUNT = 16
const FADE_IN = 1.2
const FADE_OUT_END = 0.6 // when thinking ends: everything gone within this
const Z_NEAR = 2.4 // depth range (model units; the face is at z ≈ 2.2)
const Z_FAR = -7

type Kind = 'question' | 'exclaim' | 'bulb'

// ── geometry (shared by all symbols) ─────────────────────────────────────────

function buildGeometry() {
  // "?" — hook tube + dot
  const q: THREE.Vector3[] = []
  for (let i = 0; i <= 14; i++) {
    const a = THREE.MathUtils.degToRad(165 - (i / 14) * 215)
    q.push(new THREE.Vector3(Math.cos(a) * 0.4, 0.52 + Math.sin(a) * 0.4, 0))
  }
  q.push(new THREE.Vector3(0.05, 0.08, 0), new THREE.Vector3(0, -0.06, 0), new THREE.Vector3(0, -0.2, 0))
  const qTube = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(q), 72, 0.075, 8, false)
  const dot = new THREE.SphereGeometry(0.095, 12, 8)
  dot.translate(0, -0.47, 0)

  // "!" — tapered stem (wide at the top) + dot
  const stem = new THREE.CylinderGeometry(0.12, 0.065, 0.86, 10, 10, false)
  stem.translate(0, 0.36, 0)

  // light bulb — lathe profile: glass dome, neck, ridged screw base, tip
  const pts: THREE.Vector2[] = [new THREE.Vector2(0.0001, -0.64), new THREE.Vector2(0.09, -0.62), new THREE.Vector2(0.15, -0.56)]
  for (let i = 0, y = -0.52; y <= -0.2; i++, y += 0.055) pts.push(new THREE.Vector2(i % 2 ? 0.185 : 0.215, y))
  pts.push(new THREE.Vector2(0.2, -0.17), new THREE.Vector2(0.26, -0.06))
  for (let i = 0; i <= 16; i++) {
    const a = THREE.MathUtils.degToRad(-40 + (i / 16) * 130) // -40° → 90° (top)
    pts.push(new THREE.Vector2(Math.max(0.0001, Math.cos(a) * 0.42), 0.32 + Math.sin(a) * 0.42))
  }
  const bulb = new THREE.LatheGeometry(pts, 22)
  const core = new THREE.SphereGeometry(0.16, 14, 10)
  core.translate(0, 0.3, 0)

  return { qTube, dot, stem, bulb, core }
}

// ── materials ─────────────────────────────────────────────────────────────────

const WIRE_VERT = /* glsl */ `
  varying vec2 vUv;
  varying vec3 vN;
  varying vec3 vV;
  void main() {
    vUv = uv;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vN = normalize(normalMatrix * normal);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`

const WIRE_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uAlpha, uGlow;
  uniform vec2 uLines; // grid density: around / along
  varying vec2 vUv;
  varying vec3 vN;
  varying vec3 vV;
  float line(float v) {
    float d = abs(fract(v - 0.5) - 0.5) / max(fwidth(v), 1e-4);
    return 1.0 - clamp(d - 0.2, 0.0, 1.0);
  }
  void main() {
    float wire = max(line(vUv.x * uLines.x), line(vUv.y * uLines.y));
    float fres = pow(1.0 - clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0), 2.0);
    vec3 col = uColor * (wire * 1.35 + fres * 0.75 + 0.07);
    // idea spark: lines brighten toward white, the glass fills with light
    col += (mix(uColor, vec3(1.0, 0.97, 0.85), 0.55) * (wire * 1.2 + 0.35 + fres * 0.6)) * uGlow;
    gl_FragColor = vec4(col * uAlpha, 1.0);
  }
`

const CORE_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uAlpha, uGlow;
  varying vec3 vN;
  varying vec3 vV;
  void main() {
    float facing = clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0);
    vec3 warm = mix(uColor, vec3(1.0, 0.95, 0.8), 0.6);
    gl_FragColor = vec4(warm * pow(facing, 1.5) * (0.12 + uGlow * 2.4) * uAlpha, 1.0);
  }
`

function material(shared: Record<string, THREE.IUniform>, lines: [number, number], frag = WIRE_FRAG) {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: { ...shared, uLines: { value: new THREE.Vector2(...lines) } },
    vertexShader: WIRE_VERT,
    fragmentShader: frag,
  })
}

// ── symbols ───────────────────────────────────────────────────────────────────

interface Sym {
  kind: Kind
  group: THREE.Group
  u: { uColor: THREE.IUniform<THREE.Color>; uAlpha: THREE.IUniform<number>; uGlow: THREE.IUniform<number> }
  age: number
  life: number
  alpha: number
  depthDim: number
  rise: number
  driftX: number
  spin: number
  wobble: number
  nextSpark: number
  sparkT: number
  ndc: THREE.Vector2 // where it was placed on screen (for spacing)
}

export function createThinkingSymbols() {
  const root = new THREE.Group()
  const g = buildGeometry()
  const syms: Sym[] = []

  for (let i = 0; i < COUNT; i++) {
    const kind: Kind = i % 5 === 0 || i % 5 === 3 ? 'bulb' : i % 5 === 1 ? 'exclaim' : 'question'
    const u = {
      uColor: { value: COLORS[i % COLORS.length].clone() },
      uAlpha: { value: 0 },
      uGlow: { value: 0 },
    }
    const group = new THREE.Group()
    if (kind === 'question') group.add(new THREE.Mesh(g.qTube, material(u, [26, 6])), new THREE.Mesh(g.dot, material(u, [12, 6])))
    else if (kind === 'exclaim') group.add(new THREE.Mesh(g.stem, material(u, [8, 9])), new THREE.Mesh(g.dot, material(u, [12, 6])))
    else group.add(new THREE.Mesh(g.bulb, material(u, [14, 26])), new THREE.Mesh(g.core, material(u, [1, 1], CORE_FRAG)))
    for (const m of group.children) m.frustumCulled = false
    group.visible = false
    root.add(group)
    syms.push({ kind, group, u, age: 0, life: 0, alpha: 0, depthDim: 1, rise: 0, driftX: 0, spin: 0, wobble: 0, nextSpark: 0, sparkT: -1, ndc: new THREE.Vector2(9, 9) })
  }

  // scratch
  const v = new THREE.Vector3()
  const dir = new THREE.Vector3()
  const tmp2 = new THREE.Vector2()
  const box = { x0: 0, x1: 0, y0: 0, y1: 0, shTop: 0, shX: 0 }

  /** Screen-space no-go zones: the head (+ ears) and the shoulders. */
  function measureBody(camera: THREE.Camera) {
    const ndc = (x: number, y: number) => v.set(x, y, 0.8).project(camera)
    const tl = ndc(-2.25, 4.45).clone()
    const br = ndc(2.25, -1.1)
    box.x0 = tl.x - 0.05
    box.x1 = br.x + 0.05
    box.y0 = br.y - 0.04
    box.y1 = tl.y + 0.06
    box.shTop = ndc(0, -1.15).y + 0.05
    box.shX = ndc(4.6, -3.2).x + 0.04
  }
  const blocked = (nx: number, ny: number) =>
    (nx > box.x0 && nx < box.x1 && ny > box.y0 && ny < box.y1) || (ny < box.shTop && Math.abs(nx) < box.shX)

  function spawn(s: Sym, delay: number, camera: THREE.Camera) {
    measureBody(camera)
    const cam = camera as THREE.PerspectiveCamera
    let placed = false
    for (let tries = 0; tries < 40 && !placed; tries++) {
      // bias toward the far field so the screen feels deep, with some close ones
      const z = THREE.MathUtils.lerp(Z_FAR, Z_NEAR, Math.pow(Math.random(), 0.8))
      const nx = (Math.random() * 2 - 1) * 0.94
      const ny = -0.7 + Math.random() * 1.62 // lower sides … top corners
      if (blocked(nx, ny)) continue
      // keep some breathing room between symbols on screen
      if (tries < 30 && syms.some((o) => o !== s && o.age < o.life && o.ndc.distanceTo(tmp2.set(nx, ny)) < 0.2)) continue
      // where it will be when it fades out (it drifts up) must be clear too
      dir.set(nx, ny, 0.5).unproject(cam).sub(cam.position).normalize()
      const t = (z - cam.position.z) / dir.z
      const pos = cam.position.clone().addScaledVector(dir, t)
      s.rise = 0.05 + Math.random() * 0.08
      s.life = 5 + Math.random() * 3
      const end = v.copy(pos).add(new THREE.Vector3(0, s.rise * s.life, 0)).project(cam)
      if (blocked(end.x, end.y)) continue
      s.group.position.copy(pos)
      s.ndc.set(nx, ny)
      s.depthDim = THREE.MathUtils.mapLinear(z, Z_FAR, Z_NEAR, 0.42, 1.0)
      placed = true
    }
    if (!placed) {
      s.age = -1 // try again shortly
      return
    }
    const size = s.kind === 'bulb' ? 0.75 + Math.random() * 0.45 : 0.6 + Math.random() * 0.5
    s.group.scale.setScalar(size)
    s.group.rotation.set((Math.random() - 0.5) * 0.25, (Math.random() - 0.5) * 0.9, (Math.random() - 0.5) * 0.35)
    s.age = -delay
    s.alpha = 0
    s.driftX = (Math.random() - 0.5) * 0.06
    s.spin = (Math.random() - 0.5) * 0.4
    s.wobble = Math.random() * 10
    s.nextSpark = 1.2 + Math.random() * 3.5
    s.sparkT = -1
  }

  /** Idea spark: two quick flickers, then a soft glow that fades (≈1.4 s). */
  const spark = (t: number) => {
    if (t < 0) return 0
    if (t < 0.28) return Math.sin(t * 40) > 0 ? 1 : 0.2
    return Math.max(0, 1 - (t - 0.28) / 1.1) ** 2
  }

  let wasActive = false
  /** Returns the strongest symbol opacity still on screen (0 = all gone). */
  function update(dt: number, active: boolean, camera: THREE.Camera): number {
    if (active && !wasActive) syms.forEach((s, i) => spawn(s, 0.15 + i * 0.17, camera)) // staggered entrance
    wasActive = active

    let maxAlpha = 0
    for (const s of syms) {
      if (active) {
        s.age += dt
        if (s.age > s.life) spawn(s, 0.3 + Math.random() * 1.2, camera)
        const fadeIn = THREE.MathUtils.smoothstep(s.age, 0, FADE_IN)
        const fadeOut = 1 - THREE.MathUtils.smoothstep(s.age, s.life - 1.3, s.life)
        s.alpha = s.age < 0 ? 0 : fadeIn * fadeOut
      } else {
        s.alpha = Math.max(0, s.alpha - dt / FADE_OUT_END) // all gone within 0.6 s
      }
      s.group.visible = s.alpha > 0.002
      if (!s.group.visible) continue

      // slow drift + gentle rotation
      s.group.position.y += s.rise * dt
      s.group.position.x += s.driftX * dt
      s.group.rotation.y += s.spin * dt
      s.group.rotation.z = Math.sin(s.age * 0.6 + s.wobble) * 0.12

      // bulbs: occasional "idea" flicker
      let glow = 0
      if (s.kind === 'bulb' && active) {
        if (s.sparkT < 0 && s.age > s.nextSpark) s.sparkT = 0
        if (s.sparkT >= 0) {
          s.sparkT += dt
          glow = spark(s.sparkT)
          if (s.sparkT > 1.5) {
            s.sparkT = -1
            s.nextSpark = s.age + 2.5 + Math.random() * 3.5
          }
        }
      }
      s.u.uGlow.value = glow
      s.u.uAlpha.value = s.alpha * s.depthDim
      maxAlpha = Math.max(maxAlpha, s.alpha)
    }
    return maxAlpha
  }

  return { root, update }
}
