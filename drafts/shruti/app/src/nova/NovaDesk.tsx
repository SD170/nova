// NOVA DESK — the side panel. A slim rail on the right edge that opens into a glass sheet:
// Today · Mail · Courses · News · LinkedIn · Saved · Memory, plus the quiz and notifications.
// Voice stays short; this is where the detail lives. Data: src/nova/useDesk.ts.
import { useCallback, useEffect, useState } from 'react'
import './nova.css'
import { errMsg, novaGet, novaPost } from './api'
import { openFile, revealFile } from './files'
import { IconClose, IconQuiz, IconRefresh, TAB_ICONS } from './icons'
import { QuizPanel } from './QuizPanel'
import { CoursesTab, LinkedInTab, MailTab, MemoryTab, NewsTab, SavedTab, TodayTab, type DeskCtx } from './Tabs'
import type { QuizView, SavedFile, TabId } from './types'
import { useDesk } from './useDesk'

const TABS: { id: TabId; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'mail', label: 'Mail' },
  { id: 'courses', label: 'Courses' },
  { id: 'news', label: 'News' },
  { id: 'linkedin', label: 'LinkedIn' },
  { id: 'saved', label: 'Saved' },
  { id: 'memory', label: 'Memory' },
]
const OPEN_KEY = 'nova.desk.open'
const noFocus = (e: React.MouseEvent) => e.preventDefault() // SPACE stays push-to-talk

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  return `${Math.floor(s / 3600)} h ago`
}

