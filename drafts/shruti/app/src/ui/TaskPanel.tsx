// Task UI (top-right): a frosted-glass count card that opens into a stack of
// task cards. Data comes from src/tasks/tasks.ts — this file only renders it.
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { clearCompleted, completeTask, getTasks, removeTask, subscribe, type Task, type TaskType } from '../tasks/tasks'

// buttons never take focus → SPACE always stays push-to-talk
const noFocus = (e: React.MouseEvent) => e.preventDefault()

/** Glass depth: tilt toward the cursor (max ~7°), sheen follows it, lift on hover. */
const tilt = {
  onMouseMove(e: React.MouseEvent<HTMLElement>) {
    const el = e.currentTarget
    const r = el.getBoundingClientRect()
    const nx = (e.clientX - r.left) / r.width - 0.5 // -0.5 … 0.5
    const ny = (e.clientY - r.top) / r.height - 0.5
    el.style.setProperty('--ry', `${(nx * 14).toFixed(2)}deg`)
    el.style.setProperty('--rx', `${(-ny * 12).toFixed(2)}deg`)
    el.style.setProperty('--mx', `${((nx + 0.5) * 100).toFixed(1)}%`)
    el.style.setProperty('--my', `${((ny + 0.5) * 100).toFixed(1)}%`)
  },
  onMouseLeave(e: React.MouseEvent<HTMLElement>) {
    const el = e.currentTarget
    el.style.setProperty('--rx', '0deg')
    el.style.setProperty('--ry', '0deg')
  },
}

