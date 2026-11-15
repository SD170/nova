// Idle dissolve particles: one glowing point per (every other) vertex of the head
// scan. At spread 0 they sit exactly on the face; as spread grows they drift
// outward and float gently like dust in space. presence.ts drives spread/alpha:
// dissolve (out, ~2 s) → float → wake (rush back, ~0.8 s) → fade as the grid redraws.
import * as THREE from 'three'

export function createDissolveParticles(head: THREE.BufferGeometry) {
  const src = head.getAttribute('position')
  const step = 2
  const n = Math.floor(src.count / step)
  const pos = new Float32Array(n * 3)
  const dir = new Float32Array(n * 3)
  const seed = new Float32Array(n)
  const c = new THREE.Vector3(0, 0.6, -0.4) // rough centre of the bust
  const v = new THREE.Vector3()
  for (let i = 0; i < n; i++) {
    v.fromBufferAttribute(src, i * step)
    pos.set([v.x, v.y, v.z], i * 3)
    // outward from the centre, with some randomness so it reads as dust, not a shell
    const d = v.clone().sub(c).normalize()
    d.x += (Math.random() - 0.5) * 0.8
    d.y += (Math.random() - 0.5) * 0.8 + 0.15 // slight upward float
    d.z += (Math.random() - 0.5) * 0.8
    d.normalize()
    dir.set([d.x, d.y, d.z], i * 3)
    seed[i] = Math.random()
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  geometry.setAttribute('aDir', new THREE.BufferAttribute(dir, 3))
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1))

  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: { uSpread: { value: 0 }, uAlpha: { value: 0 }, uTime: { value: 0 }, uPx: { value: 1 } },
    vertexShader: /* glsl */ `
      attribute vec3 aDir;
      attribute float aSeed;
      uniform float uSpread, uTime, uPx;
      varying float vSeed;
      varying float vTw;
      void main() {
        vec3 p = position + aDir * (0.7 + aSeed * 2.8) * uSpread;
        // gentle floating once drifted
        p += vec3(sin(uTime * 0.55 + aSeed * 31.0), cos(uTime * 0.45 + aSeed * 17.0), sin(uTime * 0.35 + aSeed * 7.0)) * 0.14 * min(uSpread, 1.0);
        vSeed = aSeed;
        vTw = 0.6 + 0.4 * sin(uTime * (1.5 + aSeed * 2.0) + aSeed * 50.0);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = uPx * (1.3 + aSeed * 2.2) * (18.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uAlpha;
      varying float vSeed;
      varying float vTw;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.05, d) * vTw * uAlpha;
        vec3 c = vSeed < 0.62 ? vec3(0.224, 1.0, 0.078) : vec3(0.55, 0.3, 1.0); // neon green + purple
        gl_FragColor = vec4(c * a * 0.9, a);
      }
    `,
  })
  const points = new THREE.Points(geometry, material)
  points.frustumCulled = false
  points.visible = false
  points.renderOrder = 6

  function update(spread: number, alpha: number, time: number, px: number) {
    material.uniforms.uSpread.value = spread
    material.uniforms.uAlpha.value = alpha
    material.uniforms.uTime.value = time
    material.uniforms.uPx.value = px
    points.visible = alpha > 0.003
  }
  return { points, update }
}
