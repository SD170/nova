// Saving what Nova makes (the exam-prep PDF) onto THIS laptop: ~/Nova/Exam Prep via Electron,
// or a normal browser download when running in a plain browser (dev).
import { absUrl, authHeaders } from './config'

const KEY = 'nova.savedPaths'

function load(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}') as Record<string, string>
  } catch {
    return {}
  }
}

export const localPath = (id: string): string | undefined => load()[id]

function remember(id: string, path: string) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...load(), [id]: path }))
  } catch {
    /* storage unavailable: the file is still saved */
  }
}

/** Downloads a saved file. Returns its path on this laptop (Electron) or null (browser download). */
export async function saveFile(f: { id: string; download_url: string; filename: string }): Promise<string | null> {
  const url = absUrl(f.download_url)
  if (window.novaFiles) {
    const r = await window.novaFiles.save({ url, filename: f.filename, folder: 'exam', headers: authHeaders() })
    remember(f.id, r.path)
    return r.path
  }
  const res = await fetch(url, { headers: authHeaders() })
  if (!res.ok) throw new Error(`Download failed (HTTP ${res.status})`)
  const blobUrl = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = f.filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(blobUrl), 5000)
  return null
}

export const revealFile = (path: string) => window.novaFiles?.reveal(path)
export const openFile = (path: string) => window.novaFiles?.open(path)
