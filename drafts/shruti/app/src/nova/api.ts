import { NOVA_BASE, authHeaders } from './config'

export async function novaFetch<T>(path: string, init?: RequestInit, timeoutMs = 60_000): Promise<T> {
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const res = await fetch(NOVA_BASE + path, {
      ...init,
      signal: ctl.signal,
      headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init?.headers as Record<string, string> | undefined) },
    })
    if (!res.ok) {
      let detail = ''
      try {
        const j = (await res.json()) as { detail?: string }
        detail = j.detail || ''
      } catch {
        /* not JSON */
      }
      throw new Error(detail || `HTTP ${res.status}`)
    }
    return (await res.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

export const novaGet = <T,>(path: string, timeoutMs?: number) => novaFetch<T>(path, undefined, timeoutMs)
export const novaPost = <T,>(path: string, body?: unknown, timeoutMs?: number) =>
  novaFetch<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }, timeoutMs)

export const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e))
