// Shapes returned by the Nova workspace service (apps/google-agent): GET /panel/summary,
// GET /panel/feed and the /quiz/* routes. Display-ready: short course codes, spoken-style times.

export interface DueItem { id: string; course: string; title: string; due: string; points: number | null; type: string; source_url: string }
export interface CalEvent { id: string; title: string; when: string; calendar: string }
export interface MailItem { id: string; from: string; subject: string; snippet: string; category: string; important: boolean; needs_reply: boolean; unread: boolean; when: string }
export interface Story { id: string; title: string; source: string; topic: string; outlets: number; confirmed: boolean; published: string; url: string }
export interface Person { name: string; headline: string; why: string; action: string; url: string }
export interface CourseRow { id: string; code: string; name: string; exam: { name: string; date: string } | null }
export interface MemoryDoc { id: string; text: string; kind: string; created_at: string }

export type Section<T> = ({ ok: true } & T) | { ok: false; error: string }

export interface SavedFile {
  id: string; title: string; filename: string; format: string; kind: 'quiz_cards' | 'document'
  course: string; download_url: string; saved_path: string | null; size_bytes: number; created_at: string; when: string
}

export interface QuizQuestion { index: number; q: string; options: string[]; topic: string; chosen: number | null }
export interface QuizReview { index: number; correct: boolean; answer: number; chosen: number | null; explanation: string; source: string }
export interface QuizView {
  id: string; course_code: string; title: string; status: 'ready' | 'in_progress' | 'done'; mode: 'voice' | 'panel' | null
  total: number; answered: number; questions: QuizQuestion[]; score: number | null; review: QuizReview[] | null
  pdf_status: string; saved_path: string | null; data_source: string
}

export interface Summary {
  today: Section<{ due: DueItem[]; count: number; events: CalEvent[] }>
  mail: Section<{ total: number; important_count: number; needs_reply_count: number; emails: MailItem[] }>
  courses: Section<{ courses: CourseRow[] }>
  news: Section<{ stories: Story[] }>
  linkedin: Section<{ posts_seen: number; engaged_posts: number; people: Person[]; companies: string[]; interests: string[] }>
  memory: Section<{ enabled: boolean; facts: string[]; recent: MemoryDoc[] }>
  saved: SavedFile[]
  quiz: QuizView | null
  data_source: string
  generated_at: string
}

export interface FeedEvent { id: number; at: string; kind: string; title: string; detail: string; data: Record<string, unknown> }

export type TabId = 'today' | 'mail' | 'courses' | 'news' | 'linkedin' | 'saved' | 'memory'

export interface Toast { id: number; kind: string; title: string; detail: string; tone: 'info' | 'good' | 'bad'; file?: { id: string; path: string | null }; quizId?: string }
