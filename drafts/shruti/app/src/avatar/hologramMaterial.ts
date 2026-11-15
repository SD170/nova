// Hologram material for the head-and-shoulders scan.
//
// Vertex shader — procedural rig (the model has no blendshapes):
//   face:  jaw hinge, lip stretch/pucker, upper-lip lift, fuller lips, lip-corner
//          offset (expressions), per-eye lids (blink / wink / wide eyes)
//   head:  rotation + lean applied only to head & neck (shoulders stay planted)
//   fx:    glitch slice jitter, breathing
// Fragment shader — neon grid, shadow/rim glow, scan band, eye glow + gaze, the
//   see-through mouth and glowing violet lips. All colors come from uniforms.
//
// Every uniform is written once per frame from AnimationController's FrameValues
// (see Avatar3D.tsx → applyFrame). Nothing else writes them.
import * as THREE from 'three'

/** Landmarks in the model's own units (LeePerrySmith.glb, face toward +Z). */
export const FACE = {
  mouthY: 0.45,
  mouthHalfW: 0.56,
  chinY: -0.35,
  hinge: new THREE.Vector2(1.05, -0.6), // (y, z) of the jaw hinge
  eyeY: 1.75,
  // the scan isn't perfectly symmetric: viewer's-left eye sits a bit further out
  eyeXL: -0.84,
  eyeXR: 0.75,
  eyeR: new THREE.Vector2(0.36, 0.2),
  neckPivot: new THREE.Vector3(0, -1.6, 0), // head turns around this point
}

