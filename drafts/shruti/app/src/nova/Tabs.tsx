// The Nova Desk tabs. Display only: every string arrives short and display-ready from the service.
import { useState } from 'react'
import { IconFile, IconQuiz } from './icons'
import { localPath, openFile, revealFile, saveFile } from './files'
import { errMsg } from './api'
import type { SavedFile, Section, Summary } from './types'

const noFocus = (e: React.MouseEvent) => e.preventDefault() // SPACE stays push-to-talk
const open = (url: string) => url && window.open(url, '_blank') // Electron sends links to the real browser
const tilde = (p: string) => p.replace(/^\/Users\/[^/]+/, '~')

export interface DeskCtx {
  quizMaking: string | null
  onQuizMe: (code: string) => void
}

function Failed({ msg }: { msg: string }) {
  return <div className="nova-error">Couldn't load this: {msg}</div>
}
const Empty = ({ children }: { children: React.ReactNode }) => <div className="nova-empty">{children}</div>
const Group = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="nova-group">
    <div className="nova-group-title">{title}</div>
    {children}
  </div>
)

function sect<T>(sec: Section<T>, render: (d: T) => React.ReactNode) {
  if (sec.ok === false) return <Failed msg={(sec as { ok: false; error: string }).error} />
  return render(sec as unknown as T)
}

export function TodayTab({ s }: { s: Summary }) {
  return (
    <>
      {sect(s.today, (t) => (
        <>
          <Group title={`Due this week · ${t.count}`}>
            {t.due.length === 0 && <Empty>Nothing due this week.</Empty>}
            {t.due.map((d) => (
              <button key={d.id} className="nova-row" onMouseDown={noFocus} onClick={() => open(d.source_url)}>
                <span className="nova-chip nova-chip--course">{d.course}</span>
                <span className="nova-row-main">
                  <span className="nova-row-title">{d.title}</span>
                  <span className={`nova-row-sub ${d.due.startsWith('today') ? 'nova-hot' : ''}`}>{d.due}</span>
                </span>
                {d.points ? <span className="nova-pts">{d.points} pts</span> : null}
              </button>
            ))}
          </Group>
          <Group title="Calendar">
            {t.events.length === 0 && <Empty>Nothing on your calendar today or tomorrow.</Empty>}
            {t.events.map((e) => (
              <div key={e.id} className="nova-row nova-row--plain">
                <span className={`nova-chip ${e.calendar === 'nova' ? 'nova-chip--nova' : ''}`}>{e.calendar === 'nova' ? 'Nova' : 'You'}</span>
                <span className="nova-row-main">
                  <span className="nova-row-title">{e.title}</span>
                  <span className="nova-row-sub">{e.when}</span>
                </span>
              </div>
            ))}
          </Group>
        </>
      ))}
    </>
  )
}

export function MailTab({ s }: { s: Summary }) {
  return sect(s.mail, (m) => (
    <Group title={`${m.important_count} important · ${m.needs_reply_count} need a reply · ${m.total} recent`}>
      {m.emails.length === 0 && <Empty>No mail in the last 3 days.</Empty>}
      {m.emails.map((e) => (
        <button key={e.id} className="nova-row nova-row--mail" onMouseDown={noFocus} onClick={() => open(`https://mail.google.com/mail/u/0/#inbox/${e.id}`)}>
          <span className="nova-row-main">
            <span className="nova-row-head">
              <span className="nova-row-title">{e.from}</span>
              <span className="nova-row-when">{e.when}</span>
            </span>
            <span className="nova-row-subject">{e.subject}</span>
            <span className="nova-tags">
              <span className="nova-chip">{e.category}</span>
              {e.important && <span className="nova-chip nova-chip--warn">important</span>}
              {e.needs_reply && <span className="nova-chip nova-chip--good">needs reply</span>}
            </span>
          </span>
        </button>
      ))}
    </Group>
  ))
}

export function CoursesTab({ s, ctx }: { s: Summary; ctx: DeskCtx }) {
  return sect(s.courses, (c) => (
    <Group title="Your courses">
      {c.courses.map((co) => (
        <div key={co.id} className="nova-course">
          <div className="nova-course-top">
            <span className="nova-course-code">{co.code}</span>
            <button className="nova-btn nova-btn--small" disabled={ctx.quizMaking !== null} onMouseDown={noFocus} onClick={() => ctx.onQuizMe(co.code)}>
              {IconQuiz}
              {ctx.quizMaking === co.code ? 'Making your quiz…' : 'Quiz me'}
            </button>
          </div>
          <div className="nova-row-sub">{co.name}</div>
          <div className="nova-course-exam">{co.exam ? `${co.exam.name} · ${co.exam.date}` : 'Ask Nova: "when is my exam?"'}</div>
        </div>
      ))}
    </Group>
  ))
}

