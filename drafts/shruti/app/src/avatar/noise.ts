// Smooth 1D gradient noise (Perlin-style). Gives organic, non-repeating head
// motion instead of sine loops. Output roughly in [-1, 1].
const PERM = new Uint8Array(512)
{
  const p = Array.from({ length: 256 }, (_, i) => i)
  let seed = 1337
  for (let i = 255; i > 0; i--) {
    seed = (seed * 16807) % 2147483647
    const j = seed % (i + 1)
    ;[p[i], p[j]] = [p[j], p[i]]
  }
  for (let i = 0; i < 512; i++) PERM[i] = p[i & 255]
}

const grad = (h: number, x: number) => ((h & 1) === 0 ? x : -x) * (1 + (h & 7) / 8)
const fade = (t: number) => t * t * t * (t * (t * 6 - 15) + 10)

export function noise1(x: number): number {
  const i = Math.floor(x)
  const f = x - i
  const a = grad(PERM[i & 255], f)
  const b = grad(PERM[(i + 1) & 255], f - 1)
  return (a + (b - a) * fade(f)) * 1.6
}

/** Two octaves — slow drift plus a little finer movement. */
export function fbm(x: number): number {
  return noise1(x) * 0.7 + noise1(x * 2.13 + 19.1) * 0.3
}
