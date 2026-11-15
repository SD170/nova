/**
 * newsTools.ts — drop-in client for Amrita's news + ASU events service (port 9004).
 *
 * News is TODAY's news by default (since midnight in the student's own timezone), newest first.
 *
 * Copy this file into the UI (e.g. src/tools/newsTools.ts). No dependencies; works in
 * the browser, Electron and Node 18+. Every function returns LIVE data from the service.
 *
 *   import { fetchNews, fetchAsuEvents, watchNews } from './tools/newsTools'
 *
 *   const news = await fetchNews('world, Phoenix Suns, AI policy', { live: true })
 *   news.links            // every article URL
 *   news.items[0].title   // headline, source, published_at, confirmed, url ...
 *
 *   const stop = watchNews('tech, sports', (news) => render(news.items))   // auto-refreshes
 *
 * Config (Vite env, optional):
 *   VITE_NEWS_BASE=http://localhost:9004     (or the Cloudflare tunnel URL from shared.env)
 *   VITE_NEWS_KEY=...                        (only if the service has NEWS_AGENT_API_KEY set)
 * or call configureNewsTools({ baseUrl, apiKey }) once at startup.
 */

// ───────────────────────── response types (match app/models.py) ─────────────────────────

export interface NewsItem {
  id: string
  title: string
  url: string // original article — always link to it
  source: string // outlet, e.g. "NPR"
  published_at: string | null // UTC ISO-8601
  topic: string // which requested topic it belongs to
  age_minutes: number | null // minutes since published (at generated_at) — show "12 min ago"
  outlets: number // independent newsrooms reporting this story
  confirmed: boolean // true when 2+ outlets report it
  also_reported_by: { source: string; url: string }[]
  summary: string
  trusted: boolean
  data_source: 'live' | 'demo'
}

export interface TopicStatus {
  topic: string
  kind: string
  ok: boolean // false = that source failed right now (nothing is made up)
  count: number
  providers: string[]
}

export interface NewsResult {
  generated_at: string // when this data was fetched (UTC)
  topics: string[]
  since_hours: number // hours the window covers
  window: string // "today (2026-11-15)" | "last N hours"
  window_start: string // UTC ISO — nothing older than this is returned
  trusted_only: boolean
  data_source: 'live' | 'demo'
  count: number
  links: string[]
  items: NewsItem[] // newest first within each topic
  by_topic: TopicStatus[]
  speak: string // one-sentence summary for TTS
}

export interface NewsItemDetail extends NewsItem {
  text: string // article text when the publisher allows it
  text_available: boolean
  text_note: string
}

export interface Topic {
  id: string // pass this to fetchNews
  label: string
  kind: 'section' | 'custom'
  outlets: string[]
}

export interface TopicsResult {
  sections: Topic[]
  custom_topics: string
  examples: string[]
}

export interface AsuEvent {
  id: string
  title: string
  starts_at: string // UTC ISO-8601
  ends_at: string | null
  when_text: string
  campus: string
  location: string
  host: string
  category: string
  interests: string[]
  cost: string
  summary: string
  url: string // event page
  rsvp_url: string | null
  source: 'ASU Events' | 'Sun Devil Central'
  data_source: 'live' | 'demo'
}

export interface EventsResult {
  generated_at: string
  days: number
  query: string
  campus: string
  data_source: 'live' | 'demo'
  count: number
  links: string[]
  items: AsuEvent[]
  sources: { source: string; ok: boolean; count: number }[]
  speak: string
}

export interface DedupeCluster {
  lead_id: string
  ids: string[]
  sources: string[]
  outlets: number
  confirmed: boolean
}

export interface NewsHealth {
  ok: boolean
  data_source: 'live' | 'demo'
  tools: string[]
  keyed_sources: Record<string, boolean>
  cached_stories: number
  push_subscribers: number
  auth_required: boolean
}

// ───────────────────────── options ─────────────────────────

export interface FetchNewsOptions {
  /** true = fetched right now (at most 60 s old). false = may be up to 15 min old, but instant. Default true. */
  live?: boolean
  /** Leave unset for TODAY's news (since the student's local midnight). Set 1–72 for a rolling "last N hours". */
  sinceHours?: number
  /** Student's UTC offset in minutes (Arizona = -420). Default: this device's timezone. */
  tzOffsetMinutes?: number
  /** Only established newsrooms. Default true. */
  trustedOnly?: boolean
  /** Max stories per topic (1–15). Default 5. */
  perTopic?: number
  signal?: AbortSignal
}