export function NewsTab({ s }: { s: Summary }) {
  return sect(s.news, (n) => (
    <Group title="Top news">
      {n.stories.length === 0 && <Empty>No news right now.</Empty>}
      {n.stories.map((st) => (
        <button key={st.id} className="nova-row nova-row--news" onMouseDown={noFocus} onClick={() => open(st.url)}>
          <span className="nova-row-main">
            <span className="nova-row-subject">{st.title}</span>
            <span className="nova-row-sub">
              {st.source} · {st.published}
              {st.confirmed ? ` · confirmed by ${st.outlets} outlets` : ''}
            </span>
          </span>
        </button>
      ))}
    </Group>
  ))
}

export function LinkedInTab({ s }: { s: Summary }) {
  return sect(s.linkedin, (l) => (
    <>
      <Group title={`LinkedIn · ${l.posts_seen} posts seen · ${l.engaged_posts} engaged`}>
        {l.people.length === 0 && <Empty>Scroll LinkedIn with the Nova Chrome extension and people worth contacting appear here.</Empty>}
        {l.people.map((p) => (
          <button key={p.name} className="nova-row nova-row--person" onMouseDown={noFocus} onClick={() => open(p.url)}>
            <span className="nova-row-main">
              <span className="nova-row-title">{p.name}</span>
              <span className="nova-row-sub">{p.headline}</span>
              <span className="nova-row-why">{p.why}</span>
              <span className="nova-row-action">{p.action}</span>
            </span>
          </button>
        ))}
      </Group>
      {l.companies.length > 0 && (
        <Group title="Companies">
          <div className="nova-tags">{l.companies.map((c) => <span key={c} className="nova-chip">{c}</span>)}</div>
        </Group>
      )}
      {l.interests.length > 0 && (
        <Group title="What you engage with">
          <div className="nova-tags">{l.interests.map((c) => <span key={c} className="nova-chip nova-chip--nova">{c}</span>)}</div>
        </Group>
      )}
    </>
  ))
}

function SavedRow({ f }: { f: SavedFile }) {
  const [path, setPath] = useState<string | undefined>(localPath(f.id))
  const [err, setErr] = useState('')
  const kb = Math.max(1, Math.round(f.size_bytes / 1024))
  async function download() {
    setErr('')
    try {
      const p = await saveFile({ id: f.id, download_url: f.download_url, filename: f.filename })
      if (p) setPath(p)
    } catch (e) {
      setErr(errMsg(e))
    }
  }
  return (
    <div className="nova-file">
      <span className="nova-file-icon">{IconFile}</span>
      <div className="nova-row-main">
        <span className="nova-row-title">{f.title}</span>
        <span className="nova-row-sub">
          {f.kind === 'quiz_cards' ? `${f.course} flashcards` : 'Document'} · {f.format.toUpperCase()} · {kb} KB · {f.when}
        </span>
        <span className="nova-file-path">{path ? `Saved to ${tilde(path)}` : 'Not saved on this laptop yet'}</span>
        <span className="nova-file-actions">
          {path ? (
            <>
              <button className="nova-link" onMouseDown={noFocus} onClick={() => void openFile(path)}>Open</button>
              <button className="nova-link" onMouseDown={noFocus} onClick={() => void revealFile(path)}>Show in Finder</button>
            </>
          ) : (
            <button className="nova-link" onMouseDown={noFocus} onClick={() => void download()}>{window.novaFiles ? 'Save to Nova folder' : 'Download'}</button>
          )}
        </span>
        {err && <span className="nova-error">{err}</span>}
      </div>
    </div>
  )
}

export function SavedTab({ s }: { s: Summary }) {
  return (
    <Group title={`Saved by Nova · ${s.saved.length}`}>
      {s.saved.length === 0 && <Empty>Quiz cards and documents Nova makes will show up here.</Empty>}
      {s.saved.map((f) => (
        <SavedRow key={f.id} f={f} />
      ))}
    </Group>
  )
}

export function MemoryTab({ s }: { s: Summary }) {
  return sect(s.memory, (m) =>
    !m.enabled ? (
      <Empty>Memory is off. Add SUPERMEMORY_API_KEY to turn it on.</Empty>
    ) : (
      <>
        <Group title="What Nova knows about you">
          {m.facts.length === 0 && <Empty>Nothing yet. Tell Nova what you prefer or what you're aiming for.</Empty>}
          {m.facts.map((f) => <div key={f} className="nova-fact">{f}</div>)}
        </Group>
        <Group title="Recently remembered">
          {m.recent.length === 0 && <Empty>Quiz results and new facts appear here.</Empty>}
          {m.recent.map((r) => (
            <div key={r.id} className="nova-fact nova-fact--recent">
              <span className="nova-chip">{r.kind === 'quiz_result' ? 'quiz' : r.kind || 'fact'}</span>
              {r.text}
            </div>
          ))}
        </Group>
      </>
    ),
  )
}
