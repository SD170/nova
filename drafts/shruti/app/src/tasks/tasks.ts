// ─────────────────────────────────────────────────────────────────────────────
// tasks.ts — the task list shown in the top-right glass card.
//
// UI only: the UI renders whatever is in this store. Teammates (orchestrator /
// agents) push real tasks in by calling the functions below, either by importing
// them or from anywhere in the page via `window.jarvisTasks`:
//
//   const id = jarvisTasks.addTask({ type: 'email', title: 'Check reply from TA Kumar' })
//   jarvisTasks.updateTask(id, { status: 'running', progress: 40 })
//   jarvisTasks.completeTask(id, { summary: 'TA replied', details: 'From: …' })
//   jarvisTasks.failTask(id, 'Inbox not reachable')
//   jarvisTasks.removeTask(id)
//   jarvisTasks.clearCompleted()
//
// Full guide for teammates: drafts/shruti/TASKS_API.md
// ─────────────────────────────────────────────────────────────────────────────

export type TaskType = 'email' | 'calendar' | 'canvas' | 'web' | 'other'
export type TaskStatus = 'queued' | 'running' | 'done' | 'failed'

export interface TaskResult {
  /** one line shown when the task is opened (or the error message when failed) */
  summary: string
  /** optional extra lines, e.g. "From: …\nSubject: …\n<preview>" — newlines are kept */
  details?: string
}

export interface Task {
  id: string
  type: TaskType
  title: string
  status: TaskStatus
  /** 0–100. Omit while running to show an indeterminate progress line. */
  progress?: number
  result?: TaskResult
  /** ms since epoch */
  createdAt: number
}

/** What callers pass to addTask — only type + title are required. */
export type NewTask = Pick<Task, 'type' | 'title'> & Partial<Omit<Task, 'type' | 'title'>>

// ── store (tiny observable, no dependencies) ─────────────────────────────────

let tasks: Task[] = []
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())
const set = (next: Task[]) => {
  tasks = next
  emit()
}

/** Subscribe to changes. Returns an unsubscribe function. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Current list, oldest first. Treat as read-only. */
export function getTasks(): readonly Task[] {
  return tasks
}

// ── API ──────────────────────────────────────────────────────────────────────

let counter = 0

/** Add a task. Missing fields get defaults (id, status 'queued', createdAt now). Returns the id. */
export function addTask(task: NewTask): string {
  const id = task.id ?? `task_${Date.now().toString(36)}_${(counter++).toString(36)}`
  if (tasks.some((t) => t.id === id)) {
    console.warn(`[tasks] addTask: id "${id}" already exists — updating instead`)
    updateTask(id, task)
    return id
  }
  set([...tasks, { status: 'queued', createdAt: Date.now(), ...task, id }])
  return id
}

/** Merge changes into a task (e.g. { status: 'running', progress: 40 }). Unknown ids are ignored. */
export function updateTask(id: string, changes: Partial<Omit<Task, 'id'>>): void {
  if (!tasks.some((t) => t.id === id)) return warn('updateTask', id)
  set(tasks.map((t) => (t.id === id ? { ...t, ...changes } : t)))
}

/** Mark a task done, optionally with its result (shown when the user opens the card). */
export function completeTask(id: string, result?: TaskResult): void {
  if (!tasks.some((t) => t.id === id)) return warn('completeTask', id)
  set(tasks.map((t) => (t.id === id ? { ...t, status: 'done', progress: 100, result: result ?? t.result } : t)))
}

/** Mark a task failed; `message` is shown under the title. */
export function failTask(id: string, message: string): void {
  if (!tasks.some((t) => t.id === id)) return warn('failTask', id)
  set(tasks.map((t) => (t.id === id ? { ...t, status: 'failed', result: { summary: message } } : t)))
}

/**
 * Remove a task from the list (any status).
 * Teammates: call this when the user says 'delete the X task' by voice.
 * (Find the id with getTasks().find(t => t.title.toLowerCase().includes('x')).)
 * If the task is still running, your agent should also stop the actual work.
 */
export function removeTask(id: string): void {
  if (!tasks.some((t) => t.id === id)) return warn('removeTask', id)
  set(tasks.filter((t) => t.id !== id))
}

/** Remove every task that is done or failed. */
export function clearCompleted(): void {
  set(tasks.filter((t) => t.status !== 'done' && t.status !== 'failed'))
}

/** Remove everything (used by demo reset). */
export function clearAll(): void {
  set([])
}

function warn(fn: string, id: string) {
  console.warn(`[tasks] ${fn}: no task with id "${id}" — ignored`)
}

export const tasksApi = { addTask, updateTask, completeTask, failTask, removeTask, clearCompleted, getTasks, subscribe }

declare global {
  interface Window {
    /** Task API for teammates — see drafts/shruti/TASKS_API.md */
    jarvisTasks: typeof tasksApi
  }
}
window.jarvisTasks = tasksApi
