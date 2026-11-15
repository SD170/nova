// The quiz in the side panel: questions pop up ONE BY ONE, no answers shown until the end,
// then the score + a review. The voice quiz uses the same session on the server.
import { useState } from 'react'
import { errMsg, novaPost } from './api'
import { IconCheck, IconCross } from './icons'
import type { QuizView, SavedFile } from './types'

const LETTERS = ['A', 'B', 'C', 'D']
const noFocus = (e: React.MouseEvent) => e.preventDefault() // buttons never take focus: SPACE stays push-to-talk

export function QuizPanel({
  quiz,
  pdf,
  onChange,
  onClose,
  onOpenPdf,
}: {
  quiz: QuizView
  pdf?: SavedFile
  onChange: (q: QuizView) => void
  onClose: () => void
  onOpenPdf: (f: SavedFile) => void
}) {
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState('')
  const current = quiz.questions.find((q) => q.chosen === null)

  async function pick(index: number, option: number) {
    setBusy(option)
    setError('')
    try {
      onChange(await novaPost<QuizView>(`/quiz/${quiz.id}/answer`, { choice: LETTERS[option], index }))
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  // ───────── score + review ─────────
  if (quiz.status === 'done' && quiz.review) {
    const weak = Array.from(new Set(quiz.review.filter((r) => !r.correct).map((r) => quiz.questions[r.index]?.topic).filter(Boolean)))
    return (
      <div className="nova-quiz">
        <div className="nova-quiz-top">
          <span className="nova-chip">{quiz.course_code} · quiz</span>
          <button className="nova-link" onMouseDown={noFocus} onClick={onClose}>Done</button>
        </div>
        <div className="nova-score">
          <div className="nova-score-num">
            {quiz.score}<span> / {quiz.total}</span>
          </div>
          <div className="nova-score-sub">{quiz.score === quiz.total ? 'Perfect score' : weak.length ? `Weak on ${weak.slice(0, 2).join(' and ')}` : 'Nice work'}</div>
        </div>
        <div className="nova-review">
          {quiz.review.map((r) => {
            const q = quiz.questions[r.index]
            return (
              <div key={r.index} className={`nova-rev ${r.correct ? 'nova-rev--ok' : 'nova-rev--bad'}`}>
                <span className="nova-rev-mark">{r.correct ? IconCheck : IconCross}</span>
                <div>
                  <div className="nova-rev-q">{q.q}</div>
                  <div className="nova-rev-a">
                    {r.correct ? `${LETTERS[r.answer]}. ${q.options[r.answer]}` : `You: ${r.chosen === null ? 'no answer' : `${LETTERS[r.chosen]}. ${q.options[r.chosen]}`}  ·  Right: ${LETTERS[r.answer]}. ${q.options[r.answer]}`}
                  </div>
                  {r.explanation && <div className="nova-rev-why">{r.explanation}{r.source ? `  (${r.source})` : ''}</div>}
                </div>
              </div>
            )
          })}
        </div>
        {pdf && <button className="nova-btn" onMouseDown={noFocus} onClick={() => onOpenPdf(pdf)}>Open the cards PDF</button>}
      </div>
    )
  }

  if (!current) return <div className="nova-empty">Finishing your quiz…</div>

  // ───────── one question ─────────
  return (
    <div className="nova-quiz">
      <div className="nova-quiz-top">
        <span className="nova-chip">{quiz.course_code} · question {current.index + 1} of {quiz.total}</span>
        <button className="nova-link" onMouseDown={noFocus} onClick={onClose}>Hide</button>
      </div>
      <div className="nova-dots">
        {quiz.questions.map((q) => (
          <span key={q.index} className={`nova-dot ${q.chosen !== null ? 'nova-dot--done' : q.index === current.index ? 'nova-dot--now' : ''}`} />
        ))}
      </div>
      {quiz.mode === 'voice' && <div className="nova-note">You started this one by voice. You can finish it here.</div>}
      <div key={current.index} className="nova-qcard">
        {current.topic && <div className="nova-qtopic">{current.topic}</div>}
        <div className="nova-qtext">{current.q}</div>
        <div className="nova-opts">
          {current.options.map((o, i) => (
            <button key={i} className="nova-opt" disabled={busy !== null} onMouseDown={noFocus} onClick={() => void pick(current.index, i)}>
              <b>{LETTERS[i]}</b>
              <span>{o}</span>
            </button>
          ))}
        </div>
      </div>
      {error && <div className="nova-error">{error}</div>}
    </div>
  )
}
