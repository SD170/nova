// Everything the Nova Desk needs from the workspace service:
//   - /panel/summary every 45 s (the tabs)
//   - /panel/feed every 2.5 s (notifications: quiz ready, PDF saved, score). Meaningful only.
// A `pdf_saved` event also downloads the PDF into ~/Nova/Exam Prep on this laptop.
import { useCallback, useEffect, useRef, useState } from 'react'
import { errMsg, novaGet } from './api'
import { saveFile } from './files'
import type { FeedEvent, QuizView, Summary, Toast } from './types'
import { playChime } from '../audio/chime'

const SUMMARY_MS = 45_000
const FEED_MS = 2_500
const FEED_KEY = 'nova.lastFeedId'

export function useDesk() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [offline, setOffline] = useState<string | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [latest, setLatest] = useState<FeedEvent[]>([])
  const [quizRequest, setQuizRequest] = useState<{ id: string; n: number } | null>(null)
  const lastId = useRef<number | null>(null) // null until the first poll: old events never toast
  const toastId = useRef(1)
  const busy = useRef(false)

  const refresh = useCallback(async () => {
    try {
      setSummary(await novaGet<Summary>('/panel/summary', 40_000))
      setOffline(null)
    } catch (e) {
      setOffline(errMsg(e))
    }
  }, [])

  const addToast = useCallback((t: Omit<Toast, 'id'>) => {
    const id = toastId.current++
    setToasts((prev) => [...prev, { ...t, id }].slice(-4))
    playChime()
    window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), t.file ? 14_000 : 8_000)
  }, [])

  const dismissToast = useCallback((id: number) => setToasts((prev) => prev.filter((t) => t.id !== id)), [])

  const handle = useCallback(
    async (events: FeedEvent[], toast: boolean) => {
      let needsRefresh = false
      for (const ev of events) {
        setLatest((prev) => [ev, ...prev].slice(0, 12))
        if (ev.kind === 'memory' || ev.data?.quiet) {
          needsRefresh = true // shown in the Memory tab, no toast
          continue
        }
        if (!toast) continue
        if (ev.kind === 'pdf_saved') {
          needsRefresh = true
          const d = ev.data as { document_id: string; download_url: string; filename: string }
          let path: string | null = null
          let detail = ev.detail
          try {
            path = await saveFile({ id: d.document_id, download_url: d.download_url, filename: d.filename })
            if (path) detail = `Saved to ${path.replace(/^\/Users\/[^/]+/, '~')}`
          } catch (e) {
            detail = `Couldn't save it here: ${errMsg(e)}`
          }
          addToast({ kind: ev.kind, title: ev.title, detail, tone: 'good', file: { id: d.document_id, path } })
        } else if (ev.kind === 'quiz_panel') {
          setQuizRequest({ id: String(ev.data.quiz_id), n: Date.now() }) // opens the quiz in the desk
        } else if (ev.kind === 'quiz_ready') {
          needsRefresh = true
          addToast({ kind: ev.kind, title: ev.title, detail: ev.detail, tone: 'info', quizId: String(ev.data.quiz_id) })
        } else if (ev.kind === 'quiz_score') {
          needsRefresh = true
          addToast({ kind: ev.kind, title: ev.title, detail: ev.detail, tone: 'good' })
        } else if (ev.kind === 'pdf_failed') {
          addToast({ kind: ev.kind, title: ev.title, detail: ev.detail, tone: 'bad' })
        }
      }
      if (needsRefresh) void refresh()
    },
    [addToast, refresh],
  )

  const pollFeed = useCallback(async () => {
    if (busy.current) return
    busy.current = true
    try {
      const since = lastId.current ?? Number(sessionStorage.getItem(FEED_KEY) || 0)
      const { events } = await novaGet<{ events: FeedEvent[] }>(`/panel/feed?since=${since}`, 8_000)
      const first = lastId.current === null && !sessionStorage.getItem(FEED_KEY)
      const max = events.reduce((m, e) => Math.max(m, e.id), since)
      lastId.current = max
      sessionStorage.setItem(FEED_KEY, String(max))
      if (events.length) await handle(events, !first) // first poll of a fresh session: history, no toasts
      setOffline(null)
    } catch (e) {
      setOffline(errMsg(e))
    } finally {
      busy.current = false
    }
  }, [handle])

  useEffect(() => {
    void refresh()
    void pollFeed()
    const a = window.setInterval(() => void refresh(), SUMMARY_MS)
    const b = window.setInterval(() => void pollFeed(), FEED_MS)
    return () => {
      window.clearInterval(a)
      window.clearInterval(b)
    }
  }, [refresh, pollFeed])

  return { summary, offline, toasts, dismissToast, latest, refresh, quizRequest, clearQuizRequest: () => setQuizRequest(null) }
}

export type { QuizView }
