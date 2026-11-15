// Demo mode (press T): five MOCK tasks that run in parallel and finish at
// different times. Press T again to reset. Mock data only — not real accounts.
import { addTask, clearAll, completeTask, failTask, updateTask } from './tasks'

let timers: number[] = []
let running = false

const at = (ms: number, fn: () => void) => timers.push(window.setTimeout(fn, ms))

/** Animate progress from `from` to `to` over `ms`. */
function progress(id: string, from: number, to: number, startMs: number, ms: number, steps = 12) {
  for (let i = 1; i <= steps; i++) {
    at(startMs + (ms * i) / steps, () => updateTask(id, { progress: Math.round(from + ((to - from) * i) / steps) }))
  }
}

export function toggleDemo() {
  if (running) return resetDemo()
  running = true

  // 1. Email → done with a result
  at(0, () => {
    const id = addTask({ id: 'demo_email', type: 'email', title: 'Check reply from TA Kumar' })
    at(500, () => updateTask(id, { status: 'running', progress: 0 }))
    progress(id, 0, 100, 500, 3400)
    at(4100, () =>
      completeTask(id, {
        summary: 'TA Kumar replied — your Q4 regrade was accepted.',
        details:
          'From: Ravi Kumar (TA, CSE 340)\nSubject: Re: Midterm regrade request\n“Hi! I re-checked Q4 and you’ll get the 3 points back. Office hours move to Thu 3 PM this week.”',
      }),
    )
  })

  // 2. Canvas → done
  at(350, () => {
    const id = addTask({ id: 'demo_canvas', type: 'canvas', title: 'Find upcoming exams' })
    at(400, () => updateTask(id, { status: 'running', progress: 0 }))
    progress(id, 0, 100, 400, 5000)
    at(5600, () =>
      completeTask(id, {
        summary: '2 exams in the next 7 days.',
        details: 'EEE 203 Midterm 2 — Mon, Nov 16 · 10:30 AM\nCSE 340 Quiz 4 — Wed, Nov 18 · 9:00 AM',
      }),
    )
  })

  // 3. Calendar → done
  at(700, () => {
    const id = addTask({ id: 'demo_calendar', type: 'calendar', title: 'Find free study slots this week' })
    at(900, () => updateTask(id, { status: 'running' })) // indeterminate for a bit…
    at(3000, () => updateTask(id, { progress: 35 }))
    progress(id, 35, 100, 3000, 3600)
    at(6900, () =>
      completeTask(id, {
        summary: '3 free 2-hour slots found.',
        details: 'Sun 2–4 PM · Mon 6–8 PM · Wed 1–3 PM',
      }),
    )
  })

  // 4. Web → failed
  at(1050, () => {
    const id = addTask({ id: 'demo_web', type: 'web', title: 'ASU events this weekend' })
    at(1300, () => updateTask(id, { status: 'running' }))
    at(5200, () => failTask(id, 'Couldn’t reach the events page — try again later.'))
  })

  // 5. Other → runs for a while, then done
  at(1400, () => {
    const id = addTask({ id: 'demo_other', type: 'other', title: 'Summarize CSE 340 lecture notes' })
    at(1900, () => updateTask(id, { status: 'running', progress: 0 }))
    progress(id, 0, 72, 1900, 9000, 18)
    progress(id, 72, 100, 11200, 3800, 8)
    at(15300, () =>
      completeTask(id, {
        summary: 'Lecture 12 summarized in 5 key points.',
        details:
          '1. LR(0) items & closure\n2. Building the canonical collection\n3. Shift/reduce conflicts\n4. SLR uses FOLLOW sets to resolve them\n5. Next class: LALR(1)',
      }),
    )
  })
}

export function resetDemo() {
  timers.forEach((t) => clearTimeout(t))
  timers = []
  running = false
  clearAll()
}