export function NovaDesk() {
  const { summary, offline, toasts, dismissToast, latest, refresh, quizRequest, clearQuizRequest } = useDesk()
  const [open, setOpen] = useState<boolean>(() => {
    const saved = localStorage.getItem(OPEN_KEY)
    return saved === null ? window.innerWidth >= 1200 : saved === '1'
  })
  const [tab, setTab] = useState<TabId>('today')
  const [quiz, setQuiz] = useState<QuizView | null>(null)
  const [showQuiz, setShowQuiz] = useState(false)
  const [quizMaking, setQuizMaking] = useState<string | null>(null)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    localStorage.setItem(OPEN_KEY, open ? '1' : '0')
    document.body.classList.toggle('nova-desk-open', open) // moves the tasks card out of the way
  }, [open])

  const flash = useCallback((msg: string) => {
    setNotice(msg)
    window.setTimeout(() => setNotice(''), 7000)
  }, [])

  // Nova (by voice) said "side panel": the quiz opens here.
  useEffect(() => {
    if (!quizRequest) return
    let live = true
    novaGet<QuizView>(`/quiz/${quizRequest.id}`)
      .then((v) => {
        if (!live) return
        setQuiz(v)
        setShowQuiz(true)
        setOpen(true)
      })
      .catch((e) => flash(errMsg(e)))
      .finally(clearQuizRequest)
    return () => {
      live = false
    }
  }, [quizRequest, clearQuizRequest, flash])

  // after a reload: resume a panel quiz that is still in progress
  useEffect(() => {
    const q = summary?.quiz
    if (q && !quiz && q.mode === 'panel' && q.status === 'in_progress') {
      setQuiz(q)
      setShowQuiz(true)
    }
  }, [summary, quiz])

  const takeHere = useCallback(
    async (quizId: string) => {
      try {
        const v = await novaPost<QuizView>(`/quiz/${quizId}/begin`, { mode: 'panel' })
        setQuiz(v)
        setShowQuiz(true)
        setOpen(true)
      } catch (e) {
        flash(errMsg(e))
      }
    },
    [flash],
  )

  const onQuizMe = useCallback(
    async (code: string) => {
      setQuizMaking(code)
      try {
        const made = await novaPost<QuizView>('/quiz/start', { course: code }, 150_000) // 5-40 s
        await takeHere(made.id)
      } catch (e) {
        flash(errMsg(e))
      } finally {
        setQuizMaking(null)
        void refresh()
      }
    },
    [takeHere, flash, refresh],
  )

  const ctx: DeskCtx = { quizMaking, onQuizMe }
  const demo = summary?.data_source === 'demo'
  const pdfFor = (q: QuizView): SavedFile | undefined => summary?.saved.find((f) => f.kind === 'quiz_cards' && f.course === q.course_code)
  const badge = (id: TabId): number => {
    if (!summary) return 0
    if (id === 'today') return summary.today.ok ? summary.today.count : 0
    if (id === 'mail') return summary.mail.ok ? summary.mail.important_count : 0
    if (id === 'saved') return summary.saved.length
    return 0
  }
  const quizLive = quiz && quiz.status !== 'done'
  const openFileFromToast = (path: string) => void openFile(path)

  return (
    <>
      {/* ── notifications: only things that finished or need you ── */}
      <div className="nova-toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`nova-toast nova-toast--${t.tone} glass`}>
            <div className="nova-toast-main">
              <div className="nova-toast-title">{t.title}</div>
              {t.detail && <div className="nova-toast-detail">{t.detail}</div>}
              <div className="nova-toast-actions">
                {t.file?.path && (
                  <>
                    <button className="nova-link" onMouseDown={noFocus} onClick={() => openFileFromToast(t.file!.path!)}>Open</button>
                    <button className="nova-link" onMouseDown={noFocus} onClick={() => void revealFile(t.file!.path!)}>Show in Finder</button>
                  </>
                )}
                {t.file && (
                  <button className="nova-link" onMouseDown={noFocus} onClick={() => { setTab('saved'); setShowQuiz(false); setOpen(true); dismissToast(t.id) }}>See in Saved</button>
                )}
                {t.quizId && (
                  <button className="nova-link" onMouseDown={noFocus} onClick={() => { void takeHere(t.quizId!); dismissToast(t.id) }}>Take it here</button>
                )}
              </div>
            </div>
            <button className="nova-x" aria-label="Dismiss" onMouseDown={noFocus} onClick={() => dismissToast(t.id)}>{IconClose}</button>
          </div>
        ))}
      </div>

      {/* ── collapsed: a slim rail with the tabs as icons + badges ── */}
      <button className={`nova-rail glass ${open ? 'nova-rail--hidden' : ''}`} aria-label="Open Nova Desk" onMouseDown={noFocus} onClick={() => setOpen(true)}>
        {TABS.map((t) => (
          <span key={t.id} className="nova-rail-i" title={t.label}>
            {TAB_ICONS[t.id]}
            {badge(t.id) > 0 && <i className="nova-badge">{badge(t.id) > 9 ? '9+' : badge(t.id)}</i>}
          </span>
        ))}
        {quizLive && <span className="nova-rail-i nova-rail-i--quiz" title="Quiz in progress">{IconQuiz}</span>}
      </button>

      {/* ── the desk ── */}
      <aside className={`nova-desk glass ${open ? 'nova-desk--open' : ''}`} aria-hidden={!open}>
        <header className="nova-head">
          <span className="nova-title">NOVA DESK</span>
          <span className={`nova-src ${demo ? 'nova-src--demo' : ''}`}>{demo ? 'DEMO DATA' : 'LIVE'}</span>
          <span className="nova-head-actions">
            <button className="nova-x" aria-label="Refresh" onMouseDown={noFocus} onClick={() => void refresh()}>{IconRefresh}</button>
            <button className="nova-x" aria-label="Close" onMouseDown={noFocus} onClick={() => setOpen(false)}>{IconClose}</button>
          </span>
        </header>

        {offline && <div className="nova-offline">Can't reach Nova's services ({offline}). Trying again…</div>}
        {notice && <div className="nova-offline">{notice}</div>}

        {latest[0] && !showQuiz && (
          <div className="nova-now">
            <span className="nova-now-dot" />
            <span className="nova-now-text">
              <b>{latest[0].title}</b>
              {latest[0].detail ? ` · ${latest[0].detail}` : ''}
            </span>
            <span className="nova-now-when">{timeAgo(latest[0].at)}</span>
          </div>
        )}

        {quiz && showQuiz ? (
          <div className="nova-body">
            <QuizPanel
              quiz={quiz}
              pdf={pdfFor(quiz)}
              onChange={(v) => { setQuiz(v); if (v.status === 'done') void refresh() }}
              onClose={() => { setShowQuiz(false); if (quiz.status === 'done') setQuiz(null) }}
              onOpenPdf={(f) => { setTab('saved'); setShowQuiz(false); if (f.id) void refresh() }}
            />
          </div>
        ) : (
          <>
            {quizLive && (
              <button className="nova-resume" onMouseDown={noFocus} onClick={() => setShowQuiz(true)}>
                {IconQuiz} Resume your {quiz!.course_code} quiz · {quiz!.answered} of {quiz!.total}
              </button>
            )}
            <nav className="nova-tabs">
              {TABS.map((t) => (
                <button key={t.id} className={`nova-tab ${tab === t.id ? 'nova-tab--on' : ''}`} onMouseDown={noFocus} onClick={() => setTab(t.id)}>
                  {TAB_ICONS[t.id]}
                  <span>{t.label}</span>
                  {badge(t.id) > 0 && <i className="nova-badge">{badge(t.id) > 9 ? '9+' : badge(t.id)}</i>}
                </button>
              ))}
            </nav>
            <div className="nova-body">
              {!summary ? (
                <div className="nova-empty">{offline ? 'Waiting for Nova…' : 'Loading…'}</div>
              ) : (
                <>
                  {tab === 'today' && <TodayTab s={summary} />}
                  {tab === 'mail' && <MailTab s={summary} />}
                  {tab === 'courses' && <CoursesTab s={summary} ctx={ctx} />}
                  {tab === 'news' && <NewsTab s={summary} />}
                  {tab === 'linkedin' && <LinkedInTab s={summary} />}
                  {tab === 'saved' && <SavedTab s={summary} />}
                  {tab === 'memory' && <MemoryTab s={summary} />}
                </>
              )}
            </div>
          </>
        )}
      </aside>
    </>
  )
}
