# NOVA — holographic avatar (Shruti's draft)

Standalone desktop app (Electron + React + Vite + Three.js): a neon-grid holographic
head & shoulders over an animated liquid-silk background, driven by push-to-talk.

**Voice backend:** wired to **Nova** (our Hermes brain via Vapi) through `@vapi-ai/web`.
Set keys in `.env` (see `.env.example`) — `VITE_VAPI_PUBLIC_KEY` + `VITE_VAPI_ASSISTANT_ID`.
Without them the app silently falls back to the local sample-voice dev path.

## Run

```bash
cd drafts/shruti/app
cp .env.example .env     # paste VAPI keys from repo-root shared.env / apps/voice/.env
npm install        # first time only
npm run dev        # opens the window (hot reload)
```

Press and hold **SPACE** to talk — this unmutes the Vapi call; release to mute. The call stays open in the background. Say *"talk to me as Shruti"* mid-call for persona switch (Vapi's `transferCall` → Savannah voice).

`npm start` builds and runs the production bundle instead. macOS asks for mic access
on first launch.

## Interaction flow

| State | Trigger | What you see |
|---|---|---|
| idle | default | gentle sway, blinks, breathing |
| listening | **hold SPACE** (the only way to talk) | signal-wave arcs pulse out of both ears; louder voice = brighter, faster pulses |
| thinking | release SPACE | head tilts up and to the side, eyes glance away, movement slows, grid shimmers; wireframe **?**, **!** and **light bulbs** (green, purple, violet, blue) drift across the whole screen at different depths, never over the face; bulbs occasionally flicker on like an idea. All of them fade out (0.6 s) before Nova speaks |
| speaking | Nova audio playing (`connectAudio`) | head faces the user and talks: lip sync only, nothing else on screen. The open mouth is a solid black cavity with the neon-green grid continuing inside |

On release, the recording is emitted. **TODO(backend)**: send it to the orchestrator
and play the reply:

```js
window.jarvisVoice.onUserSpeechEnd(async (blob, ms) => {
  const reply = await fetch(`${ORCHESTRATOR_URL}/voice`, { method: 'POST', body: blob })
  const audio = new Audio(URL.createObjectURL(await reply.blob()))
  await window.jarvisAvatar.endThinking()  // thinking symbols fade out fully first (~0.6 s)
  window.jarvisAvatar.connectAudio(audio)  // → speaking, lips follow the audio
  audio.play()
})
// also broadcast as a DOM event: 'jarvis:user-speech-end' (detail: { blob, durationMs })
```

With no handler registered, dev builds play `public/dev/sample-voice.m4a` as a fake
reply after 2.5 s. Non-dev builds go back to idle after 8 s.

A subtle "Hold SPACE to talk" hint shows when idle and fades out after 4 s.

**Debug panel:** press **D** to toggle it (off by default). It forces idle, listening
or thinking, or plays the sample reply ("speaking ▶").

## Public API

Available as `avatarRef.current` (React) or `window.jarvisAvatar` (anywhere).
Every call returns immediately; unknown names log a console warning and are ignored.

```ts
jarvisAvatar.connectAudio(source)   // HTMLAudioElement | MediaStream | AudioNode → lip sync
jarvisAvatar.disconnectAudio()
jarvisAvatar.setLevel(0.6)          // 0..1 volume fallback (e.g. Vapi 'volume-level')

jarvisAvatar.setState('idle' | 'listening' | 'thinking' | 'speaking')
jarvisAvatar.setExpression({ name: 'smile', duration_ms: 3000, intensity: 0.8 })
jarvisAvatar.setExpression({ name: 'sad', duration_ms: null })   // hold until cleared / user speaks
jarvisAvatar.clearExpression()
jarvisAvatar.lookAt({ target: 'shelf', duration_ms: 2000 })      // left|right|up|down|user|shelf
jarvisAvatar.playGesture({ name: 'nod' })                        // nod|shake|tilt
await jarvisAvatar.endThinking()   // leave 'thinking'; resolves once the symbols are gone
```

Expressions: `smile, laugh, angry, sad, surprised, confused, excited, wink, glitch, power_up`.
`duration_ms` omitted means the expression's default (2–4 s); `null` means hold until
`clearExpression()` or until the state becomes `listening`. A new expression replaces
the current one with a cross-fade. `lookAt` follows the same timer rules.
"left"/"right" are from the viewer's side; "shelf" looks into the empty space above
the head (reserved for hologram cards).

## Voice → state (automatic)

`src/avatar/voiceBridge.ts` maps voice events to base states:
user speech → `listening`, user done / tool call → `thinking`, assistant audio →
`speaking`, otherwise `idle`.

```js
// where the Vapi client is created (e.g. apps/voice/static/index.html):
window.jarvisVoice.bindVapi(vapi)        // speech-start/end, message, volume-level, call-end

// any other stack:
jarvisVoice.hooks.userSpeechStart() / userSpeechEnd() / toolCallStart() / toolCallEnd()
jarvisVoice.hooks.assistantSpeechStart() / assistantSpeechEnd() / callEnd()
```

Orchestrator tool calls can drive the avatar directly, e.g. a `show_emotion` tool →
`jarvisAvatar.setExpression({ name: 'excited' })`.
Also: whenever connected audio is audible and the state is `idle`, the avatar
switches itself to `speaking`, and back to `idle` after 1.3 s of silence.
The Vapi binding is written against `@vapi-ai/web` 2.3.x event names and has not
been run against a live call yet.

## Test keys

| Key | Action |
|---|---|
| 1–9, 0 | smile, laugh, angry, sad, surprised, confused, excited, wink, glitch, power_up |
| C | clear expression |
| ← → ↑ ↓ | lookAt left / right / up / down |
| U / H | lookAt user / shelf |
| N / S / G | gesture nod / shake / tilt |
| T | task demo: 5 mock tasks (press again to reset) |
| Q / W / E / R | state idle / listening / thinking / speaking |
| D | toggle the debug panel |
| M | mute / unmute the task-done chime (remembered) |
| I | dissolve the head into particles (demo of the 2-min idle dissolve) |

## How the layers blend (`src/avatar/AnimationController.ts`)

Every frame: `final = base + Σ(expression × weight) + look + gesture`, then the mouth.

- **Base** (one active, ~250 ms cross-fade): sway amount, pitch/yaw/roll offsets,
  lean, gaze offset, particle speed/spin, scan speed, emphasis nods.
- **Listening signal waves** (`src/avatar/signalWaves.ts`): 4 arcs per side of the
  head pulse from the inner arc outward (green → violet → purple), with sparkles. Mic
  volume speeds up and brightens the pulses. When the state leaves `listening`, the
  current pulse finishes and then fades out.
- **Expression** (timed, 200 ms in / 300 ms out, eased): grid tint, brightness,
  per-eye opening, eye glow, head pitch/roll/yaw, laugh bob, particle
  speed/count/direction/spin, scan speed, bloom, lip-corner offset, glitch, energy.
  The data lives in `src/avatar/expressions.ts`.
- **Look** (its own channel): head yaw/pitch, eye direction, calmer sway.
- **Mouth** (audio only): jaw, wide and round come straight from `AvatarAudio`
  into the shader. Expressions can only add the lip-corner offset; they never change
  the jaw. Inside the open mouth: solid black with the neon-green grid continuing in.

All weights use frame-rate-independent exponential smoothing plus smoothstep easing.
Speed changes accumulate phase (scan, particles), so nothing jumps. Uniforms are
written in one place (`applyFrame` in `Avatar3D.tsx`).

## Dev aids (env vars; nothing on the page)

Run `npm run build` first, then `npx electron .` with:

- `JARVIS_PAGE_JS='…'`: runs a snippet after load (e.g. loop a clip into `connectAudio`).
- `JARVIS_SCREENSHOT=out.png` with optional `JARVIS_SCREENSHOT_DELAY`, `JARVIS_SCREENSHOT_FRAMES` and `JARVIS_SCREENSHOT_INTERVAL` (ms): captures, then quits.
- `JARVIS_SIZE=700x1000`: window size, for checking framing.
- `JARVIS_QUERY=debug`: tints the face rig.

## Presence: boot, HUD, idle

- **Boot (~4 s):** black, then a scanline draws the grid face bottom to top, the eyes
  ignite, "NOVA" types in and fades out, and the liquid background fades in.
  **SPACE skips it.**
- **Cursor follow:** the head (up to ~11°) and eyes turn subtly toward the mouse and
  ease back when it leaves the window.
- **Sound:** one soft Web Audio chime when a task finishes; nothing else. **M** mutes.
- **HUD:** violet corner brackets, a status line
  ("NOVA · ONLINE · n AGENTS ACTIVE", n = running tasks) and faint scanlines.
- **Idle dissolve:** after 2 min with no interaction (while idle, nothing running),
  or on **I**, the head crumbles into floating green and purple dust. **SPACE or a
  click wakes it:** the particles rush back, the boot scanline redraws the face, and
  the eyes ignite. Waking never starts listening; the next SPACE hold talks.
  Mouse movement alone never wakes it.
- Code: `src/avatar/presence.ts` (timeline), `dissolveParticles.ts`,
  `src/ui/BootTitle.tsx`, `src/ui/Hud.tsx`, `src/audio/chime.ts`.

## Tasks (top-right)

A frosted-glass card shows the live task count; click it to open the stack of task
cards. Teammates add and update tasks through `window.jarvisTasks`; see
[`../TASKS_API.md`](../TASKS_API.md). Press **T** for a demo with mock tasks.

## Where things live

| Effect | File |
|---|---|
| Liquid-silk background | `src/avatar/liquidBackground.ts` |
| Push-to-talk recording | `src/voice/pushToTalk.ts` |
| Hint, debug panel | `src/ui/Controls.tsx` |
| Task data + API | `src/tasks/tasks.ts` (demo: `src/tasks/demo.ts`) |
| Task UI (glass card + stack) | `src/ui/TaskPanel.tsx` |
| Listening arcs | `src/avatar/signalWaves.ts` (timing in `AnimationController.ts`) |
| Thinking symbols (? ! bulbs) | `src/avatar/thinkingSymbols.ts` |
| Head shader / face rig | `src/avatar/hologramMaterial.ts` |

## Credits

3D head: **"Infinite, 3D Head Scan" by Lee Perry-Smith**, licensed under
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/), based on a work at
www.triplegangers.com, distributed with the three.js examples. License text is in
`public/models/LeePerrySmith_License.txt`. Shading, rig and animation are ours.
