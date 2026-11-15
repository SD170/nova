// ─────────────────────────────────────────────────────────────────────────────
// Push-to-talk: hold SPACE to record the student (the only way to talk).
//
//   start()  → mic opens (getUserMedia), recording starts, avatar → 'listening'
//   stop()   → recording ends, avatar → 'thinking', onUserSpeechEnd(blob) fires
//
// TODO(backend): register a handler and send the audio to the orchestrator:
//
//   window.jarvisVoice.onUserSpeechEnd(async (blob) => {
//     const reply = await fetch(`${ORCHESTRATOR_URL}/voice`, { method: 'POST', body: blob })
//     const audio = new Audio(URL.createObjectURL(await reply.blob()))
//     await window.jarvisAvatar.endThinking()   // thinking symbols fade out first
//     window.jarvisAvatar.connectAudio(audio)   // lips follow it
//     audio.play()                              // state goes 'speaking', then 'idle'
//   })
//
// The same blob is also broadcast as a DOM event: 'jarvis:user-speech-end'
// (event.detail = { blob, durationMs }).
// ─────────────────────────────────────────────────────────────────────────────

export type SpeechHandler = (blob: Blob, durationMs: number) => void

export class PushToTalk {
  recording = false
  onStart?: () => void
  /** fires the instant the student releases (before the audio blob is ready) */
  onRelease?: () => void
  onEnd?: SpeechHandler
  onError?: (err: unknown) => void

  private stream: MediaStream | null = null
  private ctx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private buf: Float32Array | null = null
  private recorder: MediaRecorder | null = null
  private chunks: Blob[] = []
  private startedAt = 0
  private level = 0

  /** Open the mic once and keep it (faster second press, single permission prompt). */
  private async ensureMic() {
    if (this.stream) return
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    this.ctx = new AudioContext()
    const src = this.ctx.createMediaStreamSource(this.stream)
    this.analyser = this.ctx.createAnalyser()
    this.analyser.fftSize = 1024
    this.buf = new Float32Array(this.analyser.fftSize)
    src.connect(this.analyser)
  }

  async start() {
    if (this.recording) return
    this.recording = true // set first so a quick release still stops cleanly
    this.onStart?.()
    try {
      await this.ensureMic()
      if (this.ctx?.state === 'suspended') await this.ctx.resume()
      if (!this.recording) return // released while the mic was opening
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : ''
      this.recorder = new MediaRecorder(this.stream!, mime ? { mimeType: mime } : undefined)
      this.chunks = []
      this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data)
      this.recorder.start()
      this.startedAt = performance.now()
    } catch (err) {
      this.recording = false
      this.onError?.(err)
    }
  }

  stop() {
    if (!this.recording) return
    this.recording = false
    this.onRelease?.()
    const rec = this.recorder
    this.recorder = null
    const durationMs = performance.now() - this.startedAt
    if (!rec || rec.state === 'inactive') {
      this.onEnd?.(new Blob([], { type: 'audio/webm' }), 0)
      return
    }
    rec.onstop = () => this.onEnd?.(new Blob(this.chunks, { type: rec.mimeType || 'audio/webm' }), durationMs)
    rec.stop()
  }

  /** 0..1 smoothed mic volume (0 when not recording). Call every frame. */
  micLevel(): number {
    if (!this.recording || !this.analyser || !this.buf) {
      this.level *= 0.85
      return this.level
    }
    this.analyser.getFloatTimeDomainData(this.buf as any)
    let sum = 0
    for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i]
    const target = Math.min(1, Math.sqrt(sum / this.buf.length) * 7)
    this.level += (target - this.level) * (target > this.level ? 0.5 : 0.12)
    return this.level
  }
}
