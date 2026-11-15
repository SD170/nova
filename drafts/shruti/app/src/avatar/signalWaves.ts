// Signal waves — the "thinking" effect. Like a broadcast / wifi icon on each side
// of the head: 4 arcs per side, "(" on the left and ")" on the right, opening away
// from the head. Arc brightness + outward growth come from AnimationController
// (signalArcs / signalExpand); this file only draws them.
//
// Each side is a flat camera-facing quad anchored just outside the ear. Avatar3D
// moves it with the head every frame and tilts it a little with the head's angle.
import * as THREE from 'three'

/** Ear anchor points in model space (the scan is slightly asymmetric). */
export const EARS = {
  left: new THREE.Vector3(-1.95, 1.45, -0.05), // viewer's left
  right: new THREE.Vector3(1.8, 1.45, -0.05),
}

const PLANE_W = 2.6
const PLANE_H = 4.4

export function createSignalWaves() {
  // shared uniform objects → one write updates both sides
  const shared = {
    uArc: { value: new THREE.Vector4() },
    uExpand: { value: new THREE.Vector4() },
    uMaster: { value: 0 },
    uTime: { value: 0 },
  }
  const geometry = new THREE.PlaneGeometry(PLANE_W, PLANE_H)
  geometry.translate(PLANE_W / 2 - 0.2, 0, 0) // origin = ear; quad extends outward (+x)

  const make = (seed: number) =>
    new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide, // left side is mirrored (scale.x = -1)
      uniforms: { ...shared, uSeed: { value: seed } },
      vertexShader: /* glsl */ `
        varying vec2 vP;
        void main() {
          vP = position.xy; // local: x = outward from the ear, y = up
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec4 uArc, uExpand;
        uniform float uMaster, uTime, uSeed;
        varying vec2 vP;

        const vec3 GREEN  = vec3(0.224, 1.0, 0.078);  // #39FF14 (inner)
        const vec3 VIOLET = vec3(0.655, 0.545, 0.980); // #A78BFA
        const vec3 PURPLE = vec3(0.486, 0.227, 0.929); // #7C3AED (outer)
        // deeper versions for the glowing arcs: bloom brightens toward white, so
        // starting more saturated lands on the intended violet / purple on screen
        const vec3 VIOLET_S = vec3(0.50, 0.30, 1.0);
        const vec3 PURPLE_S = vec3(0.42, 0.10, 0.95);
        const float HALF = 0.88;   // half-angle of each arc (~100° total)
        const float WIDTH = 0.05;  // core thickness

        float hash(float n) { return fract(sin(n) * 43758.5453); }

        vec3 arc(float r, float bright, vec3 color, float alpha, float len, float ang) {
          float d = abs(len - r);
          float core = smoothstep(WIDTH, WIDTH * 0.3, d);
          float halo = exp(-(d * d) / 0.022) * 0.55;
          // soft rounded ends instead of hard cut-offs
          float span = smoothstep(HALF, HALF - 0.28, abs(ang));
          return color * (core * 1.7 + halo * 1.3) * span * bright * alpha;
        }

        void main() {
          float len = length(vP);
          float ang = atan(vP.y, vP.x); // 0 = straight out from the ear
          vec3 col = vec3(0.0);
          // inner → outer: neon green → violet → purple (saturated so bloom keeps the hue)
          col += arc(0.3  + uExpand.x, uArc.x, GREEN * 1.25,                  1.0,  len, ang);
          col += arc(0.64 + uExpand.y, uArc.y, mix(GREEN, VIOLET_S, 0.6),       0.92, len, ang);
          col += arc(0.98 + uExpand.z, uArc.z, VIOLET_S,                      0.8,  len, ang);
          col += arc(1.32 + uExpand.w, uArc.w, PURPLE_S,                      0.68, len, ang);

          // a few sparkles drifting outward off the arcs
          for (int k = 0; k < 7; k++) {
            float fk = float(k) + uSeed * 13.0;
            float life = fract(uTime * (0.32 + hash(fk) * 0.2) + hash(fk + 4.2));
            float a = (hash(fk + 1.3) - 0.5) * 1.6;
            float rr = 0.45 + life * 1.7;
            vec2 p = rr * vec2(cos(a), sin(a)) + vec2(0.0, life * 0.25);
            float s = smoothstep(0.05, 0.0, length(vP - p));
            float tw = 0.6 + 0.4 * sin(uTime * 12.0 + fk * 7.0);
            vec3 sc = mix(GREEN, VIOLET, hash(fk + 9.0));
            col += sc * s * tw * (1.0 - life) * smoothstep(0.0, 0.15, life) * 1.4;
          }

          col *= uMaster;
          gl_FragColor = vec4(col, 1.0);
        }
      `,
    })

  const left = new THREE.Mesh(geometry, make(1))
  const right = new THREE.Mesh(geometry, make(2))
  left.scale.x = -1 // mirror → "(" on the viewer's left, ")" on the right
  for (const m of [left, right]) {
    m.frustumCulled = false
    m.renderOrder = 10
    m.visible = false
  }
  return { left, right, uniforms: shared }
}
