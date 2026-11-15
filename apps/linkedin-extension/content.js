// Runs on linkedin.com. Reads posts already rendered on screen and what the student
// does with them, then batches them to the Jarvis browser agent (POST /linkedin/observe
// via background.js). READ-ONLY: never clicks, types or posts on LinkedIn. The only thing
// it does to the page is scroll to + briefly outline a post when the student clicks that
// post in the Nova side panel.
(() => {
  const FLUSH_MS = 4000;
  const VISIBLE = 0.6; // fraction of a post on screen to count as "looking at it"

  const known = new Map();      // post id -> last sent text length
  const visibleSince = new Map(); // post id -> ms timestamp
  const elById = new Map();     // post id -> element (for "on screen" + scroll-to)
  let lastOnScreen = "";
  let postQueue = new Map();    // post id -> post object
  let engagements = [];
  let paused = false;

  chrome.storage.local.get({ paused: false }, (c) => (paused = c.paused));
  chrome.storage.onChanged.addListener((ch) => {
    if (ch.paused) paused = ch.paused.newValue;
  });

  function queuePost(el) {
    const post = JarvisParse.parsePost(el);
    if (!post) return null;
    const prev = known.get(post.id);
    if (prev === undefined || post.text.length > prev) {
      known.set(post.id, post.text.length);
      postQueue.set(post.id, post);
    }
    return post;
  }

  function addDwell(id, now) {
    const since = visibleSince.get(id);
    if (since === undefined) return;
    const seconds = (now - since) / 1000;
    if (seconds >= 1) engagements.push({ post_id: id, kind: "dwell", seconds: Math.round(seconds * 10) / 10 });
    visibleSince.set(id, now);
  }

  const io = new IntersectionObserver((entries) => {
    const now = Date.now();
    for (const e of entries) {
      const id = JarvisParse.postId(e.target);
      if (!id) continue;
      elById.set(id, e.target);
      if (e.isIntersecting && e.intersectionRatio >= VISIBLE) {
        queuePost(e.target);
        if (!visibleSince.has(id)) visibleSince.set(id, now);
      } else {
        addDwell(id, now);
        visibleSince.delete(id);
      }
    }
  }, { threshold: [0, VISIBLE] });

  const watched = new WeakSet();
  let watchedCount = 0;
  function scan() {
    document.querySelectorAll(JarvisParse.POST_SELECTOR).forEach((el) => {
      if (watched.has(el)) return;
      // skip nested matches (a reshared post inside a post): watch the outer one only
      if (el.parentElement && el.parentElement.closest(JarvisParse.POST_SELECTOR)) return;
      watched.add(el);
      watchedCount++;
      io.observe(el);
    });
    if (watchedCount !== scan.logged) {
      scan.logged = watchedCount;
      console.info(`[Nova] watching ${watchedCount} LinkedIn posts`);
    }
  }

  let scanTimer = null;
  new MutationObserver(() => {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scan, 400);
  }).observe(document.body, { childList: true, subtree: true });
  scan();

  document.addEventListener("click", (ev) => {
    const postEl = ev.target.closest && ev.target.closest(JarvisParse.POST_SELECTOR);
    if (!postEl) return;
    const kind = JarvisParse.clickKind(ev.target);
    if (!kind) return;
    const post = queuePost(postEl);
    if (!post) return;
    engagements.push({ post_id: post.id, kind });
    // "see more" reveals the full text a moment later: re-read it
    if (kind === "expanded") setTimeout(() => queuePost(postEl), 400);
  }, true);

  // visible posts, the one nearest the middle of the screen first
  function onScreen() {
    const mid = window.innerHeight / 2;
    return [...visibleSince.keys()]
      .map((id) => [id, elById.get(id)])
      .filter(([, el]) => el && el.isConnected)
      .map(([id, el]) => {
        const r = el.getBoundingClientRect();
        return [id, Math.abs((r.top + r.bottom) / 2 - mid)];
      })
      .sort((a, b) => a[1] - b[1])
      .map(([id]) => id);
  }

  function flush() {
    const now = Date.now();
    for (const id of visibleSince.keys()) addDwell(id, now);
    const visible = onScreen();
    const visibleKey = visible.join(",");
    if (paused || (!postQueue.size && !engagements.length && visibleKey === lastOnScreen)) {
      if (paused) { postQueue = new Map(); engagements = []; }
      return;
    }
    lastOnScreen = visibleKey;
    const payload = { posts: [...postQueue.values()], engagements, on_screen: visible };
    postQueue = new Map();
    engagements = [];
    try {
      chrome.runtime.sendMessage({ type: "observe", payload }, () => void chrome.runtime.lastError);
    } catch (_) {
      // extension was reloaded: this old content script is orphaned; stop quietly
      clearInterval(timer);
    }
  }
  // side panel: "show me that post" -> scroll to it and outline it for 2 s
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (!msg || msg.type !== "scrollToPost") return false;
    const el = elById.get(msg.id);
    if (!el || !el.isConnected) { reply({ ok: false }); return false; }
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    const prev = el.style.outline;
    el.style.outline = "2px solid #3fd2ff";
    el.style.outlineOffset = "4px";
    setTimeout(() => { el.style.outline = prev; }, 2000);
    reply({ ok: true });
    return false;
  });

  const timer = setInterval(flush, FLUSH_MS);
  window.addEventListener("pagehide", flush);
})();
