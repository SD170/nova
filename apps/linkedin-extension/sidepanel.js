// Nova side panel: Nova on top, then what Nova made for you (drafts / research, by voice
// or by a click here), then activity, people, companies, posts, interests.
// All LinkedIn and web text is untrusted: rendered with textContent only, never innerHTML.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    summary: null, activity: [], posts: [], cards: [],
    shownCard: null,        // id of the card in the big slot
    dismissed: new Set(),   // cards the student closed
    openRows: new Set(),    // expanded people/company rows
    connected: false, paused: false,
  };

  // ---------- tiny DOM helper ----------
  function h(tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const link = (text, url) => url
    ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", onclick: (e) => e.stopPropagation() }, text)
    : text;

  function ago(iso) {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 45) return "now";
    if (s < 3600) return `${Math.round(s / 60)}m`;
    return `${Math.round(s / 3600)}h`;
  }

  function copyBtn(text) {
    const b = h("button", { class: "ghost", title: "Copy" }, "Copy");
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      await navigator.clipboard.writeText(text);
      b.textContent = "Copied";
      setTimeout(() => (b.textContent = "Copy"), 1200);
    });
    return b;
  }
  const option = (text) => h("div", { class: "opt" }, h("p", {}, text), copyBtn(text));

  // ---------- Nova figure ----------
  let clip = "idle";
  function setNova(next) {
    if (next === clip) return;
    clip = next;
    const v = $("nova");
    v.src = `media/nova-${next}.webm`;
    v.play().catch(() => {});
  }

  // ---------- actions (same endpoints Nova's voice tools use) ----------
  async function act(fn) {
    try { await fn(); } catch (e) { flash("Nova couldn't do that: " + e.message); }
    refreshCards();
  }
  const draftFor = (body) => act(async () => {
    setNova("thinking");
    const card = await JarvisApi.call("POST", "/linkedin/cards/draft", body);
    state.shownCard = card.id;
  });
  const research = (body) => act(async () => {
    const card = await JarvisApi.call("POST", "/linkedin/research", body);
    state.shownCard = card.id;
  });

  async function showPost(postId, fallbackUrl) {
    try {
      const tabs = await chrome.tabs.query({ url: "https://www.linkedin.com/*" });
      const tab = tabs.find((t) => t.active) || tabs[0];
      if (tab) {
        const res = await chrome.tabs.sendMessage(tab.id, { type: "scrollToPost", id: postId });
        if (res && res.ok) { chrome.tabs.update(tab.id, { active: true }); return; }
      }
    } catch (_) { /* tab gone or content script not loaded */ }
    if (fallbackUrl) chrome.tabs.create({ url: fallbackUrl });
    else flash("That post isn't on your LinkedIn page anymore.");
  }

  function flash(msg) {
    $("statusText").textContent = msg.slice(0, 80);
    setTimeout(renderStatus, 3500);
  }

  // ---------- render: status ----------
  function renderStatus() {
    const s = state.summary;
    const dot = $("dot");
    if (!state.connected) {
      dot.className = "dot bad";
      $("statusText").textContent = "NOVA · NOT CONNECTED";
      $("counts").textContent = "Open ⚙ and check the URL and key.";
      return;
    }
    dot.className = "dot " + (state.paused ? "paused" : "ok");
    $("statusText").textContent = state.paused ? "NOVA · PAUSED" : "NOVA · READING LINKEDIN";
    const liked = state.activity.filter((a) => a.kind === "liked").length;
    $("counts").replaceChildren(
      h("b", {}, s ? s.posts_seen : 0), " posts · ",
      h("b", {}, liked), " liked · ",
      h("b", {}, s ? s.people.length : 0), " to reach out to");
    $("pauseBtn").classList.toggle("on", state.paused);
    $("pauseBtn").textContent = state.paused ? "▶" : "❚❚";
    $("pauseBtn").title = state.paused ? "Resume reading" : "Pause reading";
  }

  // ---------- render: Nova card ----------
  function renderCard() {
    const slot = $("novaCard");
    const visible = state.cards.filter((c) => !state.dismissed.has(c.id));
    const card = visible.find((c) => c.id === state.shownCard) || visible[0];
    if (!card) { slot.hidden = true; $("earlier").replaceChildren(); return; }
    state.shownCard = card.id;
    slot.hidden = false;
    const close = h("button", { class: "card-x", title: "Close", onclick: () => {
      state.dismissed.add(card.id); state.shownCard = null; renderCard(); } }, "×");
    const head = h("div", { class: "card-head" },
      h("span", { class: "card-tag" }, card.kind === "research" ? "RESEARCH" : "DRAFT"),
      h("span", { class: "card-title" }, card.title), close);

    let body;
    if (card.status === "working") {
      body = h("div", { class: "working" }, h("span", { class: "spinner" }),
        card.kind === "research" ? "Looking up the company and CEO…" : "Writing…");
    } else if (card.status === "failed") {
      body = h("div", { class: "err" }, card.error || "Something went wrong.");
    } else if (card.drafts) {
      const d = card.drafts;
      body = [
        d.comments.length ? [h("div", { class: "label" }, "Comment"), d.comments.map(option)] : null,
        d.connection_note || d.dm ? h("div", { class: "label" }, "Reach out") : null,
        d.connection_note ? option(d.connection_note) : null,
        d.dm ? option(d.dm) : null,
        d.source === "template" ? h("p", { class: "hint" }, "Template (AI unavailable). Edit before sending.") : null,
        card.post_id ? h("div", { class: "row", style: "margin-top:6px" },
          h("button", { class: "ghost", onclick: () => showPost(card.post_id) }, "Show post"),
          h("button", { class: "ghost", onclick: () => draftFor({ post_id: card.post_id, kind: "both" }) }, "Redraft")) : null,
      ];
    } else if (card.research) {
      const r = card.research;
      body = [
        h("p", { class: "brief" }, r.summary),
        r.ceo_name || r.ceo_linkedin_url ? h("div", { class: "ceo" },
          h("span", {}, "CEO: ", h("b", {}, r.ceo_name || "unknown")),
          r.ceo_linkedin_url ? h("a", { class: "ghost", href: r.ceo_linkedin_url, target: "_blank",
            rel: "noopener noreferrer", style: "text-decoration:none" }, "LinkedIn ↗") : null) : null,
        r.messages.length ? [h("div", { class: "label" }, "Message to the CEO"), r.messages.map(option)] : null,
        r.sources.length ? h("div", { class: "sources" }, "Sources: ",
          r.sources.slice(0, 3).map((s, i) => [i ? " · " : "", link(new URL(s.url).hostname.replace(/^www\./, ""), s.url)])) : null,
      ];
    }
    slot.replaceChildren(head, h("div", {}, body));

    const others = visible.filter((c) => c.id !== card.id).slice(0, 4);
    $("earlier").replaceChildren(...others.map((c) => h("button", {
      title: c.title, onclick: () => { state.shownCard = c.id; renderCard(); } },
      `${c.kind === "research" ? "◎" : "✎"} ${c.title.replace(/^(Comment \+ reach-out|Comment|Reach-out) for /, "")} · ${ago(c.created_at)}`)));
  }

  // ---------- render: sections ----------
  const VERB = { liked: ["♥", "Liked"], commented: ["✎", "Opened comments on"], reposted: ["⟳", "Reposted"],
                 expanded: ["⤢", "Read more of"], profile_click: ["◉", "Opened profile of"], read: ["◷", "Read"] };

  function renderActivity() {
    const list = state.activity.slice(0, 8);
    $("nActivity").textContent = state.activity.length || "";
    $("activity").replaceChildren(...(list.length ? list.map((a) => {
      const [ic, verb] = VERB[a.kind] || ["•", a.kind];
      return h("li", {}, h("div", { class: "line", title: "Show this post", onclick: () => showPost(a.post_id) },
        h("span", { class: "ic" }, ic),
        h("div", { class: "main" },
          h("div", { class: "t" }, verb, " ", h("b", {}, a.author_name)),
          a.snippet ? h("div", { class: "s" }, a.snippet) : null),
        h("span", { class: "when" }, ago(a.at))));
    }) : [h("li", { class: "empty" }, "Like, comment on or read a post and it shows up here.")]));
  }

  function toggleRow(key) {
    state.openRows.has(key) ? state.openRows.delete(key) : state.openRows.add(key);
    renderPeople(); renderCompanies();
  }

  function renderPeople() {
    const people = (state.summary && state.summary.people) || [];
    $("nPeople").textContent = people.length || "";
    $("people").replaceChildren(...(people.length ? people.slice(0, 6).map((p) => {
      const key = "p:" + (p.profile_url || p.name);
      const open = state.openRows.has(key);
      const postId = p.post_ids[p.post_ids.length - 1];
      return h("li", {},
        h("div", { class: "line", onclick: () => toggleRow(key) },
          h("span", { class: "ic" }, open ? "▾" : "▸"),
          h("div", { class: "main" },
            h("div", { class: "t" }, h("b", {}, p.name), p.company ? ` · ${p.company}` : ""),
            h("div", { class: "s" }, p.headline)),
          h("span", { class: "badge" }, p.reasons.some((r) => /recruit|hiring/i.test(r)) ? "hiring"
            : p.reasons.some((r) => /founder/i.test(r)) ? "founder" : "engaged")),
        open ? h("div", { class: "more" },
          h("div", { class: "why" }, p.reasons.join(" · ")),
          h("div", { class: "row" },
            h("button", { class: "primary", onclick: () => draftFor({ post_id: postId, kind: "dm" }) }, "Draft reach-out"),
            h("button", { class: "ghost", onclick: () => draftFor({ post_id: postId, kind: "comment" }) }, "Draft comment"),
            p.company ? h("button", { class: "ghost", onclick: () => research({ company: p.company }) }, `Research ${p.company}`) : null,
            p.profile_url ? h("a", { class: "ghost", href: p.profile_url, target: "_blank",
              rel: "noopener noreferrer", style: "text-decoration:none" }, "Profile ↗") : null)) : null);
    }) : [h("li", { class: "empty" }, "Nobody yet. Like or read a few posts from recruiters or founders.")]));
  }

  function renderCompanies() {
    const cos = (state.summary && state.summary.companies) || [];
    $("nCompanies").textContent = cos.length || "";
    $("companies").replaceChildren(...(cos.length ? cos.map((c) => h("li", {},
      h("div", { class: "line", title: `Research ${c.name}`, onclick: () => research({ company: c.name }) },
        h("span", { class: "ic" }, "◎"),
        h("div", { class: "main" }, h("div", { class: "t" }, h("b", {}, c.name)),
          h("div", { class: "s" }, `${c.posts} post${c.posts === 1 ? "" : "s"} in your feed`)),
        h("span", { class: "badge" }, "Research")))) : [h("li", { class: "empty" }, "No companies yet.")]));
  }

  function renderPosts() {
    const posts = state.posts;
    $("nPosts").textContent = posts.length || "";
    $("posts").replaceChildren(...(posts.length ? posts.map((p) => {
      const first = (p.text || "").split(/(?<=[.!?])\s/)[0].slice(0, 110);
      return h("li", {}, h("div", { class: "line", title: "Show this post on LinkedIn",
        onclick: () => showPost(p.id, p.post_url || p.author_url) },
        h("span", { class: "ic" }, p.signals && p.signals.liked ? "♥" : "◷"),
        h("div", { class: "main" }, h("div", { class: "t" }, h("b", {}, p.author_name)),
          h("div", { class: "s" }, first || p.author_headline)),
        h("button", { class: "ghost", onclick: (e) => { e.stopPropagation(); draftFor({ post_id: p.id, kind: "comment" }); } }, "Comment")));
    }) : [h("li", { class: "empty" }, "Posts you like or read show up here.")]));
  }

  function renderInterests() {
    const ints = (state.summary && state.summary.interests) || [];
    $("interests").replaceChildren(...(ints.length
      ? ints.map((i) => h("span", { class: "chip", title: `${i.post_count} post(s)` }, i.topic))
      : [h("span", { class: "empty" }, "—")]));
  }

  function renderAll() {
    renderStatus(); renderCard(); renderActivity(); renderPeople();
    renderCompanies(); renderPosts(); renderInterests();
  }

  // ---------- polling ----------
  let lastNewest = null;
  async function refreshCards() {
    try {
      const { cards } = await JarvisApi.call("GET", "/linkedin/cards?limit=10");
      const newest = cards[0];
      // a card Nova just made (e.g. by voice) jumps to the big slot
      if (newest && newest.id !== lastNewest) {
        if (lastNewest !== null) state.shownCard = newest.id;
        lastNewest = newest.id;
      }
      state.cards = cards;
      setNova(cards.some((c) => c.status === "working") ? "thinking" : "idle");
      renderCard();
    } catch (_) { /* refreshData reports connection problems */ }
  }

  let loading = false;
  async function refreshData() {
    if (loading) return;
    loading = true;
    try {
      const [summary, act, posts] = await Promise.all([
        JarvisApi.call("GET", "/linkedin/summary?max_people=6"),
        JarvisApi.call("GET", "/linkedin/activity?limit=30"),
        JarvisApi.call("GET", "/linkedin/posts?limit=12&engaged_only=true"),
      ]);
      Object.assign(state, { summary, activity: act.activity, posts: posts.posts, connected: true });
    } catch (e) {
      state.connected = false;
    } finally {
      loading = false;
    }
    renderAll();
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === "observed") refreshData();
  });

  // ---------- controls ----------
  $("gear").addEventListener("click", () => ($("settings").hidden = !$("settings").hidden));
  $("pauseBtn").addEventListener("click", () => {
    state.paused = !state.paused;
    chrome.storage.local.set({ paused: state.paused });
    renderStatus();
  });
  $("save").addEventListener("click", async () => {
    await chrome.storage.local.set({ apiBase: $("apiBase").value.trim() || JarvisApi.DEFAULTS.apiBase,
                                     apiKey: $("apiKey").value.trim() });
    try {
      const hl = await JarvisApi.call("GET", "/health");
      await JarvisApi.call("GET", "/linkedin/summary?max_people=1"); // checks the key too
      $("settingsMsg").textContent = `Connected (llm: ${hl.llm}).`;
      refreshData(); refreshCards();
    } catch (e) {
      $("settingsMsg").textContent = "Failed: " + e.message;
    }
  });
  $("clear").addEventListener("click", async () => {
    if (!confirm("Forget everything from this LinkedIn session?")) return;
    try {
      await JarvisApi.call("DELETE", "/linkedin/session");
      refreshData();
    } catch (e) {
      $("settingsMsg").textContent = "Failed: " + e.message;
    }
  });

  chrome.storage.local.get({ ...JarvisApi.DEFAULTS, paused: false }, (c) => {
    $("apiBase").value = c.apiBase;
    $("apiKey").value = c.apiKey;
    state.paused = c.paused;
    refreshData(); refreshCards();
  });
  setInterval(refreshCards, 3000);   // voice results show up within ~3 s
  setInterval(refreshData, 8000);
})();
