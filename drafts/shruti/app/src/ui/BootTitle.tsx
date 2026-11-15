// "NOVA" typed in letter by letter during the boot sequence, then fades out.
// Timing follows presence.ts (same clock as the 3D scanline), so the letters land
// right after the eyes ignite even if the 3D model took a moment to load.
import { useEffect, useState } from 'react'
import { presence } from '../avatar/presence'

const NAME = 'NOVA'
const LETTER_MS = 130

export function BootTitle() {
  const [letters, setLetters] = useState(0)
  const [fading, setFading] = useState(false)
  const [gone, setGone] = useState(presence.mode !== 'boot')

  useEffect(() => {
    if (gone) return
    let raf = 0
    const tick = () => {
      if (presence.mode !== 'boot') {
        setGone(true) // finished or skipped (SPACE)
        return
      }
      const { textStart, textEnd } = presence.bootText
      const t = presence.time
      setLetters(Math.max(0, Math.min(NAME.length, Math.floor(((t - textStart) * 1000) / LETTER_MS) + 1)))
      setFading(t >= textEnd)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [gone])

  if (gone) return null
  return (
    <div className={`boot-title ${fading ? 'boot-title--out' : ''}`} aria-label={NAME}>
      {NAME.split('').map((ch, i) => (
        <span key={i} className={i < letters ? 'on' : ''}>
          {ch}
        </span>
      ))}
      {letters > 0 && <span className={`boot-caret ${letters >= NAME.length ? 'boot-caret--done' : ''}`} />}
    </div>
  )
}
