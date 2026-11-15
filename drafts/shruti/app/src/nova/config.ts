// Where the Nova workspace service lives. Set in the app's .env (see .env.example):
//   VITE_NOVA_BASE  = the PUBLIC_WORKSPACE_BASE tunnel URL in repo-root shared.env (or http://localhost:9005)
//   VITE_NOVA_KEY   = the shared CANVAS_API_KEY (sent as X-Canvas-Key)
const env = import.meta.env

export const NOVA_BASE: string = String(env.VITE_NOVA_BASE || 'http://localhost:9005').replace(/\/$/, '')
export const NOVA_KEY: string = String(env.VITE_NOVA_KEY || '')

export const authHeaders = (): Record<string, string> => (NOVA_KEY ? { 'X-Canvas-Key': NOVA_KEY } : {})
export const absUrl = (u: string): string => (u.startsWith('http') ? u : NOVA_BASE + u)