export function createHologramMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      // mouth layer (audio only)
      uJaw: { value: 0 },
      uWide: { value: 0 },
      uRound: { value: 0 },
      uMM: { value: 0 },
      uFF: { value: 0 },
      // subtle face motion
      uEmph: { value: 0 }, // cheek raise + nostril flare on emphasis
      uBrow: { value: 0 }, // eyebrow raise on louder moments
      // expression / base outputs
      uLipCorner: { value: 0 },
      uEyeOpen: { value: new THREE.Vector2(1, 1) },
      uEyeGlow: { value: 1 },
      uEyeLook: { value: new THREE.Vector2(0, 0) },
      uGridColor: { value: new THREE.Color(0.224, 1.0, 0.078) },
      uTintAmount: { value: 0 },
      uBrightness: { value: 1 },
      uEnergy: { value: 0 },
      uScanPhase: { value: 0 },
      uGlitch: { value: 0 },
      uShimmer: { value: 0 }, // thinking: soft wave rising through the grid
      // head pose
      uHeadRot: { value: new THREE.Matrix3() },
      uHeadOffset: { value: new THREE.Vector3() },
      uHeadPivot: { value: FACE.neckPivot.clone() },
      uBreath: { value: 0 },
      // landmarks
      uMouthY: { value: FACE.mouthY },
      uMouthHalfW: { value: FACE.mouthHalfW },
      uChinY: { value: FACE.chinY },
      uHinge: { value: FACE.hinge },
      uEyeY: { value: FACE.eyeY },
      uEyeXL: { value: FACE.eyeXL },
      uEyeXR: { value: FACE.eyeXR },
      uEyeR: { value: FACE.eyeR },
      uDebug: { value: 0 },
    },
    vertexShader: /* glsl */ `
      uniform float uTime, uJaw, uWide, uRound, uMM, uFF, uLipCorner, uGlitch, uBreath, uEmph, uBrow;
      uniform vec2 uEyeOpen;
      uniform float uMouthY, uMouthHalfW, uChinY, uEyeY, uEyeXL, uEyeXR;
      uniform vec2 uHinge, uEyeR;
      uniform mat3 uHeadRot;
      uniform vec3 uHeadOffset, uHeadPivot;

      varying vec3 vRest;      // undeformed position: grid sticks to the "skin"
      varying vec3 vPos;       // deformed position (before head pose): grid inside the open mouth
      varying vec3 vNormalV;   // view-space normal
      varying vec3 vViewDir;
      varying float vJawW;

      vec3 rotX(vec3 p, float a) {
        float c = cos(a), s = sin(a);
        return vec3(p.x, p.y * c - p.z * s, p.y * s + p.z * c);
      }
      float hash(float n) { return fract(sin(n) * 43758.5453); }

      // squash/stretch one eye region toward its center line; open: 0 closed, 1 normal, >1 wide
      vec3 lid(vec3 p, vec3 rest, float cx, float open) {
        vec2 d = (rest.xy - vec2(cx, uEyeY)) / uEyeR;
        float e = (1.0 - smoothstep(0.55, 1.0, length(d))) * smoothstep(1.2, 1.9, rest.z);
        float s = open < 1.0 ? mix(0.15, 1.0, open) : 1.0 + (open - 1.0) * 0.6;
        float shut = 1.0 - min(open, 1.0);
        p.y = mix(p.y, uEyeY + (p.y - uEyeY) * s - 0.02 * shut, e);
        p.z -= shut * 0.03 * e;
        return p;
      }

      void main() {
        vec3 p = position;
        vRest = position;
        float ax = abs(p.x);
        float front = smoothstep(-0.2, 1.2, p.z);

        // ── LIPS (static sculpt): real volume — rounded, plump, a cupid's bow on the
        // upper lip, a fuller lower lip, soft tapered corners. Everything expands
        // smoothly away from the seam, so a closed mouth stays sealed.
        float dy    = position.y - uMouthY;
        float taper = clamp(1.0 - pow(ax / (uMouthHalfW * 1.08), 2.0), 0.0, 1.0); // soft corners
        float upBand  = smoothstep(-0.005, 0.03, dy) * (1.0 - smoothstep(0.1, 0.2, dy));
        float lowBand = smoothstep(0.005, -0.03, dy) * (1.0 - smoothstep(0.12, 0.24, -dy));
        float lipVol  = (upBand * 0.07 + lowBand * 0.105) * taper * front;
        p.z += lipVol;                                         // pout (lower lip fuller)
        p.y += dy * 0.2 * (upBand + lowBand) * taper * front; // thickness
        p.y -= 0.02 * lowBand * taper * front;                 // lower lip sits a bit lower
        // cupid's bow: two peaks either side of a small centre dip on the upper border
        float bow = exp(-pow((ax - 0.12) / 0.06, 2.0)) - 0.7 * exp(-pow(ax / 0.045, 2.0));
        float border = smoothstep(0.05, 0.11, dy) * (1.0 - smoothstep(0.13, 0.2, dy));
        p.y += 0.03 * bow * border * front;
        p.z += 0.015 * bow * border * front;

        // ── MOUTH LAYER (audio visemes). Jaw rotates open around a hinge near the
        // ears; the chin and lower cheeks travel with it (wide, soft falloff).
        float soft  = mix(0.1, 1.05, smoothstep(uMouthHalfW * 0.8, uMouthHalfW * 1.5, ax));
        float below = smoothstep(uMouthY + 0.03, uMouthY - soft, p.y);
        float side  = 1.0 - smoothstep(uMouthHalfW * 1.8, uMouthHalfW * 4.2, ax);
        float neck  = smoothstep(uChinY - 1.4, uChinY - 0.3, p.y);
        float wJaw  = below * side * neck * front;
        vJawW = wJaw;
        vec3 pivot = vec3(0.0, uHinge.x, uHinge.y);
        p = mix(p, rotX(p - pivot, uJaw * 0.17) + pivot, wJaw);

        float lipX = 1.0 - smoothstep(uMouthHalfW * 0.75, uMouthHalfW * 1.25, ax);
        float lipY = 1.0 - smoothstep(0.0, 0.32, abs(dy));
        float wLip = lipX * lipY * front;
        float upper = smoothstep(uMouthY - 0.01, uMouthY + 0.05, position.y) * wLip;
        float lower = smoothstep(uMouthY + 0.01, uMouthY - 0.05, position.y) * wLip;
        p.y += uJaw * 0.07 * upper;                       // upper lip lifts as it opens
        // "ee": wider, corners pulled back · "oo": rounded + pushed forward
        p.x *= 1.0 + (uWide * 0.13 - uRound * 0.2) * wLip;
        p.z += (uRound * 0.13 - uWide * 0.025) * wLip;
        // "mm/bb": lips pressed together (thinner, slightly in)
        p.y = mix(p.y, uMouthY + (p.y - uMouthY) * 0.72, uMM * (upBand + lowBand) * taper * front);
        p.z -= 0.025 * uMM * wLip;
        // "ff": lower lip tucked up under the top teeth
        p.y += 0.04 * uFF * lower;
        p.z -= 0.06 * uFF * lower;

        // ── subtle realism on emphasis: cheeks lift, nostrils flare, brows rise
        vec2 ck = vec2(ax - 1.0, position.y - 0.95);
        float cheek = exp(-dot(ck, ck) / 0.13) * front;
        p.y += 0.045 * uEmph * cheek;
        p.z += 0.02 * uEmph * cheek;
        vec2 nk = vec2(ax - 0.33, position.y - 0.93);
        float nostril = exp(-dot(nk, nk) / 0.012) * smoothstep(1.8, 2.2, position.z);
        p.x += sign(p.x) * 0.028 * uEmph * nostril;
        float brow = exp(-pow((position.y - 2.12) / 0.13, 2.0)) * (1.0 - smoothstep(0.9, 1.25, ax)) * smoothstep(1.4, 1.9, position.z);
        p.y += 0.06 * uBrow * brow;

        // ── EXPRESSION: additive lip-corner lift (never touches the jaw)
        float corner = (1.0 - smoothstep(0.0, 0.24, abs(ax - uMouthHalfW * 0.95)))
                     * (1.0 - smoothstep(0.0, 0.22, abs(position.y - uMouthY))) * front;
        p.y += uLipCorner * 0.075 * corner;
        p.x += sign(p.x) * max(uLipCorner, 0.0) * 0.035 * corner;

        // ── eyes: per-eye openness (blink, wink, squint, wide)
        p = lid(p, position, uEyeXL, uEyeOpen.x); // viewer's left eye
        p = lid(p, position, uEyeXR, uEyeOpen.y); // viewer's right eye

        // ── glitch: random horizontal slices jump sideways
        if (uGlitch > 0.001) {
          float slice = floor(position.y * 5.0) + floor(uTime * 14.0) * 7.0;
          float on = step(0.82, hash(slice));
          p.x += (hash(slice + 3.1) - 0.5) * 0.35 * uGlitch * on;
        }

        vPos = p;

        // ── head pose: only head + neck rotate; shoulders stay put
        float wHead = max(smoothstep(-1.6, -0.9, position.y),
                          smoothstep(-2.5, -1.3, position.y) * (1.0 - smoothstep(0.9, 1.8, ax)));
        vec3 hp = uHeadRot * (p - uHeadPivot) + uHeadPivot + uHeadOffset;
        p = mix(p, hp, wHead);
        vec3 n = normalize(mix(normal, uHeadRot * normal, wHead));
        p.y += uBreath * (0.55 + 0.45 * wHead);

        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        vViewDir = normalize(-mv.xyz);
        vNormalV = normalize(normalMatrix * n);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uTime, uDebug, uJaw, uMouthY, uMouthHalfW, uEyeY, uEyeXL, uEyeXR;
      uniform float uEyeGlow, uTintAmount, uBrightness, uEnergy, uScanPhase, uGlitch, uShimmer;
      uniform vec2 uEyeR, uEyeOpen, uEyeLook;
      uniform vec3 uGridColor;
      varying vec3 vRest;
      varying vec3 vPos;
      varying vec3 vNormalV;
      varying vec3 vViewDir;
      varying float vJawW;

      const vec3 PURPLE = vec3(0.486, 0.227, 0.929); // #7C3AED
      const vec3 VIOLET = vec3(0.655, 0.545, 0.980); // #A78BFA

      float line(float v, float width) {
        float d = abs(fract(v - 0.5) - 0.5) / max(fwidth(v), 1e-4);
        return 1.0 - clamp(d - width, 0.0, 1.0);
      }
      float hash(float n) { return fract(sin(n) * 43758.5453); }

      float eyeGlow(float cx, float open) {
        vec2 c = vec2(cx, uEyeY) + uEyeLook * vec2(0.13, 0.07);
        vec2 r = uEyeR * vec2(0.62, 0.62 * clamp(open, 0.05, 1.4));
        float d = length((vRest.xy - c) / r);
        return (1.0 - smoothstep(0.25, 1.0, d)) * smoothstep(1.2, 1.9, vRest.z) * smoothstep(0.05, 0.35, open);
      }

      void main() {
        vec3 n = normalize(vNormalV);
        vec3 v = normalize(vViewDir);
        float facing = clamp(dot(n, v), 0.0, 1.0);
        float fres = pow(1.0 - facing, 2.4);

        vec3 L = normalize(vec3(-0.5, 0.6, 0.6));
        float lit = smoothstep(-0.25, 0.85, dot(n, L));
        float shadow = 1.0 - lit;

        vec3 GRID = uGridColor;
        vec3 rimCol = mix(mix(PURPLE, VIOLET, fres), GRID, uTintAmount * 0.35);

        // grid: latitude rings + longitude lines + fine sub-grid
        float lat  = line(vRest.y * 7.0, 0.15);
        float lon  = line(atan(vRest.x, vRest.z + 2.2) * 26.0, 0.15);
        float fine = line(vRest.y * 28.0, 0.0) * 0.25;
        float grid = max(max(lat, lon), fine);

        float scanY = mod(uScanPhase, 11.0) - 5.5;
        float band = exp(-pow((vRest.y - scanY) / 0.16, 2.0));
        float flicker = 0.96 + 0.04 * sin(uTime * 37.0 + vRest.y * 11.0);
        // thinking shimmer: a slow soft wave of light rising from bottom to top
        float shimmer = uShimmer * 0.55 * pow(0.5 + 0.5 * sin(vRest.y * 1.4 - uTime * 1.6), 4.0);
        float power = uBrightness * (1.0 + uEnergy * 0.9 + shimmer);

        vec3 col = vec3(0.0);
        col += GRID * grid * (0.18 + 0.85 * lit) * power;                // lit grid lines
        col += mix(PURPLE, GRID, uTintAmount * 0.3) * grid * shadow * 0.55 * uBrightness;
        col += (GRID * 0.05 * lit + PURPLE * 0.10 * shadow) * uBrightness;
        col += rimCol * fres * 1.7;                                        // rim light
        col += GRID * band * (0.35 + 0.9 * grid);
        // eyes: glow follows gaze, scales with openness, dims on blink
        float eyes = eyeGlow(uEyeXL, uEyeOpen.x) + eyeGlow(uEyeXR, uEyeOpen.y);
        col += mix(GRID, vec3(1.0), 0.15) * eyes * (0.4 + 0.35 * facing) * uEyeGlow;

        // ── mouth. The opening is triangles stretched between the lips; their
        // rest-space y stays in a thin band around the seam, so distance from the
        // seam maps across the opening: 0 = deepest point, ~1 = inner lip edge.
        // Inside = solid black cavity with the neon-green grid continuing into it
        // (drawn on the DEFORMED surface so the lines stay evenly spaced as it opens).
        // Lips keep the normal face grid, plus a brighter outline so the shape reads.
        float ax   = abs(vRest.x);
        float mx   = 1.0 - smoothstep(uMouthHalfW * 0.5, uMouthHalfW * 1.2, ax);
        float mz   = smoothstep(1.4, 1.9, vRest.z);
        float open = smoothstep(0.02, 0.22, uJaw);
        float seam = abs(vRest.y - (uMouthY - 0.01)) / 0.075;
        // Stretch test for the asymmetric mouth corners: the gap triangles span the
        // opening, so they move ~5x+ more on screen than their rest (skin) coordinate
        // changes. The lips stretch only moderately as the jaw opens → they stay lips.
        float restGrad = length(vec2(dFdx(vRest.y), dFdy(vRest.y)));
        float posGrad  = max(length(vec2(dFdx(vPos.y), dFdy(vPos.y))), 1e-6);
        // corners stretch less than the middle of the opening → looser test there
        float corner   = smoothstep(uMouthHalfW * 0.55, uMouthHalfW * 0.95, ax);
        float gapLim   = mix(0.2, 0.42, corner);
        float gapTri   = 1.0 - smoothstep(gapLim * 0.45, gapLim, restGrad / posGrad);
        float mxWide   = 1.0 - smoothstep(uMouthHalfW * 1.15, uMouthHalfW * 1.6, ax);
        float nearSeam = 1.0 - smoothstep(0.9, 1.5, seam);
        float cavity = max((1.0 - smoothstep(0.5, 0.9, seam)) * mx, gapTri * mxWide * nearSeam) * mz * open;
        cavity = clamp(cavity, 0.0, 1.0);

        // interior: solid black with the neon-green grid continuing inside
        float mLat = line(vPos.y * 7.0, 0.15);
        float mLon = line(atan(vPos.x, vPos.z + 2.2) * 26.0, 0.15);
        vec3 inside = vec3(0.224, 1.0, 0.078) * max(mLat, mLon) * 0.45; // dim #39FF14 lines on solid black

        // upper side of the opening = rest y above the seam; lower side = below
        float upSide = step(uMouthY - 0.01, vRest.y);
        // faint upper teeth: a dark band just under the upper lip, only on wide opens
        float wideOpen = smoothstep(0.35, 0.75, uJaw);
        float teeth = upSide * smoothstep(0.32, 0.62, seam) * (1.0 - smoothstep(0.9, 1.0, seam))
                    * (1.0 - smoothstep(uMouthHalfW * 0.5, uMouthHalfW * 0.72, ax)) * wideOpen;
        float toothGaps = line(vPos.x * 16.0, 0.0);                      // separations between teeth
        vec3 teethCol = vec3(0.05, 0.07, 0.055) + vec3(0.224, 1.0, 0.078) * (toothGaps * 0.18 + mLat * 0.12);
        inside = mix(inside, teethCol, teeth);
        // dark tongue resting at the bottom: rounded, faint violet edge on top
        float tongueX = 1.0 - smoothstep(uMouthHalfW * 0.36, uMouthHalfW * 0.6, ax);
        float tongue = (1.0 - upSide) * smoothstep(0.18, 0.5, seam) * tongueX * smoothstep(0.15, 0.4, uJaw);
        float tongueEdge = (1.0 - upSide) * exp(-pow((seam - 0.22) / 0.07, 2.0)) * tongueX * smoothstep(0.15, 0.4, uJaw);
        inside = mix(inside, vec3(0.035, 0.0, 0.03) + vec3(0.224, 1.0, 0.078) * mLon * 0.08, tongue);
        inside += VIOLET * tongueEdge * 0.12;
        col = mix(col, inside, cavity);

        // lips: same grid as the face + a soft neon outline along the inner edge
        // (where the lips meet / part) and the outer lip line
        float lipX  = 1.0 - smoothstep(uMouthHalfW * 0.8, uMouthHalfW * 1.2, ax);
        float inner = exp(-pow((seam - 0.95) / 0.32, 2.0));
        float outer = exp(-pow((seam - 2.9) / 0.45, 2.0)) * 0.65;
        vec3 LIPLINE = mix(vec3(0.224, 1.0, 0.078), VIOLET, 0.4);
        col += LIPLINE * (inner + outer) * lipX * mz * (1.0 - cavity) * 0.5;

        // glitch: chroma split + dropout flicker on random slices
        if (uGlitch > 0.001) {
          float slice = floor(vRest.y * 9.0) + floor(uTime * 18.0) * 3.0;
          float on = step(0.75, hash(slice));
          col.r += uGlitch * on * 0.35;
          col.b += uGlitch * (1.0 - on) * 0.08 * step(0.5, hash(slice + 1.7));
          col *= 1.0 - uGlitch * 0.55 * step(0.93, hash(slice + 9.1));
        }

        col *= flicker;
        if (uDebug > 0.5) col = col * 0.6 + vec3(vJawW * 0.7, cavity, eyes * 0.5); // rig check
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  })
}
