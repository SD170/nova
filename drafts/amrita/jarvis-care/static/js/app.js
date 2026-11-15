// Jarvis Care app shell: router, voice dock, accessibility center, actions.
import { h, announce, copyText, fmtDate } from "./dom.js";
import * as prefs from "./prefs.js";
import * as voice from "./voice.js";
import { api } from "./api.js";
import { consent } from "./components.js";
import * as views from "./views.js";

const ROUTES = {
  "/health": ["home", "Overview", views.home],
  "/health/conversation": ["conversation", "Conversation", views.conversation],
  "/health/care-plan": ["care-plan", "Care plan", views.carePlan],
  "/health/visit-prep": ["visit-prep", "Visit prep", views.visitPrep],
  "/health/bills": ["bills", "Bills", views.billsView],
  "/health/appointments": ["appointments", "Appointments", views.appointments],
  "/health/timeline": ["timeline", "Timeline", views.timelineView],
};

const $ = (id) => document.getElementById(id);
const state = { transcript: [], last: null, plan: null, bill: null, slots: null, academics: false };

// ───────────────────────── routing ─────────────────────────
function currentPath() {
  const p = location.pathname.replace(/\/+$/, "") || "/health";
  return ROUTES[p] ? p : "/health";
}

function render({ focus = false } = {}) {
  const path = currentPath();
  const [key, title, view] = ROUTES[path];
  document.title = `${title} · Jarvis Care · Student Jarvis`;
  for (const a of document.querySelectorAll("#sidenav-list a")) {
    if (a.dataset.route === key) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  view($("view"), ctx);
  if (focus) $("page-title")?.focus();
}

export function navigate(path) {
  if (path !== location.pathname) history.pushState({}, "", path);
  render({ focus: true });
  window.scrollTo(0, 0);
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  const url = new URL(a.href, location.href);
  if (url.origin !== location.origin || !ROUTES[url.pathname.replace(/\/+$/, "") || "/health"]) return;
  e.preventDefault();
  navigate(url.pathname);
});
window.addEventListener("popstate", () => render({ focus: true }));

// ───────────────────────── speech helpers ─────────────────────────
function speakText(text, force = false) {
  if (!text) return;
  setCaption(text);
  const spoke = voice.speak(text, { force });
  if (!spoke && force && !voice.support.tts) announce("Spoken replies aren't available in this browser. The text is on screen.");
}
function replay() { if (!voice.replay()) announce("Nothing to replay yet, or speech isn't available here."); }
function slower() {
  const p = prefs.get();
  const rate = Math.max(0.75, p.speechRate - 0.25);
  prefs.set({ speechRate: rate });
  announce(`Speaking speed ${rate}×.`);
  voice.replay();
}

// ───────────────────────── conversation ─────────────────────────
async function send(text, source = "text", extra = {}) {
  const msg = (text || "").trim();
  if (!msg && !extra.intent) return;
  voice.stopSpeaking();
  if (msg) state.transcript.push({ role: "user", text: msg, source });
  voice.setState("thinking");
  announce("Jarvis is thinking.");
  try {
    const res = await api.ask(msg || undefined, { source, ...extra });
    state.last = res;
    state.transcript.push({ role: "jarvis", res });
    for (const a of res.actions) {
      if (a.kind === "setPreferences") applyPrefAction(a.payload);
      if (a.kind === "openPage" && a.id === "nav") { navigate(a.payload.path); }
    }
    await syncFromResponse(res);
    voice.setState("done");
    const spoken = res.spokenSummary;
    if (prefs.get().speechEnabled && voice.support.tts) {
      announce("Jarvis replied. Speaking now.");
    } else {
      announce(`Jarvis says: ${spoken}`);
    }
    speakText(spoken);
    if (["/health", "/health/conversation"].includes(currentPath())) render();
    refreshLoop();
    return res;
  } catch (e) {
    voice.setState("error");
    setCaption(e.message);
    announce(e.message);
    state.transcript.push({ role: "jarvis", res: { replyText: e.message, spokenSummary: e.message, cards: [], actions: [], isMock: false } });
    if (currentPath() === "/health/conversation") render();
  }
}

// Keep page caches in sync when the conversation changes things.
async function syncFromResponse(res) {
  try {
    if (res.intent === "health.parseAfterVisit" && res.cards.some((c) => c.evidence?.length)) {
      const docId = res.cards.find((c) => c.evidence?.length).evidence[0].docId;
      state.plan = await api.carePlan(docId);
    }
    if (res.intent === "health.compareBill" && res.cards.length && res.cards[0].kind === "billFlag") {
      state.bill = await api.compareBills("sample-bill", "sample-eob").catch(() => state.bill);
    }
  } catch { /* the reply already shows the result */ }
}

function applyPrefAction(p) {
  prefs.set(p);
  syncA11yForm();
}

function editLast(text) {
  const input = $("voice-input");
  input.value = text;
  input.focus();
  announce("Your last message is in the message box. Edit it, then press Send.");
}