export function TaskPanel() {
  const tasks = useSyncExternalStore(subscribe, getTasks)
  const [open, setOpen] = useState(false)
  const [bump, setBump] = useState(0) // re-triggers the "count ticked up" glow
  const prevCount = useRef(tasks.length)

  useEffect(() => {
    if (tasks.length > prevCount.current) setBump((b) => b + 1)
    prevCount.current = tasks.length
    if (tasks.length === 0) setOpen(false)
  }, [tasks.length])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const n = tasks.length
  const anyRunning = tasks.some((t) => t.status === 'running')
  const anyFinished = tasks.some((t) => t.status === 'done' || t.status === 'failed')

  return (
    <div className="tasks">
      <button
        className={`glass glass--depth task-head ${n === 0 ? 'task-head--empty' : ''} ${open ? 'task-head--open' : ''}`}
        {...tilt}
        onClick={() => n > 0 && setOpen((o) => !o)}
        onMouseDown={noFocus}
        tabIndex={-1}
        aria-expanded={open}
      >
        <span className="glass-sweep" />
        <span className={`task-dot ${anyRunning ? 'task-dot--live' : ''}`} />
        {n === 0 ? (
          <span>No active tasks</span>
        ) : (
          <span>
            <span key={bump} className={bump ? 'task-count task-count--bump' : 'task-count'}>
              {n}
            </span>{' '}
            {n === 1 ? 'task' : 'tasks'}
          </span>
        )}
        {n > 0 && <Chevron open={open} />}
      </button>

      {open && (
        <div className="task-stack">
          <div className="task-scroll">
            {tasks.map((t, i) => (
              <TaskCard key={t.id} task={t} index={i} />
            ))}
          </div>
          {anyFinished && (
            <button className="task-clear" onClick={clearCompleted} onMouseDown={noFocus} tabIndex={-1} style={{ animationDelay: `${tasks.length * 60}ms` }}>
              Clear completed
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function TaskCard({ task, index }: { task: Task; index: number }) {
  const [confirming, setConfirming] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const done = task.status === 'done'
  const failed = task.status === 'failed'
  const running = task.status === 'running'

  // fade out, then remove from the store
  const leave = () => {
    setLeaving(true)
    window.setTimeout(() => removeTask(task.id), 220)
  }
  const onCheck = () => (done ? leave() : completeTask(task.id)) // check off a done task, or mark complete
  const onDelete = () => (running ? setConfirming(true) : leave())

  return (
    <div
      className={`glass glass--depth task-card task-card--${task.status} ${leaving ? 'task-card--leaving' : ''} ${expanded ? 'task-card--expanded' : ''}`}
      style={{ animationDelay: `${index * 60}ms`, ['--sweep-delay' as string]: `${index * 60 + 180}ms` }}
      {...tilt}
    >
      <span className="glass-sweep" />
      <div className="task-row">
        <span className="task-icon">
          <TaskIcon type={task.type} />
        </span>
        <button
          className="task-main"
          onClick={() => (done || failed) && task.result && setExpanded((x) => !x)}
          onMouseDown={noFocus}
          tabIndex={-1}
          style={{ cursor: (done || failed) && task.result ? 'pointer' : 'default' }}
        >
          <span className="task-title">{task.title}</span>
          <span className={`task-status task-status--${task.status}`}>
            {done && <CheckIcon />}
            {task.status === 'queued' && 'Queued'}
            {running && `Working…${task.progress != null ? ` ${Math.round(task.progress)}%` : ''}`}
            {done && 'Done'}
            {failed && 'Failed'}
          </span>
        </button>
        {!confirming && (
          <span className="task-actions">
            <button className={`task-check ${done ? 'task-check--on' : ''}`} onClick={onCheck} onMouseDown={noFocus} tabIndex={-1} aria-label={done ? 'Check off' : 'Mark complete'}>
              {done && <CheckIcon />}
            </button>
            <button className="task-x" onClick={onDelete} onMouseDown={noFocus} tabIndex={-1} aria-label="Delete task">
              <svg viewBox="0 0 16 16" width="12" height="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                <path d="M4 4l8 8M12 4l-8 8" />
              </svg>
            </button>
          </span>
        )}
      </div>

      {confirming && (
        <div className="task-confirm">
          <span>Cancel this task?</span>
          <button onClick={leave} onMouseDown={noFocus} tabIndex={-1}>
            Yes
          </button>
          <button onClick={() => setConfirming(false)} onMouseDown={noFocus} tabIndex={-1}>
            No
          </button>
        </div>
      )}

      {/* failed: always show the reason; done: result opens on click */}
      {failed && task.result && <div className="task-error">{task.result.summary}</div>}
      <div className={`task-result ${expanded && done ? 'task-result--open' : ''}`}>
        {task.result && (
          <div>
            <div className="task-summary">{task.result.summary}</div>
            {task.result.details && <div className="task-details">{task.result.details}</div>}
          </div>
        )}
      </div>

      {running && (
        <span className="task-progress">
          <span
            className={task.progress == null ? 'task-progress-bar task-progress-bar--indeterminate' : 'task-progress-bar'}
            style={task.progress == null ? undefined : { width: `${Math.max(3, task.progress)}%` }}
          />
        </span>
      )}
    </div>
  )
}

// ── icons (thin line, currentColor) ──────────────────────────────────────────

function TaskIcon({ type }: { type: TaskType }) {
  const p = { viewBox: '0 0 24 24', width: 18, height: 18, fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  switch (type) {
    case 'email':
      return (
        <svg {...p}>
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M3.5 6.5l8.5 6.5 8.5-6.5" />
        </svg>
      )
    case 'calendar':
      return (
        <svg {...p}>
          <rect x="3.5" y="5" width="17" height="15" rx="2" />
          <path d="M3.5 9.5h17M8 3v4M16 3v4" />
          <path d="M8 13h2M12 13h2M8 16.5h2" />
        </svg>
      )
    case 'canvas':
      return (
        <svg {...p}>
          <path d="M2.5 9.5L12 5l9.5 4.5L12 14z" />
          <path d="M6.5 11.5v4.2c0 1.3 2.5 2.8 5.5 2.8s5.5-1.5 5.5-2.8v-4.2" />
          <path d="M21.5 9.5v5" />
        </svg>
      )
    case 'web':
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M3.5 12h17M12 3.5c2.4 2.4 3.6 5.2 3.6 8.5s-1.2 6.1-3.6 8.5M12 3.5C9.6 5.9 8.4 8.7 8.4 12s1.2 6.1 3.6 8.5" />
        </svg>
      )
    default:
      return (
        <svg {...p}>
          <path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9z" />
          <path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
        </svg>
      )
  }
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3.5 8.5l3 3 6-7" />
    </svg>
  )
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg className={`task-chevron ${open ? 'task-chevron--open' : ''}`} viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M4 6l4 4 4-4" />
    </svg>
  )
}
