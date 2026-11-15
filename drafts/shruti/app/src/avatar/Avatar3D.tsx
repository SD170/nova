// ─────────────────────────────────────────────────────────────────────────────
// Avatar3D — holographic head & shoulders with layered animation + lip sync.
//
// PUBLIC API (avatarRef.current, or window.jarvisAvatar — see App.tsx). All calls
// return immediately; unknown names log a console warning and are ignored.
//
//   connectAudio(source)        HTMLAudioElement | MediaStream | AudioNode → lip sync
//   disconnectAudio()
//   setLevel(v)                 0..1 output volume fallback (e.g. Vapi 'volume-level')
//   setState(s)                 'idle' | 'listening' | 'thinking' | 'speaking'
//   setExpression({ name, duration_ms, intensity })   duration_ms null = hold
//   clearExpression()
//   lookAt({ target, duration_ms })  'left'|'right'|'up'|'down'|'user'|'shelf'
//   playGesture({ name })       'nod' | 'shake' | 'tilt'
//   endThinking()               → Promise: resolves when the thinking symbols are gone
//
// The avatar never makes sound itself; the mouth follows the audio you connect.
// While connected audio is audible and the state is 'idle', it switches itself to
// 'speaking' (and back after 1.3 s of silence).
// ─────────────────────────────────────────────────────────────────────────────
import { Canvas, useFrame, useLoader, useThree } from '@react-three/fiber'
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing'
import type { BloomEffect } from 'postprocessing'
import { forwardRef, Suspense, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { AnimationController, type FrameValues } from './AnimationController'
import { AvatarAudio, type AudioSourceLike } from './AvatarAudio'
import type { BaseState } from './expressions'
import { createHologramMaterial, FACE } from './hologramMaterial'
import { createSignalWaves, EARS } from './signalWaves'
import { createLiquidBackground } from './liquidBackground'
import { presence } from './presence'
import { createDissolveParticles } from './dissolveParticles'
import { createThinkingSymbols } from './thinkingSymbols'

export type AvatarState = BaseState

export interface Avatar3DHandle {
  getState: () => AvatarState
  connectAudio: (source: AudioSourceLike) => void
  disconnectAudio: () => void
  setLevel: (v: number) => void
  setState: (state: AvatarState) => void
  setExpression: (opts: { name: string; duration_ms?: number | null; intensity?: number }) => void
  clearExpression: () => void
  lookAt: (opts: { target: string; duration_ms?: number | null }) => void
  playGesture: (opts: { name: string }) => void
  /** End 'thinking' and resolve once every thinking symbol has fully faded out
   *  (~0.6 s) — await this BEFORE playing the reply so nothing overlaps. */
  endThinking: () => Promise<void>
  /** Cursor position -1..1 (x+ right, y+ up) for head/eye follow; null = recentre. */
  setPointer: (x: number | null, y?: number) => void
}

interface Props {
  /** 0..1 mic volume while the student talks (grid pulses with it while listening). */
  getMicLevel?: () => number
  /** Tint the face rig regions (dev aid). */
  debug?: boolean
}

const MODEL_URL = `${import.meta.env.BASE_URL}models/LeePerrySmith.glb`
const FOV = 30

export const Avatar3D = forwardRef<Avatar3DHandle, Props>(function Avatar3D(props, ref) {
  const audio = useMemo(() => new AvatarAudio(), [])
  const ctrl = useMemo(() => new AnimationController(), [])

  useImperativeHandle(ref, () => ({
    getState: () => ctrl.getState(),
    connectAudio: (s) => audio.connect(s),
    disconnectAudio: () => audio.disconnect(),
    setLevel: (v) => audio.setLevel(v),
    setState: (s) => ctrl.setState(s),
    setExpression: (o) => ctrl.setExpression(o),
    clearExpression: () => ctrl.clearExpression(),
    lookAt: (o) => ctrl.lookAt(o),
    playGesture: (o) => ctrl.playGesture(o),
    setPointer: (x, y) => ctrl.setPointer(x, y),
    endThinking: () => {
      if (ctrl.getState() === 'thinking') {
        ctrl.setState('idle')
        ctrl.lookAt({ target: 'user', duration_ms: 1600 }) // turn back to face the user
      }
      return new Promise<void>((resolve) => {
        const started = performance.now()
        const check = () => {
          const probe = (window as unknown as { __jarvisDebug?: { symbolsAlpha: number } }).__jarvisDebug
          if (!probe || probe.symbolsAlpha <= 0.001 || performance.now() - started > 1200) resolve()
          else setTimeout(check, 30)
        }
        setTimeout(check, 30)
      })
    },
  }))
  useEffect(() => () => audio.disconnect(), [audio])

  return (
    <Canvas
      className="!pointer-events-none"
      dpr={[1, 1.5]}
      gl={{ antialias: false, powerPreference: 'high-performance', alpha: false }}
      camera={{ position: [0, 0, 16], fov: FOV, near: 1, far: 100 }}
    >
      <CameraRig />
      <Suspense fallback={null}>
        <Scene {...props} audio={audio} ctrl={ctrl} />
      </Suspense>
    </Canvas>
  )
})

/**
 * Frames head + shoulders at any window size: the bottom of the screen always cuts
 * through the shoulders (no gap under them), the head fills most of the height,
 * and any spare room ends up ABOVE the head (reserved "shelf" space).
 */
function CameraRig() {
  const { camera, size } = useThree()
  useLayoutEffect(() => {
    const cam = camera as THREE.PerspectiveCamera
    const aspect = size.width / size.height
    const bottom = -3.5 // world y at the bottom edge — below it the scan is cut off
    const top = 4.25 // top of the skull + room for breathing / looking up
    let h = (top - bottom) / 0.92 // ~8% headroom
    h = Math.max(h, 4.2 / aspect) // narrow windows: keep the whole head + ears in view
    cam.fov = FOV
    cam.position.set(0, bottom + h / 2, h / 2 / Math.tan(THREE.MathUtils.degToRad(FOV / 2)))
    cam.lookAt(0, bottom + h / 2, -100)
    cam.updateProjectionMatrix()
  }, [camera, size])
  return null
}

function Scene({ getMicLevel, debug, audio, ctrl }: Props & { audio: AvatarAudio; ctrl: AnimationController }) {
  const gltf = useLoader(GLTFLoader, MODEL_URL)
  const head = useMemo(() => createHologramMaterial(), [])
  const geometry = useMemo(() => {
    let g: THREE.BufferGeometry | null = null
    gltf.scene.traverse((o) => {
      if (!g && (o as THREE.Mesh).isMesh) g = (o as THREE.Mesh).geometry
    })
    return g!
  }, [gltf])
  const particles = useMemo(() => createParticles(), [])
  const dust = useMemo(() => createDissolveParticles(geometry), [geometry]) // idle dissolve
  const signal = useMemo(() => createSignalWaves(), [])
  // thinking: ? ! and light-bulb symbols across the screen
  const symbols = useMemo(() => createThinkingSymbols(), [])
  // read-only numbers for automated checks (no UI): window.__jarvisDebug
  const probe = useMemo(() => {
    const d = { symbolsAlpha: 0, mouth: null as unknown }
    ;(window as unknown as { __jarvisDebug: typeof d }).__jarvisDebug = d
    return d
  }, [])
  // liquid-silk background: rendered to a low-res texture each frame, used as scene.background
  const background = useMemo(() => createLiquidBackground(), [])
  const { scene, size, viewport } = useThree()
  useEffect(() => {
    scene.background = background.texture
    return () => {
      scene.background = null
    }
  }, [scene, background])
  const points = useRef<THREE.Points>(null)
  const bloom = useRef<BloomEffect>(null)

  useEffect(() => {
    head.uniforms.uDebug.value = debug ? 1 : 0
  }, [debug, head])

  // scratch objects (no per-frame allocation)
  const tmp = useMemo(
    () => ({
      euler: new THREE.Euler(),
      m4: new THREE.Matrix4(),
      m3: new THREE.Matrix3(),
      v: new THREE.Vector3(),
    }),
    [],
  )

  useFrame(({ clock, gl, camera }, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const t = clock.elapsedTime
    const pf = presence.update(dt) // boot / dissolve / wake sequences
    background.render(gl, t, size.width * viewport.dpr, size.height * viewport.dpr, pf.bgFade)

    // LAYER 3 input: mouth shape from audio only
    const mouth = audio.read(dt)
    const mic = ctrl.getState() === 'listening' && getMicLevel ? getMicLevel() : 0
    // LAYERS 1 + 2 + 2b + gestures
    const f = ctrl.update(dt, t, { level: mouth.level, active: audio.isActive() }, mic)

    applyFrame(f, mouth)
    // presence (boot scanline, eye ignition, dissolve)
    head.uniforms.uRevealOn.value = pf.revealOn
    head.uniforms.uRevealY.value = pf.revealY
    head.uniforms.uEyeIgnite.value = pf.eyeIgnite
    head.uniforms.uDissolve.value = pf.dissolve
    particles.material.uniforms.uFade.value = pf.bgFade
    dust.update(pf.spread, pf.particleAlpha, t, gl.getPixelRatio())
    probe.mouth = mouth
    probe.symbolsAlpha = symbols.update(dt, f.thinking > 0.5, camera)
    particles.material.uniforms.uPx.value = gl.getPixelRatio()
  })

  /** The ONE place uniforms are written each frame. */
  function applyFrame(f: FrameValues, mouth: { jaw: number; wide: number; round: number; mm: number; ff: number }) {
    const u = head.uniforms
    u.uTime.value = f.time
    // mouth layer last, straight from audio — expressions only add lip corners
    u.uJaw.value = mouth.jaw
    u.uWide.value = mouth.wide
    u.uRound.value = mouth.round
    u.uMM.value = mouth.mm
    u.uFF.value = mouth.ff
    u.uEmph.value = f.emph
    u.uBrow.value = f.brow
    u.uLipCorner.value = f.lipCorner
    // head pose (shader applies it to head + neck only)
    tmp.euler.set(f.pitch, f.yaw, f.roll, 'YXZ')
    tmp.m4.makeRotationFromEuler(tmp.euler)
    ;(u.uHeadRot.value as THREE.Matrix3).setFromMatrix4(tmp.m4)
    ;(u.uHeadOffset.value as THREE.Vector3).set(0, -f.lean * 0.12, f.lean)
    u.uBreath.value = f.breath
    // eyes
    ;(u.uEyeOpen.value as THREE.Vector2).set(f.eyeOpen[0], f.eyeOpen[1])
    ;(u.uEyeLook.value as THREE.Vector2).set(f.eyeLook[0], f.eyeLook[1])
    u.uEyeGlow.value = f.eyeGlow
    // color + fx
    ;(u.uGridColor.value as THREE.Color).setRGB(f.gridColor[0], f.gridColor[1], f.gridColor[2])
    u.uTintAmount.value = f.tintAmount
    u.uBrightness.value = f.brightness
    u.uEnergy.value = f.energy
    u.uScanPhase.value = f.scanPhase
    u.uGlitch.value = f.glitch
    u.uShimmer.value = f.thinking
    // particles + bloom
    const pu = particles.material.uniforms
    pu.uRise.value = f.particleRise
    pu.uCount.value = f.particleCount
    ;(pu.uTint.value as THREE.Color).setRGB(f.gridColor[0], f.gridColor[1], f.gridColor[2])
    pu.uTintAmount.value = f.tintAmount
    if (points.current) points.current.rotation.y = f.particleSpin
    if (bloom.current) bloom.current.intensity = f.bloom

    // signal waves (listening): ride along with the head, mostly facing the camera
    const su = signal.uniforms
    su.uArc.value.fromArray(f.signalArcs)
    su.uExpand.value.fromArray(f.signalExpand)
    su.uMaster.value = f.signalMaster
    su.uTime.value = f.time
    const on = f.signalMaster > 0.002 || f.signalArcs.some((b) => b > 0.002)
    tmp.m3.setFromMatrix4(tmp.m4) // head rotation (same as the shader's uHeadRot)
    for (const [mesh, ear] of [[signal.left, EARS.left], [signal.right, EARS.right]] as const) {
      mesh.visible = on
      if (!on) continue
      // same transform the vertex shader applies to the head
      tmp.v.copy(ear).sub(FACE.neckPivot).applyMatrix3(tmp.m3).add(FACE.neckPivot)
      mesh.position.set(tmp.v.x, tmp.v.y - f.lean * 0.12 + f.breath, tmp.v.z + f.lean)
      mesh.rotation.set(f.pitch * 0.35, f.yaw * 0.35, f.roll, 'YXZ')
    }
  }

  return (
    <>
      <mesh geometry={geometry} material={head} frustumCulled={false} />
      <points ref={points} geometry={particles.geometry} material={particles.material} frustumCulled={false} />
      <primitive object={symbols.root} />
      <primitive object={dust.points} />
      <primitive object={signal.left} />
      <primitive object={signal.right} />
      <EffectComposer multisampling={0} enableNormalPass={false}>
        <Bloom ref={bloom as never} mipmapBlur intensity={1.25} luminanceThreshold={0.12} luminanceSmoothing={0.35} radius={0.72} />
        <Vignette eskil={false} offset={0.25} darkness={0.6} />
      </EffectComposer>
    </>
  )
}

/** Floating motes around the bust. Speed / direction / count come from the layers. */
function createParticles() {
  const COUNT = 520
  const pos = new Float32Array(COUNT * 3)
  const seed = new Float32Array(COUNT)
  for (let i = 0; i < COUNT; i++) {
    const r = 4.6 + Math.random() * 7
    const a = Math.random() * Math.PI * 2
    pos[i * 3] = Math.cos(a) * r
    pos[i * 3 + 1] = (Math.random() - 0.5) * 14
    pos[i * 3 + 2] = Math.sin(a) * r - 2
    seed[i] = Math.random()
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1))
  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uPx: { value: 1 },
      uRise: { value: 0 },
      uCount: { value: 1 },
      uTint: { value: new THREE.Color(0.224, 1.0, 0.078) },
      uTintAmount: { value: 0 },
      uFade: { value: 1 },
    },
    vertexShader: /* glsl */ `
      attribute float aSeed;
      uniform float uPx, uRise, uCount;
      varying float vSeed;
      varying float vTw;
      varying float vVis;
      void main() {
        vec3 p = position;
        p.y = mod(p.y + 7.0 + uRise * (0.15 + aSeed * 0.35), 14.0) - 7.0;
        vSeed = aSeed;
        vTw = 0.5 + 0.5 * sin(uRise * 3.0 * (1.0 + aSeed) + aSeed * 40.0);
        vVis = 1.0 - smoothstep(uCount - 0.12, uCount, aSeed); // fade, never pop
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = uPx * (1.5 + aSeed * 3.5) * (22.0 / -mv.z) * step(0.001, vVis);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uTint;
      uniform float uTintAmount, uFade;
      varying float vSeed;
      varying float vTw;
      varying float vVis;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d) * (0.35 + 0.65 * vTw) * vVis;
        vec3 c = vSeed > 0.82 ? uTint : mix(vec3(0.486, 0.227, 0.929), vec3(0.655, 0.545, 0.98), vSeed);
        c = mix(c, uTint, uTintAmount * 0.35);
        gl_FragColor = vec4(c * a * 0.7 * uFade, a * uFade); // faint, on top of the silk
      }
    `,
  })
  return { geometry, material }
}
