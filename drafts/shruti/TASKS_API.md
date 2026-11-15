# Jarvis Tasks API

The task list is the glass card in the **top-right** of the Jarvis app. It shows a live
count; click it to open a stack of task cards. The UI only displays tasks — **your
code adds and updates them** through the functions below.

Code: `drafts/shruti/app/src/tasks/tasks.ts`

## How to call it

From anywhere in the page (no imports needed):

```js
window.jarvisTasks.addTask({ type: 'email', title: 'Check reply from TA Kumar' })
```

Or inside the app's code: `import { addTask, … } from './tasks/tasks'`.

## Task shape

```ts
{
  id: string,                                   // auto-generated if you don't pass one
  type: 'email' | 'calendar' | 'canvas' | 'web' | 'other',   // picks the icon
  title: string,                                // one line, shown in white
  status: 'queued' | 'running' | 'done' | 'failed',          // default 'queued'
  progress?: number,                            // 0–100; omit while running → animated "working" line
  result?: { summary: string, details?: string },            // shown when the user opens a done task
  createdAt: number                             // ms timestamp, auto-filled
}
```

- `details` keeps line breaks, so you can pass e.g.
  `"From: Ravi Kumar\nSubject: Re: Midterm regrade\n“Hi! I re-checked Q4…”"`.
- Icons: `email` = envelope, `calendar` = calendar, `canvas` = graduation cap,
  `web` = globe, `other` = sparkle.

## Functions

| Function | What it does |
|---|---|
| `addTask(task)` | Adds a task (only `type` and `title` are required). **Returns the id.** Card appears, count ticks up. |
| `updateTask(id, changes)` | Merges changes, e.g. `{ status: 'running', progress: 40 }`. |
| `completeTask(id, result?)` | Marks it **done** (green check). `result` = `{ summary, details? }`, shown when the user clicks the card. |
| `failTask(id, message)` | Marks it **failed** (red-violet) and shows `message` under the title. |
| `removeTask(id)` | Removes it from the list. **Call this when the user says "delete the X task" by voice.** If the task is still running, also stop the real work on your side. |
| `clearCompleted()` | Removes every done or failed task. |
| `getTasks()` | Returns the current list (read-only). Handy for finding a task by title. |
| `subscribe(fn)` | Calls `fn` whenever the list changes. Returns an unsubscribe function. |

Unknown ids are ignored with a console warning, never an error.

## What the user can do in the UI

- Click the count card to open or close the stack (Esc also closes it).
- **Checkbox:** marks a task complete. On a task that's already done, it checks it
  off and removes it.
- **×:** deletes. On a *running* task it first asks "Cancel this task?" with Yes / No.
  The UI only removes the card, so if you need to cancel the real work, watch for the
  task disappearing via `subscribe`.
- Click a **done** task to see its result.
- **Clear completed** at the bottom.

## Example: an email agent

```js
const t = window.jarvisTasks

const id = t.addTask({ type: 'email', title: 'Check reply from TA Kumar' })   // queued
t.updateTask(id, { status: 'running', progress: 0 })                          // working…

// … as your agent makes progress
t.updateTask(id, { progress: 60 })

// success
t.completeTask(id, {
  summary: 'TA Kumar replied — your Q4 regrade was accepted.',
  details: 'From: Ravi Kumar (TA, CSE 340)\nSubject: Re: Midterm regrade request\n“Hi! I re-checked Q4…”',
})

// …or failure
// t.failTask(id, 'Could not reach the inbox — try again later.')
```

Voice "delete the exams task":

```js
const task = window.jarvisTasks.getTasks().find((x) => x.title.toLowerCase().includes('exam'))
if (task) window.jarvisTasks.removeTask(task.id)
```

## Try it

Run the app (`cd drafts/shruti/app && npm run dev`) and press **T**. Five mock tasks
run in parallel: email, canvas and calendar finish, web fails, and the lecture-notes
summary keeps running for a while, then finishes. Press **T** again to reset.
