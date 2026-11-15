/**
 * useNews.ts — React hooks over newsTools.ts. Copy both files into the UI.
 *
 *   const { news, loading, error, refresh } = useLiveNews('world, Phoenix Suns, AI policy')
 *   news?.items.map((s) => <a href={s.url}>{s.title} — {s.source}</a>)
 *
 *   const { events } = useAsuEvents({ days: 7, query: 'career fair' })
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchAsuEvents,
  watchNews,
  type EventsResult,
  type FetchEventsOptions,
  type NewsItem,
  type NewsResult,
  type NewsToolError,
  type WatchOptions,
} from './newsTools'

/** Live news for the student's topics; refreshes every minute and when the window regains focus. */
export function useLiveNews(
  topics: string | string[],
  opts: Omit<WatchOptions, 'onError'> = {},
): {
  news: NewsResult | null
  loading: boolean
  error: NewsToolError | null
  newStories: NewsItem[] // stories that arrived in the latest update (for a "new" badge / toast)
  refresh: () => void
} {
  const key = Array.isArray(topics) ? topics.join(',') : topics
  const { intervalMs, sinceHours, tzOffsetMinutes, trustedOnly, perTopic } = opts
  const onNewRef = useRef(opts.onNewStories)
  onNewRef.current = opts.onNewStories

  const [news, setNews] = useState<NewsResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<NewsToolError | null>(null)
  const [newStories, setNewStories] = useState<NewsItem[]>([])
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!key.trim()) {
      setNews(null)
      setLoading(false)
      return
    }
    setLoading(true)
    return watchNews(
      key,
      (n) => {
        setNews(n)
        setError(null)
        setLoading(false)
      },
      {
        intervalMs,
        sinceHours,
        tzOffsetMinutes,
        trustedOnly,
        perTopic,
        onError: (e) => {
          setError(e)
          setLoading(false)
        },
        onNewStories: (items) => {
          setNewStories(items)
          onNewRef.current?.(items)
        },
      },
    )
  }, [key, intervalMs, sinceHours, tzOffsetMinutes, trustedOnly, perTopic, nonce])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  return { news, loading, error, newStories, refresh }
}

/** Upcoming ASU events (live). Re-fetches when options change; refresh() to re-read now. */
export function useAsuEvents(opts: Omit<FetchEventsOptions, 'signal'> = {}): {
  events: EventsResult | null
  loading: boolean
  error: NewsToolError | null
  refresh: () => void
} {
  const { days, query, campus, limit, live } = opts
  const [events, setEvents] = useState<EventsResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<NewsToolError | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    const ctrl = new AbortController()
    setLoading(true)
    fetchAsuEvents({ days, query, campus, limit, live, signal: ctrl.signal })
      .then((e) => {
        setEvents(e)
        setError(null)
      })
      .catch((e: NewsToolError) => {
        if (!ctrl.signal.aborted) setError(e)
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false)
      })
    return () => ctrl.abort()
  }, [days, query, campus, limit, live, nonce])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  return { events, loading, error, refresh }
}
