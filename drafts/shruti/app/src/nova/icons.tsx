import type { ReactNode } from 'react'
import type { TabId } from './types'

const base = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round' } as const
const svg = (children: ReactNode) => <svg {...base} aria-hidden="true">{children}</svg>

export const TAB_ICONS: Record<TabId, ReactNode> = {
  today: svg(<><rect x="3.5" y="5" width="17" height="15" rx="2.5" /><path d="M3.5 10h17M8 3v4M16 3v4" /></>),
  mail: svg(<><rect x="3" y="5.5" width="18" height="13" rx="2.5" /><path d="m4 8 8 6 8-6" /></>),
  courses: svg(<><path d="m3 9 9-5 9 5-9 5-9-5Z" /><path d="M7 11.5V16c0 1.2 2.2 2.5 5 2.5s5-1.3 5-2.5v-4.5" /></>),
  news: svg(<><path d="M5 5h11v14H7a2 2 0 0 1-2-2V5Z" /><path d="M16 9h3v8a2 2 0 0 1-2 2M8 9h5M8 12.5h5M8 16h3" /></>),
  linkedin: svg(<><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8.5 10.5v5M8.5 8v.01M12 15.5v-5M12 12.7c0-1.4 1-2.2 2.2-2.2s1.8.8 1.8 2.2v2.8" /></>),
  saved: svg(<><path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Z" /></>),
  memory: svg(<><path d="M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-1.5 5.2A3 3 0 0 0 7 17.5a3 3 0 0 0 5 1V4.5a2.7 2.7 0 0 0-3 0Z" /><path d="M15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 1.5 5.2 3 3 0 0 1-2.5 4.8 3 3 0 0 1-5 1" /></>),
}

export const IconClose = svg(<path d="M6 6l12 12M18 6 6 18" />)
export const IconRefresh = svg(<><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 5v6h-6" /></>)
export const IconFile = svg(<><path d="M7 3.5h7l4 4V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" /><path d="M14 3.5V8h4M9 13h6M9 16.5h6" /></>)
export const IconCheck = svg(<path d="m5 12.5 4.5 4.5L19 7.5" />)
export const IconCross = svg(<path d="M7 7l10 10M17 7 7 17" />)
export const IconQuiz = svg(<><circle cx="12" cy="12" r="8.5" /><path d="M9.7 9.6a2.4 2.4 0 1 1 3.4 2.2c-.7.4-1.1.9-1.1 1.7M12 16.8v.01" /></>)