// ───────────────────────── actions (approval-gated) ─────────────────────────
async function reminderFlow({ title, dueDate, sourceCardId }) {
  const { confirmed, values } = await consent({
    title: "Save this reminder?",
    summary: [["Reminder", title], ["Date", dueDate ? fmtDate(dueDate) : "No date in your document"], ["Where it's saved", "Jarvis Care, this session only"]],
    fields: [{ name: "title", label: "Reminder text (you can edit it)", value: title }],
    note: "No phone, email or calendar notification is sent. Nothing is saved until you press Save reminder.",
    confirmLabel: "Save reminder",
  });
  if (!confirmed) return false;
  try {
    await api.saveReminder({ title: values.title || title, dueDate, sourceCardId });
    announce("Reminder saved. It's on your care timeline.");
    speakText("Saved. Your reminder is on your care timeline.");
    if (currentPath() === "/health/care-plan") render();
    refreshLoop();
    return true;
  } catch (e) { announce(e.message); return false; }
}

async function planFlow(slot) {
  const { confirmed } = await consent({
    title: "Plan this follow-up time?",
    summary: [["Time", slot.label], ["What happens", "It's added to your Jarvis Care timeline as a planned time."]],
    note: "Demo — no real appointment is booked and no clinic is contacted. Call the clinic to book.",
    confirmLabel: "Add to my timeline",
  });
  if (!confirmed) return;
  try {
    await api.planVisit(slot);
    announce("Planned. No real appointment was booked.");
    speakText(`Done. I added ${slot.label} to your care timeline. No real appointment was booked.`);
    refreshLoop();
  } catch (e) { announce(e.message); }
}

async function perform(action) {
  const p = action.payload || {};
  switch (action.kind) {
    case "openPage": return navigate(p.path || "/health");
    case "useSample":
      if (p.documentId) return send("", "ui", { intent: "health.parseAfterVisit", documentIds: [p.documentId] });
      if (p.documentIds) return send("", "ui", { intent: "health.compareBill", documentIds: p.documentIds });
      if (p.schedule) return send("", "ui", { intent: "health.planAppointment", permittedContext: { useDemoSchedule: true } });
      return;
    case "saveReminder": return reminderFlow(p);
    case "confirmAppointment": return planFlow(p);
    case "copyQuestions": {
      const ok = await copyText((p.questions || []).join("\n\n"));
      return announce(ok ? "Copied to your clipboard." : "Couldn't copy. Select the text and copy it instead.");
    }
    case "setPreferences": return applyPrefAction(p);
    default: return undefined;
  }
}

async function loadSamplePlan() {
  try {
    state.plan = await api.carePlan("sample-after-visit");
    speakText(state.plan.spokenSummary);
    navigate("/health/care-plan");
    refreshLoop();
  } catch (e) { announce(e.message); }
}

// ───────────────────────── voice dock ─────────────────────────
function setCaption(text) { $("dock-caption-text").textContent = text; }

function toggleMic() {
  if (voice.isListening()) voice.stopListening(); else voice.startListening();
}

voice.on("state", (s) => {
  $("voice-dock").dataset.state = s;
  $("voice-state-label").textContent = voice.stateLabel(s);
  const listening = s === "listening";
  const mic = $("mic-btn");
  mic.dataset.listening = String(listening);
  $("mic-label").textContent = listening ? "Stop" : "Talk";
  mic.setAttribute("aria-label", listening ? "Stop listening" : "Talk to Jarvis");
  const hero = document.querySelector(".hero__mic");
  if (hero) { hero.dataset.listening = String(listening); hero.querySelector("span").textContent = listening ? "Stop listening" : "Talk to Jarvis"; }
  if (listening) announce("Listening. Microphone on. Press Stop when you're done.");
});
voice.on("interim", (t) => { $("voice-input").value = t; });
voice.on("final", (t) => {
  if (prefs.get().reviewSpeech) {
    $("voice-input").value = t;
    $("voice-input").focus();
    voice.setState("idle");
    announce("Check what I heard, then press Send.");
  } else {
    $("voice-input").value = "";
    send(t, "voice");
  }
});
voice.on("error", (msg) => { setCaption(msg); $("voice-hint").textContent = msg; announce(msg); });

$("mic-btn").addEventListener("click", toggleMic);
$("voice-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("voice-input");
  const text = input.value;
  input.value = "";
  $("voice-hint").textContent = "";
  send(text, "text");
});
$("replay-btn").addEventListener("click", replay);
$("slower-btn").addEventListener("click", slower);
$("stop-audio-btn").addEventListener("click", () => { voice.stopSpeaking(); announce("Stopped speaking."); });
$("mute-btn").addEventListener("click", () => {
  prefs.set({ speechEnabled: !prefs.get().speechEnabled });
  announce(prefs.get().speechEnabled ? "Spoken replies on." : "Spoken replies off. Everything stays on screen.");
});
function syncMute() {
  const muted = !prefs.get().speechEnabled;
  $("mute-btn").setAttribute("aria-pressed", String(muted));
  $("mute-btn").querySelector("span").textContent = muted ? "Replies muted" : "Mute replies";
  if (muted) voice.stopSpeaking();
}