export interface FetchEventsOptions {
  /** Days ahead to look (1–60). Default 7. */
  days?: number
  /** Keywords, e.g. "career fair", "free food". */
  query?: string
  /** Tempe, Downtown Phoenix, West, Polytechnic, Online. */
  campus?: string
  /** Max events (1–100). Default 25. */
  limit?: number
  /** true = re-read ASU's feeds now (at most 60 s old). Default true. */
  live?: boolean
  signal?: AbortSignal
}

// ───────────────────────── config ─────────────────────────

const env: Record<string, string | undefined> =
  (typeof import.meta !== 'undefined' && (import.meta as unknown as { env?: Record<string, string> }).env) || {}

let config = {
  baseUrl: (env.VITE_NEWS_BASE || 'http://localhost:9004').replace(/\/+$/, ''),
  apiKey: env.VITE_NEWS_KEY || '',
  timeoutMs: 20_000,
}

export function configureNewsTools(opts: Partial<typeof config>): void {
  config = { ...config, ...opts, baseUrl: (opts.baseUrl ?? config.baseUrl).replace(/\/+$/, '') }
}

export class NewsToolError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'NewsToolError'
  }
}

/** "world, Phoenix Suns" or ["world", "Phoenix Suns"] -> "world,Phoenix Suns" */
export function topicsToString(topics: string | string[]): string {
  const list = Array.isArray(topics) ? topics : topics.split(',')
  return list.map((t) => t.trim()).filter(Boolean).join(',')
}

/** This device's UTC offset in minutes (Arizona -> -420), so "today" matches the student's clock. */
export function deviceTzOffsetMinutes(): number {
  return -new Date().getTimezoneOffset()
}

