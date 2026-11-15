// Exposed by electron/preload.cjs. Undefined when the UI runs in a plain browser (dev).
export {}

declare global {
  interface Window {
    novaFiles?: {
      /** Downloads url (with headers) into ~/Nova/Exam Prep and returns where it landed. */
      save(opts: { url: string; filename: string; folder: 'exam'; headers?: Record<string, string> }): Promise<{ path: string; bytes: number }>
      reveal(path: string): Promise<void>
      open(path: string): Promise<void>
    }
  }
}
