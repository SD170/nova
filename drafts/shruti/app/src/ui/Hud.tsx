// Hologram-projector HUD: violet corner brackets, a tiny status line, and a very
// faint scanline texture. Decorative only (no pointer events).
import { useSyncExternalStore } from 'react'
import { getTasks, subscribe } from '../tasks/tasks'

export function Hud() {
  const tasks = useSyncExternalStore(subscribe, getTasks)
  const running = tasks.filter((t) => t.status === 'running').length
  return (
    <div className="hud" aria-hidden="true">
      <div className="hud-scanlines" />
      <span className="hud-corner hud-corner--tl" />
      <span className="hud-corner hud-corner--tr" />
      <span className="hud-corner hud-corner--bl" />
      <span className="hud-corner hud-corner--br" />
      <div className="hud-status">
        NOVA · <span className="hud-online">ONLINE</span> ·{' '}
        <span className={running ? 'hud-agents hud-agents--on' : 'hud-agents'}>{running}</span> AGENTS ACTIVE
      </div>
    </div>
  )
}
