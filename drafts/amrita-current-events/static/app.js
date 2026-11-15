// Current events page: interests, live feed, browser notifications, spoken digest.
const $ = (id) => document.getElementById(id);
const REFRESH_MS = 5 * 60 * 1000;
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked */ } },
};

let interests = store.get("jarvisNews.interests", null);
let seen = new Set(store.get("jarvisNews.seen", []));
let filter = "All";
let last = null;

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c);
  return el;
}

function announce(msg) { $("live").textContent = ""; setTimeout(() => { $("live").textContent = msg; }, 50); }

function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} hr ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const KIND = { topic: "Topic", sports: "Sports", course: "Course", tech: "Tech" };

function saveInterests() { store.set("jarvisNews.interests", interests); }

function renderChips() {
  $("chips").replaceChildren(...interests.map((it, idx) => h("li", { class: "chip", "data-on": String(it.on !== false) },
    h("button", { type: "button", class: "chip__toggle", "aria-pressed": String(it.on !== false),
      onclick: () => { it.on = it.on === false; saveInterests(); renderChips(); load(); } },
      it.label, h("span", { class: "chip__kind" }, KIND[it.kind] || "")),
    h("button", { type: "button", class: "chip__remove", "aria-label": `Remove ${it.label}`,
      onclick: () => { interests.splice(idx, 1); saveInterests(); renderChips(); load(); announce(`${it.label} removed.`); } }, "×"))));
}

function renderTabs(items) {
  const topics = ["All", ...new Set(items.map((i) => i.topic))];
  if (!topics.includes(filter)) filter = "All";
  $("tabs").replaceChildren(...topics.map((t) => h("button", { type: "button", class: "tab", "aria-pressed": String(t === filter),
    onclick: () => { filter = t; renderFeed(); } }, t)));
}

function renderFeed() {
  if (!last) return;
  renderTabs(last.items);
  const items = last.items.filter((i) => filter === "All" || i.topic === filter);
  $("cards").replaceChildren(...(items.length ? items.map((i) => h("li", { class: "card" },
    h("p", { class: "card__topic" }, i.topic, i._new ? h("span", { class: "new" }, "New") : null),
    h("h3", { class: "card__title" }, h("a", { href: i.url, target: "_blank", rel: "noopener noreferrer" }, i.title)),
    i.summary ? h("p", { class: "card__summary" }, i.summary) : null,
    h("p", { class: "card__meta" }, `${i.source} · ${ago(i.published_at)}`)))
    : [h("li", { class: "card card--empty" }, "No headlines for these interests right now. Try adding another topic.")]));
}

async function load({ notify = false } = {}) {
  const active = interests.filter((i) => i.on !== false);
  if (!active.length) {
    last = { items: [], speak: "Turn on at least one interest to see headlines." };
    $("digest-text").textContent = last.speak;
    renderFeed();
    return;
  }
  $("meta").textContent = "Refreshing…";
  try {
    const r = await fetch("/news/digest", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interests: active, per_topic: 5 }) });
    if (!r.ok) throw new Error();
    last = await r.json();
  } catch {
    $("meta").textContent = "Couldn't reach the news service. Showing the last headlines I had.";
    return;
  }
  const fresh = last.items.filter((i) => !seen.has(i.id));
  const firstRun = seen.size === 0;
  for (const i of last.items) { i._new = !firstRun && !seen.has(i.id); seen.add(i.id); }
  store.set("jarvisNews.seen", [...seen].slice(-600));
  $("digest-text").textContent = last.speak;
  const failed = last.sources.filter((s) => !s.ok).map((s) => s.topic);
  $("meta").textContent = `Updated ${new Date(last.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
    + (failed.length ? ` · couldn't load: ${failed.join(", ")}` : "");
  renderFeed();
  if (notify && !firstRun && fresh.length) {
    announce(`${fresh.length} new headline${fresh.length === 1 ? "" : "s"}.`);
    sendNotifications(fresh);
  }
}

