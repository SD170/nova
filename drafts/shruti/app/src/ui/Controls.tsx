import type { AvatarState } from '../avatar/Avatar3D'

/** Subtle hint at the bottom; fades out after a few seconds of idle. */
export function Hint({ visible }: { visible: boolean }) {
  return <div className={`hint ${visible ? '' : 'hint--hidden'}`}>Hold SPACE to talk</div>
}

/** Big top-center badge while SPACE is held — so the user knows mic is open. */
export function ListeningBadge({ visible }: { visible: boolean }) {
  return (
    <div className={`listening-badge ${visible ? '' : 'listening-badge--hidden'}`}>
      <span className="listening-badge__dot" />
      Listening
    </div>
  )
}

/** Hidden debug panel (press D): force each state for testing. Off by default. */
export function DevPanel({
  state,
  onState,
  onSpeakSample,
}: {
  state: AvatarState
  onState: (s: AvatarState) => void
  onSpeakSample: () => void
}) {
  const states: AvatarState[] = ['idle', 'listening', 'thinking']
  const noFocus = (e: React.MouseEvent) => e.preventDefault() // keep SPACE for push-to-talk
  return (
    <div className="dev-panel">
      {states.map((s) => (
        <button key={s} className={s === state ? 'on' : ''} onClick={() => onState(s)} onMouseDown={noFocus} tabIndex={-1}>
          {s}
        </button>
      ))}
      <button className={state === 'speaking' ? 'on' : ''} onClick={onSpeakSample} onMouseDown={noFocus} tabIndex={-1}>
        speaking ▶
      </button>
    </div>
  )
}
