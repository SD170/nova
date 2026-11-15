// ─────────────────────────────────────────────────────────────────────────────
// Liquid silk / molten black metal background.
//
// A fullscreen GLSL shader: domain-warped fbm noise gives a smooth "height" field;
// finite-difference normals + fake lighting make it read as glossy folds; fold
// edges pick up iridescent highlights (purple, violet, electric blue, magenta-pink)
// with rare neon-green glints. Kept ~70% dark, with extra darkness behind the head.
//
// Performance: it renders into a LOW-RES render target (35% of the canvas) every
// frame and that texture becomes `scene.background`, so it always sits BEHIND the
// avatar. The folds are smooth, so the upscale is invisible.
// ─────────────────────────────────────────────────────────────────────────────
import * as THREE from 'three'

const RES_SCALE = 0.35

export function createLiquidBackground() {
  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)
  const material = new THREE.ShaderMaterial({
    depthTest: false,
    depthWrite: false,
    uniforms: {
      uTime: { value: 0 },
      uAspect: { value: 1 },
      uFocus: { value: new THREE.Vector2(0.5, 0.58) }, // where the head is (uv)
    },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = vec4(position.xy, 0.0, 1.0);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uTime, uAspect;
      uniform vec2 uFocus;
      varying vec2 vUv;

      const vec3 BASE0   = vec3(0.020, 0.012, 0.039); // #05030A
      const vec3 BASE1   = vec3(0.043, 0.031, 0.125); // #0B0820
      const vec3 PURPLE  = vec3(0.486, 0.227, 0.929); // #7C3AED
      const vec3 VIOLET  = vec3(0.655, 0.545, 0.980); // #A78BFA
      const vec3 BLUE    = vec3(0.231, 0.510, 0.965); // #3B82F6
      const vec3 MAGENTA = vec3(0.925, 0.282, 0.600); // #EC4899
      const vec3 GREEN   = vec3(0.224, 1.000, 0.078); // #39FF14

      vec2 hash2(vec2 p) {
        p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
        return -1.0 + 2.0 * fract(sin(p) * 43758.5453);
      }
      // gradient noise, smooth (quintic) → no grid artifacts in the folds
      float noise(vec2 p) {
        vec2 i = floor(p), f = fract(p);
        vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
        return mix(mix(dot(hash2(i), f), dot(hash2(i + vec2(1, 0)), f - vec2(1, 0)), u.x),
                   mix(dot(hash2(i + vec2(0, 1)), f - vec2(0, 1)), dot(hash2(i + vec2(1, 1)), f - vec2(1, 1)), u.x), u.y);
      }
      float fbm(vec2 p) {
        float v = 0.0, a = 0.5;
        mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
        for (int i = 0; i < 3; i++) { v += a * noise(p); p = m * p; a *= 0.45; }
        return v;
      }

      // domain-warped height field; also returns the warp vector for color variety
      float silk(vec2 p, float t, out vec2 warp) {
        vec2 q = vec2(fbm(p + vec2(0.0, t * 0.6)), fbm(p + vec2(5.2, 1.3) - t * 0.4));
        vec2 r = vec2(fbm(p + 1.5 * q + vec2(1.7, 9.2) + t * 0.3),
                      fbm(p + 1.5 * q + vec2(8.3, 2.8) - t * 0.25));
        warp = r;
        return fbm(p + 1.7 * r);
      }

      // cyclic iridescent palette: purple → violet → blue → magenta → purple
      vec3 iridescent(float h) {
        h = fract(h) * 4.0;
        if (h < 1.0) return mix(PURPLE, VIOLET, smoothstep(0.0, 1.0, h));
        if (h < 2.0) return mix(VIOLET, BLUE, smoothstep(1.0, 2.0, h));
        if (h < 3.0) return mix(BLUE, MAGENTA, smoothstep(2.0, 3.0, h));
        return mix(MAGENTA, PURPLE, smoothstep(3.0, 4.0, h));
      }

      void main() {
        vec2 p = (vUv - 0.5) * vec2(uAspect, 1.0) * 1.05; // large, slow folds
        float t = uTime * 0.035; // one full drift ≈ 25 s — slow and calm

        vec2 warp, w2;
        float e = 0.02;
        float h  = silk(p, t, warp);
        float hx = silk(p + vec2(e, 0.0), t, w2);
        float hy = silk(p + vec2(0.0, e), t, w2);
        vec3 n = normalize(vec3(-(hx - h) / e * 0.9, -(hy - h) / e * 0.9, 1.0));

        vec3 L = normalize(vec3(-0.45, 0.6, 0.65));
        vec3 V = vec3(0.0, 0.0, 1.0);
        float diff = max(dot(n, L), 0.0);
        float spec = pow(max(dot(reflect(-L, n), V), 0.0), 34.0);
        float edge = smoothstep(0.04, 0.45, 1.0 - n.z); // steep fold edges

        vec3 base = mix(BASE0, BASE1, smoothstep(-0.4, 0.5, h)) * (0.55 + 0.9 * diff);
        vec3 irid = iridescent(dot(n.xy, vec2(0.9, 0.55)) * 1.3 + warp.x * 0.9 + t * 0.4);
        vec3 col = base * 1.3 + irid * (edge * 0.85 + spec * 0.95);

        // a few faint neon-green glints on the brightest ridges
        float glint = smoothstep(0.55, 0.75, noise(p * 2.3 + warp * 3.0 + t * 2.0)) * spec;
        col += GREEN * glint * 0.45;

        col *= 0.6; // keep it dim (~70% dark)
        // darker pool behind the head so the avatar stays the focus
        float d = length((vUv - uFocus) * vec2(uAspect, 1.0));
        col *= mix(0.22, 1.0, smoothstep(0.08, 0.62, d));
        // The 3D pipeline converts its output to sRGB at the end; store linear here
        // so the colors land on screen exactly as the hex values above.
        gl_FragColor = vec4(pow(col, vec3(2.2)), 1.0);
      }
    `,
  })
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material)
  quad.frustumCulled = false
  scene.add(quad)

  const target = new THREE.WebGLRenderTarget(16, 16, { depthBuffer: false })
  target.texture.minFilter = THREE.LinearFilter
  target.texture.magFilter = THREE.LinearFilter

  /** Re-render the silk for this frame (call before the main render). */
  function render(gl: THREE.WebGLRenderer, time: number, width: number, height: number) {
    const w = Math.max(64, Math.round(width * RES_SCALE))
    const h = Math.max(64, Math.round(height * RES_SCALE))
    if (target.width !== w || target.height !== h) target.setSize(w, h)
    material.uniforms.uTime.value = time
    material.uniforms.uAspect.value = width / height
    const prev = gl.getRenderTarget()
    gl.setRenderTarget(target)
    gl.render(scene, camera)
    gl.setRenderTarget(prev)
  }

  return { texture: target.texture, render, uniforms: material.uniforms }
}