// ───────── notifications ─────────
function notifyOn() { return store.get("jarvisNews.notify", false) && "Notification" in window && Notification.permission === "granted"; }
function syncNotifyBtn() {
  const on = notifyOn();
  $("notify-btn").setAttribute("aria-pressed", String(on));
  $("notify-btn").textContent = on ? "Notifications on" : "Turn on notifications";
}
function sendNotifications(items) {
  if (!notifyOn()) return;
  for (const i of items.slice(0, 3)) {
    const n = new Notification(`${i.topic}: ${i.title}`, { body: `${i.source} · tap to read`, tag: i.id });
    n.onclick = () => { window.open(i.url, "_blank", "noopener"); n.close(); };
  }
  if (items.length > 3) new Notification(`Jarvis: ${items.length - 3} more new headlines`, { tag: "more" });
}
$("notify-btn").addEventListener("click", async () => {
  if (!("Notification" in window)) { announce("This browser doesn't support notifications."); return; }
  if (notifyOn()) { store.set("jarvisNews.notify", false); syncNotifyBtn(); announce("Notifications off."); return; }
  const p = await Notification.requestPermission();
  store.set("jarvisNews.notify", p === "granted");
  syncNotifyBtn();
  if (p === "granted") {
    new Notification("Jarvis news notifications are on", { body: "I'll let you know when new headlines match your interests." });
    announce("Notifications on.");
  } else announce("Notifications are blocked. You can allow them in your browser's site settings.");
});

// ───────── spoken digest ─────────
$("speak-btn").addEventListener("click", () => {
  if (!("speechSynthesis" in window) || !last) { announce("Reading aloud isn't available here."); return; }
  if (speechSynthesis.speaking) { speechSynthesis.cancel(); $("speak-btn").textContent = "Read my digest aloud"; return; }
  const u = new SpeechSynthesisUtterance(last.speak);
  u.onend = u.onerror = () => { $("speak-btn").textContent = "Read my digest aloud"; };
  speechSynthesis.speak(u);
  $("speak-btn").textContent = "Stop reading";
});

// ───────── add interest ─────────
$("add-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const label = $("add-label").value.trim();
  if (!label) return;
  if (interests.some((i) => i.label.toLowerCase() === label.toLowerCase())) { announce(`${label} is already in your interests.`); return; }
  interests.push({ label, kind: $("add-kind").value, query: label, on: true });
  saveInterests();
  $("add-label").value = "";
  renderChips();
  announce(`${label} added.`);
  load();
});

// ───────── ambient particles (decorative; still when reduced motion) ─────────
function ambient() {
  const c = document.querySelector(".ambient"), ctx = c.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W, H, motes = [];
  const mk = (any) => ({ x: Math.random() * W, y: any ? Math.random() * H : H + 20, d: Math.random(), p: Math.random() * 6.28, warm: Math.random() < 0.12 });
  const size = () => {
    const dpr = Math.min(devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight;
    c.width = W * dpr; c.height = H * dpr; c.style.width = `${W}px`; c.style.height = `${H}px`; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    motes = Array.from({ length: Math.round(Math.min(60, (W * H) / 28000)) }, () => mk(true));
  };
  let lastT = 0;
  const frame = (t) => {
    const dt = Math.min(0.05, (t - lastT) / 1000 || 0); lastT = t;
    ctx.clearRect(0, 0, W, H); ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < motes.length; i++) {
      const m = motes[i]; m.y -= (4 + m.d * 12) * dt; if (m.y < -30) motes[i] = mk(false);
      const x = m.x + Math.sin(t / 1000 * (0.15 + m.d * 0.3) + m.p) * (6 + m.d * 14);
      const a = (0.25 + m.d * 0.5) * (0.55 + 0.45 * Math.sin(t / 1000 * 0.8 + m.p)), r = (0.6 + m.d * 2.4) * 6;
      const col = m.warm ? "255,236,170" : "140,255,200";
      const g = ctx.createRadialGradient(x, m.y, 0, x, m.y, r);
      g.addColorStop(0, `rgba(${col},${a})`); g.addColorStop(0.35, `rgba(${col},${a * 0.35})`); g.addColorStop(1, `rgba(${col},0)`);
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, m.y, r, 0, 6.28); ctx.fill();
    }
    if (!still && !document.hidden) requestAnimationFrame(frame);
  };
  size(); addEventListener("resize", size);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !still) requestAnimationFrame(frame); });
  requestAnimationFrame(frame);
}

// ───────── start ─────────
(async () => {
  if (!interests) {
    try { interests = (await (await fetch("/news/interests")).json()).items.map((i) => ({ ...i, on: true })); }
    catch { interests = [{ label: "World", kind: "topic", section: "WORLD", on: true }]; }
    saveInterests();
  }
  renderChips();
  syncNotifyBtn();
  ambient();
  await load();
  setInterval(() => load({ notify: true }), REFRESH_MS);
})();
