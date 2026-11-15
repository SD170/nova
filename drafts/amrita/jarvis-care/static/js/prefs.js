// Accessibility preferences — non-sensitive, persisted in this browser only.

const KEY = "jarvisCare.prefs.v1";
export const DEFAULTS = Object.freeze({
  textScale: 1,
  theme: "system",
  highContrast: false,
  reduceMotion: false,
  speechEnabled: true,
  speechRate: 1,
  voiceURI: "",
  reviewSpeech: false,
  simpleLanguage: true,
  locale: "en-US",
});
const SCALES = [1, 1.25, 1.5, 2];

let prefs = { ...DEFAULTS };
const listeners = new Set();

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) prefs = { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { /* storage blocked: defaults still work */ }
  sanitize();
}

function sanitize() {
  if (!SCALES.includes(Number(prefs.textScale))) prefs.textScale = 1;
  prefs.textScale = Number(prefs.textScale);
  prefs.speechRate = Math.min(1.5, Math.max(0.75, Number(prefs.speechRate) || 1));
  if (!["system", "light", "dark"].includes(prefs.theme)) prefs.theme = "system";
}

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* ignore */ }
}

export function apply() {
  const root = document.documentElement;
  root.style.setProperty("--text-scale", String(prefs.textScale));
  root.dataset.theme = prefs.theme;
  if (prefs.highContrast) root.dataset.contrast = "high"; else delete root.dataset.contrast;
  if (prefs.reduceMotion) root.dataset.motion = "reduce"; else delete root.dataset.motion;
  root.lang = "en"; // UI text is English; prefs.locale only changes the speech voice.
}

export function get() { return { ...prefs }; }

export function set(patch) {
  prefs = { ...prefs, ...patch };
  sanitize();
  save();
  apply();
  for (const fn of listeners) fn(get(), patch);
}

export function reset() { set({ ...DEFAULTS }); }
export function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function reducedMotion() {
  return prefs.reduceMotion || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

load();
apply();
