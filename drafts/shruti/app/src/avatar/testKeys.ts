// Hidden keyboard test hook — no on-screen UI. Keys are documented in README.md.
//   1–9, 0  expressions (smile, laugh, angry, sad, surprised, confused, excited, wink, glitch, power_up)
//   C       clear expression
//   ← → ↑ ↓ lookAt left/right/up/down    U = user   H = shelf
//   N / S / T  nod / shake / tilt
//   Q / W / E / R  base state idle / listening / thinking / speaking
import type { Avatar3DHandle } from './Avatar3D'
import type { BaseState, ExpressionName } from './expressions'

const EXPR_KEYS: ExpressionName[] = ['smile', 'laugh', 'angry', 'sad', 'surprised', 'confused', 'excited', 'wink', 'glitch', 'power_up']
const STATE_KEYS: Record<string, BaseState> = { KeyQ: 'idle', KeyW: 'listening', KeyE: 'thinking', KeyR: 'speaking' }
const LOOK_KEYS: Record<string, string> = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down', KeyU: 'user', KeyH: 'shelf' }
const GESTURE_KEYS: Record<string, string> = { KeyN: 'nod', KeyS: 'shake', KeyT: 'tilt' }

export function installTestKeys(getAvatar: () => Avatar3DHandle | null) {
  const onKey = (e: KeyboardEvent) => {
    if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return
    const a = getAvatar()
    if (!a) return
    const digit = e.code.startsWith('Digit') ? Number(e.code.slice(5)) : NaN
    if (!Number.isNaN(digit)) {
      a.setExpression({ name: EXPR_KEYS[digit === 0 ? 9 : digit - 1] })
    } else if (e.code === 'KeyC') a.clearExpression()
    else if (STATE_KEYS[e.code]) a.setState(STATE_KEYS[e.code])
    else if (LOOK_KEYS[e.code]) a.lookAt({ target: LOOK_KEYS[e.code] })
    else if (GESTURE_KEYS[e.code]) a.playGesture({ name: GESTURE_KEYS[e.code] })
    else return
    e.preventDefault()
  }
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}
