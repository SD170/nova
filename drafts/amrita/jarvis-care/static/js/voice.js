// Voice controller: tap-to-talk speech recognition + spoken replies.
// Progressive enhancement — every function degrades to text when the browser
// lacks SpeechRecognition or speechSynthesis. One microphone owner, one voice.
import * as prefs from "./prefs.js";

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const synth = "speechSynthesis" in window ? window.speechSynthesis : null;

export const support = {
  stt: Boolean(SR),
  tts: Boolean(synth && "SpeechSynthesisUtterance" in window),
};

const STATE_LABELS = {
  idle: "Ready",
  listening: "Listening… microphone on",
  thinking: "Thinking…",
  speaking: "Speaking…",
  done: "Done",
  error: "Something went wrong",
};

let state = "idle";
let rec = null;
let finalText = "";
let lastSpoken = "";
const handlers = { state: new Set(), interim: new Set(), final: new Set(), error: new Set() };

export function on(evt, fn) { handlers[evt].add(fn); return () => handlers[evt].delete(fn); }
function emit(evt, ...args) { for (const fn of handlers[evt]) fn(...args); }

export function getState() { return state; }
export function stateLabel(s = state) { return STATE_LABELS[s] || s; }
export function setState(s) { state = s; emit("state", s); }
export function isListening() { return state === "listening"; }

const ERRORS = {
  "not-allowed": "Microphone access is blocked. You can type instead, or allow the microphone in your browser's site settings.",
  "service-not-allowed": "Speech recognition isn't allowed in this browser. Please type your message instead.",
  "no-speech": "I didn't hear anything. Press Talk to try again, or type your message.",
  "audio-capture": "I couldn't find a microphone. Please type your message instead.",
  "network": "The browser's speech service isn't reachable. Please type your message instead.",
  "unsupported": "Voice input isn't available in this browser (try Chrome, Edge, or Safari). You can type everything instead.",
};

export function startListening() {
  stopSpeaking();
  if (!SR) {
    setState("error");
    emit("error", ERRORS.unsupported);
    return;
  }
  if (rec) return;
  finalText = "";
  try {
    rec = new SR();
  } catch {
    setState("error");
    emit("error", ERRORS.unsupported);
    return;
  }
  rec.lang = prefs.get().locale || "en-US";
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 1;
  rec.onstart = () => setState("listening");
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }
    emit("interim", (finalText + interim).trim());
  };
  rec.onerror = (e) => {
    const msg = ERRORS[e.error];
    if (e.error === "aborted") return;
    setState("error");
    emit("error", msg || "Voice input stopped unexpectedly. Please try again or type your message.");
  };
  rec.onend = () => {
    rec = null;
    const text = finalText.trim();
    if (state === "listening") setState(text ? "thinking" : "idle");
    if (text) emit("final", text);
  };
  try {
    rec.start();
  } catch {
    rec = null;
    setState("error");
    emit("error", ERRORS["service-not-allowed"]);
  }
}

export function stopListening() {
  if (rec) {
    try { rec.stop(); } catch { /* already stopped */ }
  }
}

// ───────── speech output ─────────

let voices = [];
function loadVoices() { voices = synth ? synth.getVoices() : []; return voices; }
if (synth) {
  loadVoices();
  synth.addEventListener?.("voiceschanged", loadVoices);
}
export function listVoices() { return loadVoices(); }

function pickVoice(p) {
  const all = voices.length ? voices : loadVoices();
  if (p.voiceURI) {
    const chosen = all.find((v) => v.voiceURI === p.voiceURI);
    if (chosen) return chosen;
  }
  const lang = (p.locale || "en-US").toLowerCase();
  return all.find((v) => v.lang?.toLowerCase() === lang && v.localService)
    || all.find((v) => v.lang?.toLowerCase() === lang)
    || all.find((v) => v.lang?.toLowerCase().startsWith(lang.slice(0, 2)))
    || null;
}

let keepAlive;
export function speak(text, { force = false } = {}) {
  if (!text) return false;
  lastSpoken = text;
  const p = prefs.get();
  if (!support.tts || (!p.speechEnabled && !force)) {
    setState("done");
    return false;
  }
  stopSpeaking();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = p.speechRate;
  u.lang = p.locale || "en-US";
  const v = pickVoice(p);
  if (v) u.voice = v;
  u.onstart = () => setState("speaking");
  const finish = () => { clearInterval(keepAlive); if (state === "speaking") setState("done"); };
  u.onend = finish;
  u.onerror = finish;
  // Some Chromium builds stall on long utterances; a periodic resume keeps them going.
  keepAlive = setInterval(() => { if (synth.speaking && !synth.paused) synth.resume(); }, 10000);
  synth.speak(u);
  return true;
}

export function stopSpeaking() {
  clearInterval(keepAlive);
  if (synth && (synth.speaking || synth.pending)) synth.cancel();
  if (state === "speaking") setState("done");
}
export function pause() { if (synth?.speaking) synth.pause(); }
export function resume() { if (synth?.paused) synth.resume(); }
export function replay() { return speak(lastSpoken, { force: true }); }
export function last() { return lastSpoken; }
export function setLast(text) { lastSpoken = text; }