async function request<T>(path: string, init: RequestInit & { signal?: AbortSignal } = {}): Promise<T> {
  const timeout = new AbortController()
  const timer = setTimeout(() => timeout.abort(), config.timeoutMs)
  init.signal?.addEventListener('abort', () => timeout.abort())
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (init.body) headers['Content-Type'] = 'application/json'
  if (config.apiKey) headers['X-Jarvis-Key'] = config.apiKey
  try {
    const res = await fetch(config.baseUrl + path, { ...init, headers, signal: timeout.signal })
    if (!res.ok) {
      let detail = res.statusText
      try {
        detail = (await res.json()).detail ?? detail
      } catch {
        /* not JSON */
      }
      throw new NewsToolError(res.status, String(detail))
    }
    return (await res.json()) as T
  } catch (e) {
    if (e instanceof NewsToolError) throw e
    if (timeout.signal.aborted && !init.signal?.aborted)
      throw new NewsToolError(504, `news service timed out (${config.baseUrl})`)
    throw new NewsToolError(0, `news service unreachable at ${config.baseUrl} — is it running on :9004?`)
  } finally {
    clearTimeout(timer)
  }
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

// ───────────────────────── the tools ─────────────────────────

/** Tool `fetch_news`: today's news for comma-separated topics, with links. */
export function fetchNews(topics: string | string[], opts: FetchNewsOptions = {}): Promise<NewsResult> {
  const t = topicsToString(topics)
  if (!t) return Promise.reject(new NewsToolError(422, 'topics is required, e.g. "world, Phoenix Suns, AI"'))
  return request<NewsResult>(
    '/news' +
      qs({
        topics: t,
        live: opts.live ?? true,
        since_hours: opts.sinceHours,
        tz_offset_minutes: opts.tzOffsetMinutes ?? deviceTzOffsetMinutes(),
        trusted_only: opts.trustedOnly,
        per_topic: opts.perTopic,
      }),
    { signal: opts.signal },
  )
}

/** Tool `fetch_asu_events`: upcoming ASU events (official calendar + Sun Devil Central). */
export function fetchAsuEvents(opts: FetchEventsOptions = {}): Promise<EventsResult> {
  return request<EventsResult>(
    '/events' +
      qs({ days: opts.days, query: opts.query, campus: opts.campus, limit: opts.limit, live: opts.live ?? true }),
    { signal: opts.signal },
  )
}

/** Tool `get_available_topics`: sections the UI can offer as chips (custom text topics also work). */
export function getAvailableTopics(signal?: AbortSignal): Promise<TopicsResult> {
  return request<TopicsResult>('/topics', { signal })
}

/** Tool `get_news_item`: one story + article text. `id` comes from a fetchNews item. */
export function getNewsItem(id: string, signal?: AbortSignal): Promise<NewsItemDetail> {
  return request<NewsItemDetail>(`/news/item/${encodeURIComponent(id)}`, { signal })
}

/** Tool `dedupe_news`: group the same story from different outlets. */
export type DedupeInput = Pick<NewsItem, 'id' | 'title'> & Partial<Pick<NewsItem, 'source' | 'url' | 'published_at'>>

export async function dedupeNews(items: DedupeInput[], signal?: AbortSignal): Promise<DedupeCluster[]> {
  const out = await request<{ clusters: DedupeCluster[] }>('/news/dedupe', {
    method: 'POST',
    body: JSON.stringify(items),
    signal,
  })
  return out.clusters
}

/** Tool `get_news_health`: is the service up, which keyed sources are on. */
export function getNewsHealth(signal?: AbortSignal): Promise<NewsHealth> {
  return request<NewsHealth>('/health', { signal })
}

// ───────────────────────── live updates ─────────────────────────

export interface WatchOptions extends Omit<FetchNewsOptions, 'signal' | 'live'> {
  /** How often to refresh, ms. Default 60 000 (the service never returns data older than 60 s in live mode). */
  intervalMs?: number
  onError?: (err: NewsToolError) => void
  /** Called with only the stories that weren't in the previous update (for "new story" toasts). */
  onNewStories?: (items: NewsItem[]) => void
}

/**
 * Keep a news view live: fetches now, then every `intervalMs`, and again when the tab/window
 * becomes visible. Returns a stop() function — call it on unmount.
 */
export function watchNews(
  topics: string | string[],
  onUpdate: (news: NewsResult) => void,
  opts: WatchOptions = {},
): () => void {
  const { intervalMs = 60_000, onError, onNewStories, ...fetchOpts } = opts
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let inflight: AbortController | undefined
  let seen: Set<string> | undefined

  const tick = async () => {
    if (stopped) return
    clearTimeout(timer)
    inflight?.abort()
    inflight = new AbortController()
    try {
      const news = await fetchNews(topics, { ...fetchOpts, live: true, signal: inflight.signal })
      if (stopped) return
      if (seen && onNewStories) {
        const fresh = news.items.filter((i) => !seen!.has(i.id))
        if (fresh.length) onNewStories(fresh)
      }
      seen = new Set(news.items.map((i) => i.id))
      onUpdate(news)
    } catch (e) {
      if (!stopped && onError) onError(e as NewsToolError)
    } finally {
      if (!stopped) timer = setTimeout(tick, intervalMs)
    }
  }

  const onVisible = () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'visible') void tick()
  }
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible)
  void tick()

  return () => {
    stopped = true
    clearTimeout(timer)
    inflight?.abort()
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible)
  }
}

// ───────────────────────── tool calling (LLM / voice) ─────────────────────────

/** Same names as the service's GET /tools. Route a model's tool call here. */
export type NewsToolName =
  | 'get_available_topics'
  | 'fetch_news'
  | 'fetch_asu_events'
  | 'get_news_item'
  | 'dedupe_news'
  | 'get_news_health'

/** Run any tool by name with the model's arguments (object or JSON string). Live by default. */
export async function callNewsTool(name: NewsToolName | string, args: Record<string, unknown> | string = {}) {
  const a: Record<string, unknown> = typeof args === 'string' ? (args.trim() ? JSON.parse(args) : {}) : { ...args }
  if (['fetch_news', 'fetch_asu_events'].includes(name) && a.live === undefined) a.live = true
  if (name === 'fetch_news' && a.tz_offset_minutes === undefined) a.tz_offset_minutes = deviceTzOffsetMinutes()
  const out = await request<{ name: string; result: unknown }>('/tools/call', {
    method: 'POST',
    body: JSON.stringify({ name, arguments: a }),
  })
  return out.result
}

/** OpenAI-style function definitions, straight from the service (always in sync with the server). */
export async function getNewsToolDefinitions(): Promise<unknown[]> {
  return (await request<{ tools: unknown[] }>('/tools')).tools
}