// Keep page content clear of the sticky dock.
new ResizeObserver(() => {
  const sticky = getComputedStyle($("voice-dock")).position === "sticky";
  document.documentElement.style.setProperty("--dock-h", sticky ? `${$("voice-dock").offsetHeight}px` : "0px");
}).observe($("voice-dock"));

// ───────────────────────── accessibility center ─────────────────────────
const form = $("a11y-form");
function syncA11yForm() {
  const p = prefs.get();
  form.elements.textScale.value = String(p.textScale);
  form.elements.theme.value = p.theme;
  form.elements.highContrast.checked = p.highContrast;
  form.elements.reduceMotion.checked = p.reduceMotion;
  form.elements.speechEnabled.checked = p.speechEnabled;
  form.elements.speechRate.value = String(p.speechRate);
  $("rate-out").textContent = `${p.speechRate}×`;
  form.elements.reviewSpeech.checked = p.reviewSpeech;
  form.elements.language.value = p.simpleLanguage ? "simple" : "detailed";
  form.elements.locale.value = p.locale;
  form.elements.voiceURI.value = p.voiceURI;
  syncMute();
}
function fillVoices() {
  const sel = form.elements.voiceURI;
  const current = prefs.get().voiceURI;
  sel.replaceChildren(h("option", { value: "" }, "Default voice"),
    ...voice.listVoices().filter((v) => v.lang?.startsWith("en") || v.lang?.startsWith("es"))
      .map((v) => h("option", { value: v.voiceURI }, `${v.name} (${v.lang})`)));
  sel.value = current;
}
window.speechSynthesis?.addEventListener?.("voiceschanged", fillVoices);

form.addEventListener("change", (e) => {
  const el = e.target;
  const patch = {};
  if (el.name === "textScale") patch.textScale = Number(el.value);
  else if (el.name === "theme") patch.theme = el.value;
  else if (el.name === "language") patch.simpleLanguage = el.value === "simple";
  else if (el.type === "checkbox") patch[el.name] = el.checked;
  else if (el.name === "speechRate") patch.speechRate = Number(el.value);
  else if (el.name) patch[el.name] = el.value;
  prefs.set(patch);
  syncA11yForm();
  announce("Setting saved.");
});
form.elements.speechRate.addEventListener("input", (e) => { $("rate-out").textContent = `${e.target.value}×`; });
$("open-a11y").addEventListener("click", () => { syncA11yForm(); fillVoices(); $("a11y-dialog").showModal(); });
$("a11y-dialog").addEventListener("close", () => $("open-a11y").focus());
$("reset-prefs").addEventListener("click", () => { prefs.reset(); syncA11yForm(); announce("Settings reset."); });
$("test-voice").addEventListener("click", () => speakText("Hi, I'm Jarvis. This is how I sound.", true));
$("pause-voice").addEventListener("click", voice.pause);
$("resume-voice").addEventListener("click", voice.resume);
$("tts-support").textContent = voice.support.tts ? "" : "Spoken replies aren't available in this browser. All answers are shown as text.";
$("stt-support").textContent = voice.support.stt
  ? "Jarvis only listens after you press Talk, and stops when you press Stop or finish speaking."
  : "Voice input isn't available in this browser. You can type everything.";
prefs.onChange(syncMute);

// ───────────────────────── care loop + privacy ─────────────────────────
async function refreshLoop() {
  const body = $("careloop-body");
  try {
    const { items } = await api.timeline(false);
    body.replaceChildren(items.length
      ? h("ol", {}, items.slice(0, 4).map((it) => h("li", {},
          h("p", { class: "eyebrow", style: "margin:0" }, it.type),
          h("p", { style: "margin:0;font-weight:700" }, it.title),
          it.when ? h("p", { class: "muted", style: "margin:0" }, fmtDate(it.when)) : null)))
      : h("p", { class: "muted" }, "Nothing planned yet. Your reminders and next steps will show up here."),
      h("p", { style: "margin-top:1rem" }, h("a", { href: "/health/timeline", "data-link": "" }, "Open full timeline")));
  } catch { body.replaceChildren(h("p", { class: "muted" }, "Your care loop is unavailable right now.")); }
}

$("clear-data").addEventListener("click", async () => {
  const { confirmed } = await consent({
    title: "Clear your Jarvis Care data?",
    summary: [["This deletes", "Documents you uploaded, check-ins, questions, reminders and planned visits for this session."]],
    note: "Accessibility settings stay in this browser.",
    confirmLabel: "Clear my data",
  });
  if (!confirmed) return;
  try {
    await api.clear();
    Object.assign(state, { transcript: [], last: null, plan: null, bill: null, slots: null });
    render();
    refreshLoop();
    announce("Your Jarvis Care data was deleted.");
  } catch (e) { announce(e.message); }
});

const ctx = {
  state, send, perform, navigate, speakText, replay, slower, toggleMic, editLast,
  reminderFlow, planFlow, loadSamplePlan, refreshLoop, rerender: () => render(),
};

api.config().then((c) => { if (c.jarvisHomeUrl) $("academics-link").href = c.jarvisHomeUrl; }).catch(() => {});
syncA11yForm();
render();
refreshLoop();
