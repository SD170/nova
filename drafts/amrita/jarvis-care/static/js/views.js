// Page views. Each render(root, ctx) builds the page from ctx.state and the API.
import { h, icon, announce, fmtDate, copyText } from "./dom.js";
import { api } from "./api.js";
import * as voice from "./voice.js";
import {
  PageHead, JarvisReply, ResponseCard, StatusBadge, DemoBadge, DocumentEvidence, Notice, Loading, consent,
} from "./components.js";

// replaceChildren() would print "null" for skipped optional sections.
const fill = (root, ...kids) => root.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));

const errBox =(e) => Notice("error", "Sorry —", e.message || String(e));

function replyOpts(ctx) {
  return { perform: ctx.perform, speak: ctx.speakText, replay: ctx.replay, slower: ctx.slower };
}

// ───────────────────────── Home ─────────────────────────
const EXAMPLES = [
  "I don't understand my doctor's instructions. What's next?",
  "Does my hospital bill match what insurance says?",
  "Find time next week for a follow-up, but I have a Monday exam.",
  "Make the text bigger and speak more slowly.",
];

export async function home(root, ctx) {
  const listening = voice.isListening();
  const next = h("div", {}, Loading("Finding your next step…"));
  fill(root,
    h("section", { class: "card hero", "aria-labelledby": "page-title" },
      h("div", {},
        h("p", { class: "eyebrow" }, "Jarvis Care"),
        h("h1", { id: "page-title", tabindex: "-1" }, "Hello, how can I help today?"),
        h("p", { class: "muted" }, "Your health, one step at a time. Speak naturally or type your question — Jarvis answers out loud and on screen."),
        h("p", { class: "muted" }, "Prefer typing? ", h("a", { href: "#voice-input" }, "Go to the message box"), "."),
      ),
      h("button", { type: "button", class: "hero__mic", "data-listening": String(listening), onclick: ctx.toggleMic },
        icon("mic"), h("span", {}, listening ? "Stop listening" : "Talk to Jarvis")),
    ),
    h("section", { class: "section", "aria-labelledby": "next-title", style: "margin-top:1.5rem" },
      h("h2", { id: "next-title" }, "Your next step"), next),
    ctx.state.last ? h("section", { class: "section", "aria-labelledby": "last-title" },
      h("h2", { id: "last-title" }, "Latest reply"), JarvisReply(ctx.state.last, replyOpts(ctx))) : null,
    h("section", { class: "section", "aria-labelledby": "tasks-title" },
      h("h2", { id: "tasks-title" }, "What would you like to do?"),
      h("div", { class: "grid-tiles" },
        tile("/health/care-plan", "doc", "Understand care instructions", "Turn an after-visit summary into clear steps"),
        tile("/health/visit-prep", "clipboard", "Prepare for a visit", "Notes and questions for your doctor"),
        tile("/health/bills", "bill", "Review my bill", "Compare a bill with your insurance statement"),
        tile("/health/appointments", "calendar", "Plan an appointment", "Find free time around your classes"),
      )),
    h("section", { class: "section", "aria-labelledby": "try-title" },
      h("h2", { id: "try-title" }, "Try saying"),
      h("ul", { class: "btn-row", style: "list-style:none;padding:0" },
        EXAMPLES.map((ex) => h("li", {}, h("button", { type: "button", class: "btn", onclick: () => ctx.send(ex, "ui") }, `“${ex}”`))))),
  );
  try {
    const { items } = await api.timeline(false);
    const first = items[0];
    next.replaceChildren(first
      ? h("div", { class: "card card--sage" },
          h("p", { class: "eyebrow", style: "color:inherit" }, first.type),
          h("p", { style: "font-size:1.125rem;font-weight:700" }, first.title),
          first.when ? h("p", {}, fmtDate(first.when)) : null,
          first.path ? h("a", { class: "btn btn--primary", href: first.path, "data-link": "" }, first.next || "Open") : null)
      : h("div", { class: "card card--sage" },
          h("p", { style: "font-size:1.125rem;font-weight:700" }, "Start with your doctor's instructions"),
          h("p", {}, "Jarvis will pull out each next step and show where it came from."),
          h("div", { class: "btn-row" },
            h("button", { type: "button", class: "btn btn--primary", onclick: () => ctx.loadSamplePlan() }, "Use Sam's demo visit summary"),
            h("a", { class: "btn", href: "/health/care-plan", "data-link": "" }, "Upload my own"))));
  } catch (e) { next.replaceChildren(errBox(e)); }
}

function tile(href, ic, title, sub) {
  return h("a", { class: "tile", href, "data-link": "" }, icon(ic), h("strong", {}, title), h("span", {}, sub));
}

// ───────────────────────── Conversation ─────────────────────────
export function conversation(root, ctx) {
  const t = ctx.state.transcript;
  const lastUser = [...t].reverse().find((m) => m.role === "user");
  fill(root,
    PageHead("Jarvis Care", "Conversation", "Everything Jarvis says is written here too. Use the message box below to talk or type."),
    !voice.support.stt ? Notice("info", "Voice input isn't available in this browser.", "You can type everything. Chrome, Edge and Safari support speaking to Jarvis.") : null,
    voice.support.stt ? h("p", { class: "hint" }, "Privacy: in Chrome and Edge, the browser sends your speech to its online speech service to turn it into text. Jarvis only listens after you press Talk.") : null,
    h("section", { "aria-labelledby": "tx-title", class: "section", style: "margin-top:1rem" },
      h("h2", { id: "tx-title" }, "Transcript"),
      t.length
        ? h("ol", { class: "transcript" }, t.map((m) => m.role === "user"
            ? h("li", { class: "msg msg--user" }, h("p", { class: "msg__who" }, m.source === "voice" ? "You said" : "You"), h("p", { class: "msg__text", text: m.text }))
            : h("li", { class: "msg" }, JarvisReply(m.res, replyOpts(ctx)))))
        : h("p", { class: "muted" }, "No messages yet. Press Talk or type a message below."),
      h("div", { class: "btn-row" },
        lastUser ? h("button", { type: "button", class: "btn", onclick: () => ctx.editLast(lastUser.text) }, icon("edit"), "Edit my last message") : null,
        t.length ? h("button", { type: "button", class: "btn", onclick: () => { ctx.state.transcript = []; ctx.rerender(); announce("Conversation cleared."); } }, "Clear conversation") : null),
    ),
  );
}

// ───────────────────────── Care plan ─────────────────────────
export function carePlan(root, ctx) {
  const status = h("div", { "aria-live": "polite" });
  const plan = ctx.state.plan;
  const fileInput = h("input", { type: "file", id: "av-file", accept: ".txt,.pdf,text/plain,application/pdf", class: "input" });
  const pasteArea = h("textarea", { id: "av-paste", "aria-describedby": "av-paste-hint" });

  async function run(getDocId) {
    status.replaceChildren(Loading("Reading your document…"));
    try {
      const id = await getDocId();
      ctx.state.plan = await api.carePlan(id);
      ctx.state.planEdits = {};
      ctx.state.done = {};
      ctx.speakText(ctx.state.plan.spokenSummary);
      ctx.rerender();
      document.getElementById("plan-title")?.focus();
      ctx.refreshLoop();
    } catch (e) { status.replaceChildren(errBox(e)); }
  }

  fill(root,
    PageHead("Care plan", "Your after-visit care plan",
      "Jarvis pulls out only what your document says, quotes the exact sentence for each step, and marks anything unclear. It never adds medical advice."),
    h("section", { class: "card section", "aria-labelledby": "choose-title" },
      h("h2", { id: "choose-title" }, plan ? "Choose a different document" : "1. Choose your visit summary"),
      h("div", { class: "btn-row", style: "margin-top:0" },
        h("button", { type: "button", class: "btn btn--primary", onclick: () => run(async () => "sample-after-visit") }, icon("doc"), "Use Sam's demo visit summary")),
      h("p", { class: "hint" }, "The demo summary is fictional. Upload your own only if you're comfortable — it's kept in memory for this session only."),
      h("div", { class: "field", style: "margin-top:1rem" },
        h("label", { for: "av-file" }, "Upload a PDF or text file"),
        fileInput,
        h("div", { class: "btn-row" }, h("button", { type: "button", class: "btn", onclick: () => run(async () => {
          const f = fileInput.files?.[0];
          if (!f) throw new Error("Please choose a file first.");
          return (await api.upload(f, "afterVisit")).id;
        }) }, icon("upload"), "Read uploaded file"))),
      h("details", {},
        h("summary", { class: "linklike" }, "Paste the text instead"),
        h("div", { class: "field" },
          h("label", { for: "av-paste" }, "Visit summary text"), pasteArea,
          h("p", { class: "hint", id: "av-paste-hint" }, "Photos of documents can't be read in this demo yet."),
          h("div", { class: "btn-row" }, h("button", { type: "button", class: "btn", onclick: () => run(async () => (await api.paste(pasteArea.value, "afterVisit", "Pasted visit summary")).id) }, "Read pasted text")))),
      status,
    ),
    plan ? planSection(ctx) : null,
    remindersSection(ctx),
  );
}

function planSection(ctx) {
  const p = ctx.state.plan;
  const docView = h("div", { hidden: true });
  const toggleDoc = async (btn) => {
    if (!docView.hidden) { docView.hidden = true; btn.setAttribute("aria-expanded", "false"); return; }
    try {
      const d = await api.document(p.document.id);
      const text = d.pages.join("\n");
      const quotes = [...p.followups, ...p.care, ...p.warnings].map((c) => c.evidence?.[0]?.excerpt).filter(Boolean);
      const pre = h("pre", { class: "doc-text", tabindex: "0", "aria-label": `Full text of ${p.document.name}` });
      let rest = text;
      while (rest) {
        const hits = quotes.map((q) => [rest.indexOf(q), q]).filter(([i]) => i >= 0).sort((a, b) => a[0] - b[0]);
        if (!hits.length) { pre.append(rest); break; }
        const [i, q] = hits[0];
        pre.append(rest.slice(0, i), h("mark", {}, q));
        rest = rest.slice(i + q.length);
      }
      docView.replaceChildren(h("p", { class: "hint" }, "Highlighted lines are the ones Jarvis used."), pre);
      docView.hidden = false;
      btn.setAttribute("aria-expanded", "true");
    } catch (e) { docView.replaceChildren(errBox(e)); docView.hidden = false; }
  };
  return h("section", { class: "section", "aria-labelledby": "plan-title" },
    h("div", { class: "card" },
      h("div", { class: "reply__meta" }, h("h2", { id: "plan-title", tabindex: "-1", style: "margin:0" }, "2. Your next steps"), DemoBadge(p.isMock)),
      h("p", { class: "muted" }, `From ${p.document.name}${p.visitDate ? ` · visit on ${fmtDate(p.visitDate)}` : ""}`),
      h("p", { class: "reply__text" }, p.spokenSummary),
      h("div", { class: "btn-row" },
        h("button", { type: "button", class: "btn btn--primary", onclick: () => ctx.speakText(p.spokenSummary, true) }, icon("speaker"), "Read summary aloud"),
        h("button", { type: "button", class: "btn", onclick: () => ctx.speakText(p.readAllText, true) }, icon("speaker"), "Read every step aloud"),
        h("button", { type: "button", class: "btn", "aria-expanded": "false", onclick: (e) => toggleDoc(e.currentTarget) }, icon("doc"), "Show full document")),
      docView),
    group(ctx, "Follow-up tasks", p.followups, true),
    p.clarifications.length ? h("div", { class: "section" }, h("h3", {}, "Needs confirmation"),
      h("ul", { class: "items" }, p.clarifications.map((c) => ResponseCard(c, { onSpeak: (t) => ctx.speakText(t, true) })))) : null,
    group(ctx, "Care instructions", p.care, true),
    p.warnings.length ? h("div", { class: "section" }, h("h3", {}, "When to get help"),
      h("ul", { class: "items" }, p.warnings.map((c) => ResponseCard(c, { onSpeak: (t) => ctx.speakText(t, true) })))) : null,
  );
}

function group(ctx, title, cards, canRemind) {
  if (!cards.length) return null;
  const id = `g-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return h("div", { class: "section" }, h("h3", { id }, title),
    h("ul", { class: "items", "aria-labelledby": id }, cards.map((c) => ChecklistItem(ctx, c, canRemind))));
}

function ChecklistItem(ctx, card, canRemind) {
  const edits = ctx.state.planEdits || (ctx.state.planEdits = {});
  const done = ctx.state.done || (ctx.state.done = {});
  const title = edits[card.id] || card.title;
  const cbId = `done-${card.id}`;
  const li = h("li", { class: "item", dataset: { status: card.status || "", done: String(!!done[card.id]) } });
  const render = (editing = false) => {
    li.dataset.done = String(!!done[card.id]);
    const head = editing
      ? h("form", { class: "field", onsubmit: (e) => { e.preventDefault(); const v = e.target.elements.t.value.trim(); if (v) edits[card.id] = v; render(); li.querySelector("button")?.focus(); announce("Step updated."); } },
          h("label", { for: `edit-${card.id}` }, "Edit this step (the original quote stays in the evidence)"),
          h("input", { id: `edit-${card.id}`, name: "t", class: "input", value: edits[card.id] || card.title }),
          h("div", { class: "btn-row" }, h("button", { type: "submit", class: "btn btn--primary" }, "Save"),
            h("button", { type: "button", class: "btn", onclick: () => render() }, "Cancel")))
      : h("div", { class: "item__head" },
          h("label", { class: "check", for: cbId, style: "font-weight:700" },
            h("input", { type: "checkbox", id: cbId, checked: !!done[card.id], onchange: (e) => { done[card.id] = e.target.checked; render(); document.getElementById(cbId)?.focus(); announce(e.target.checked ? "Marked done." : "Marked not done."); } }),
            h("span", { class: "item__title" }, edits[card.id] || card.title, edits[card.id] ? h("span", { class: "muted", style: "font-weight:400" }, " (edited)") : null)),
          StatusBadge(card.status));
    li.replaceChildren(
      head,
      card.meta?.dueDate ? h("p", { class: "item__note" }, icon("calendar"), " Date in your document: ", h("time", { datetime: card.meta.dueDate }, fmtDate(card.meta.dueDate))) : null,
      card.meta?.clarification ? h("p", { class: "item__note item__note--flag" }, icon("question"), " ", card.meta.clarification) : null,
      card.meta?.note ? h("p", { class: "item__note" }, card.meta.note) : null,
      DocumentEvidence(card.evidence),
      editing ? null : h("div", { class: "btn-row" },
        h("button", { type: "button", class: "btn btn--quiet", onclick: () => ctx.speakText(edits[card.id] || card.description, true) }, icon("speaker"), "Read aloud", h("span", { class: "visually-hidden" }, `: ${title}`)),
        h("button", { type: "button", class: "btn btn--quiet", onclick: () => { render(true); document.getElementById(`edit-${card.id}`)?.focus(); } }, icon("edit"), "Edit", h("span", { class: "visually-hidden" }, `: ${title}`)),
        canRemind && !card.meta?.medication ? h("button", { type: "button", class: "btn", onclick: () => ctx.reminderFlow({ title: edits[card.id] || card.title, dueDate: card.meta?.dueDate || null, sourceCardId: card.id }) }, icon("bell"), "Create reminder…", h("span", { class: "visually-hidden" }, ` for: ${title}`)) : null),
    );
  };
  render();
  return li;
}

function remindersSection(ctx) {
  const box = h("div", {}, Loading("Loading reminders…"));
  (async () => {
    try {
      const { items } = await api.reminders();
      box.replaceChildren(items.length
        ? h("ul", { class: "items" }, items.map((r) => h("li", { class: "item" },
            h("div", { class: "item__head" }, h("p", { class: "item__title" }, r.title), StatusBadge("done")),
            r.dueDate ? h("p", { class: "item__note" }, "Due: ", h("time", { datetime: r.dueDate }, fmtDate(r.dueDate))) : null,
            h("p", { class: "item__note" }, r.note),
            h("div", { class: "btn-row" }, h("button", { type: "button", class: "btn btn--quiet", onclick: async () => { await api.deleteReminder(r.id); announce("Reminder deleted."); ctx.rerender(); ctx.refreshLoop(); } }, "Delete reminder", h("span", { class: "visually-hidden" }, `: ${r.title}`))))))
        : h("p", { class: "muted" }, "No reminders yet. Use “Create reminder” on a step — you'll confirm before anything is saved."));
    } catch (e) { box.replaceChildren(errBox(e)); }
  })();
  return h("section", { class: "section", "aria-labelledby": "rem-title" }, h("h2", { id: "rem-title" }, "Reminders you saved"), box);
}

// ───────────────────────── Bills ─────────────────────────
export function billsView(root, ctx) {
  const status = h("div", { "aria-live": "polite" });
  const billFile = h("input", { type: "file", id: "bill-file", accept: ".txt,.pdf,text/plain,application/pdf", class: "input" });
  const eobFile = h("input", { type: "file", id: "eob-file", accept: ".txt,.pdf,text/plain,application/pdf", class: "input" });
  async function run(get) {
    status.replaceChildren(Loading("Comparing line by line…"));
    try {
      const [b, e] = await get();
      ctx.state.bill = await api.compareBills(b, e);
      ctx.speakText(ctx.state.bill.spokenSummary);
      ctx.rerender();
      document.getElementById("bill-results")?.focus();
      ctx.refreshLoop();
    } catch (err) { status.replaceChildren(errBox(err)); }
  }
  const r = ctx.state.bill;
  fill(root,
    PageHead("BillSmart", "Check a bill against your insurance",
      "Jarvis lines up each charge on your bill with your insurance statement (EOB) and shows where they match. It points out questions to ask — it can't tell you a bill is wrong."),
    h("section", { class: "card section", "aria-labelledby": "bill-choose" },
      h("h2", { id: "bill-choose" }, "Choose your documents"),
      h("div", { class: "btn-row", style: "margin-top:0" },
        h("button", { type: "button", class: "btn btn--primary", onclick: () => run(async () => ["sample-bill", "sample-eob"]) }, icon("bill"), "Use Sam's demo bill and EOB")),
      h("p", { class: "hint" }, "Demo values are fictional."),
      h("div", { class: "field", style: "margin-top:1rem" }, h("label", { for: "bill-file" }, "Your bill (PDF or text)"), billFile),
      h("div", { class: "field" }, h("label", { for: "eob-file" }, "Your insurance statement / EOB (PDF or text)"), eobFile),
      h("button", { type: "button", class: "btn", onclick: () => run(async () => {
        const b = billFile.files?.[0], e = eobFile.files?.[0];
        if (!b && !e) throw new Error("Please choose at least one file.");
        return [b ? (await api.upload(b, "bill")).id : null, e ? (await api.upload(e, "eob")).id : null];
      }) }, icon("upload"), "Compare uploaded files"),
      status),
    r ? billResults(ctx, r) : null,
  );
}

function billResults(ctx, r) {
  const money = (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`);
  const labelBadge = (label) => label === "Matches the supplied documents" ? StatusBadge("ready") && h("span", { class: "badge badge--ok" }, icon("check"), label)
    : label === "Possible mismatch to verify" ? h("span", { class: "badge badge--warn" }, icon("alert"), label)
    : h("span", { class: "badge badge--info" }, icon("question"), label);
  return h("section", { class: "section", "aria-labelledby": "bill-results" },
    h("div", { class: "card" },
      h("div", { class: "reply__meta" }, h("h2", { id: "bill-results", tabindex: "-1", style: "margin:0" }, "What I found"), DemoBadge(r.isMock)),
      h("p", { class: "reply__text" }, r.spokenSummary),
      r.complete ? h("p", {}, `${r.mismatchCount} possible mismatch${r.mismatchCount === 1 ? "" : "es"} to verify · ${r.moreInfoCount} line${r.moreInfoCount === 1 ? "" : "s"} needing more information.`) : null,
      r.arithmetic.map((a) => h("p", { class: "muted" }, icon("check"), " ", a)),
      h("div", { class: "btn-row" }, h("button", { type: "button", class: "btn btn--quiet", onclick: () => ctx.speakText(r.spokenSummary, true) }, icon("speaker"), "Read aloud"))),
    r.rows.length ? h("div", { class: "section", style: "margin-top:1rem" },
      h("div", { class: "table-wrap", role: "region", "aria-labelledby": "bill-cap", tabindex: "0" },
        h("table", {},
          h("caption", { id: "bill-cap" }, "Bill and insurance statement, line by line (scrolls sideways on small screens)"),
          h("thead", {}, h("tr", {}, ["Date", "Code", "Service", "Charged", "Bill says you owe", "Insurance says you owe", "Result"].map((c) => h("th", { scope: "col" }, c)))),
          h("tbody", {}, r.rows.map((row) => {
            const b = row.bill || {}, e = row.eob || {};
            return h("tr", { "data-label": row.label },
              h("td", {}, b.date || e.date || "—"), h("td", {}, b.code || e.code || "—"),
              h("th", { scope: "row" }, b.description || e.description || "—"),
              h("td", { class: "num" }, money(b.billed ?? e.billed)), h("td", { class: "num" }, money(b.responsibility)),
              h("td", { class: "num" }, row.eob ? money(e.responsibility) : "Not listed", e.notes ? h("div", { class: "muted" }, e.notes) : null),
              h("td", {}, labelBadge(row.label)));
          }))))) : null,
    h("ul", { class: "items section" }, r.cards.map((c) => ResponseCard(c, { onSpeak: (t) => ctx.speakText(t, true) }))),
    r.questions.length ? h("div", { class: "card section" },
      h("h3", {}, "Questions to ask the billing office"),
      h("ol", {}, r.questions.map((q) => h("li", {}, q))),
      h("button", { type: "button", class: "btn btn--primary", onclick: async () => announce(await copyText(r.questions.join("\n\n")) ? "Questions copied." : "Couldn't copy. Select the text and copy it instead.") }, icon("copy"), "Copy questions")) : null,
    h("div", { class: "card section" }, h("h3", {}, "How to verify"), h("ol", {}, r.howToVerify.map((s) => h("li", {}, s)))),
    h("div", { class: "card section" }, h("h3", {}, "Words to know"),
      h("dl", {}, r.glossary.map((g) => [h("dt", { style: "font-weight:700" }, g.term), h("dd", { style: "margin:0 0 .75rem" }, g.meaning)])),
      h("p", { class: "hint" }, "General information only — your plan's documents have the details.")),
  );
}

// ───────────────────────── Visit prep ─────────────────────────
export function visitPrep(root, ctx) {
  const radios = (name, legend, opts) => h("fieldset", { class: "field" }, h("legend", {}, legend),
    h("div", { class: "segmented" }, opts.map((o) => h("label", {}, h("input", { type: "radio", name, value: o.toLowerCase() }), h("span", {}, o)))));
  const status = h("div", { "aria-live": "polite" });
  const form = h("form", { class: "card section", "aria-labelledby": "ci-title", onsubmit: async (e) => {
      e.preventDefault();
      const f = e.target.elements;
      try {
        await api.checkin({ text: f.note.value, sleep: f.sleep.value || null, energy: f.energy.value || null, stress: f.stress.value || null });
        announce("Check-in saved to your visit notes.");
        ctx.rerender();
      } catch (err) { status.replaceChildren(errBox(err)); }
    } },
    h("h2", { id: "ci-title" }, "Quick check-in (optional)"),
    h("p", { class: "muted" }, "This isn't a medical screening and there are no scores. It just helps you remember what to tell your doctor."),
    radios("sleep", "How have you been sleeping?", ["Good", "Okay", "Poor"]),
    radios("energy", "Energy", ["High", "Okay", "Low"]),
    radios("stress", "Stress", ["Low", "Medium", "High"]),
    h("div", { class: "field" }, h("label", { for: "ci-note" }, "Anything you've noticed or want to ask, in your own words"),
      h("textarea", { id: "ci-note", name: "note" })),
    h("button", { type: "submit", class: "btn btn--primary" }, "Save check-in"), status);
  const summary = h("div", {}, Loading("Loading your visit notes…"));
  fill(root,
    PageHead("Visit prep", "Prepare for your doctor visit", "Your own words, organized into a note you can bring, copy or download."),
    form,
    h("section", { class: "section", "aria-labelledby": "vp-title" }, h("h2", { id: "vp-title" }, "Your visit notes"), summary));
  (async () => {
    try {
      const p = await api.visitPrep();
      const qs = [...p.questions];
      const qList = h("ul", { class: "items" });
      const drawQs = () => qList.replaceChildren(...qs.map((q, i) => h("li", { class: "item" },
        h("label", { for: `q-${i}` }, `Question ${i + 1}`),
        h("input", { id: `q-${i}`, class: "input", value: q, oninput: (e) => { qs[i] = e.target.value; } }),
        h("div", { class: "btn-row" }, h("button", { type: "button", class: "btn btn--quiet", onclick: () => { qs.splice(i, 1); drawQs(); qList.querySelector("input")?.focus(); announce("Question removed."); } }, "Remove", h("span", { class: "visually-hidden" }, ` question ${i + 1}`))))));
      drawQs();
      const know = p.cards.find((c) => c.id === "prep-know"), unsure = p.cards.find((c) => c.id === "prep-unsure");
      fill(summary,
        h("div", { class: "card" }, h("h3", {}, "What I want my doctor to know"), h("p", { style: "white-space:pre-line" }, know.description)),
        h("div", { class: "card" }, h("h3", {}, "Questions I want to ask"),
          p.cards.find((c) => c.id === "prep-questions").meta.suggested ? h("p", { class: "hint" }, "These are starter questions — edit them to make them yours.") : null,
          qList,
          h("div", { class: "btn-row" },
            h("button", { type: "button", class: "btn", onclick: () => { qs.push(""); drawQs(); document.getElementById(`q-${qs.length - 1}`)?.focus(); } }, "Add a question"),
            h("button", { type: "button", class: "btn btn--primary", onclick: async () => { try { await api.saveQuestions(qs); announce("Questions saved."); ctx.refreshLoop(); } catch (e) { announce(e.message); } } }, "Save questions"))),
        h("div", { class: "card" }, h("h3", {}, "Things I'm unsure about"), h("p", { style: "white-space:pre-line" }, unsure.description)),
        p.starters.map((s) => h("div", { class: "card card--sage" }, h("h3", {}, "Conversation starter"), h("p", {}, s))),
        h("div", { class: "btn-row" },
          h("button", { type: "button", class: "btn", onclick: () => ctx.speakText(p.spoken, true) }, icon("speaker"), "Read aloud"),
          h("button", { type: "button", class: "btn", onclick: async () => announce(await copyText([`Questions:`, ...qs.map((q) => `- ${q}`)].join("\n")) ? "Visit notes copied." : "Couldn't copy.") }, icon("copy"), "Copy questions"),
          h("a", { class: "btn", href: api.exportUrl(), download: "my-visit-notes.txt" }, "Download visit notes (.txt)")));
    } catch (e) { summary.replaceChildren(errBox(e)); }
  })();
}

// ───────────────────────── Appointments ─────────────────────────
export function appointments(root, ctx) {
  const status = h("div", { "aria-live": "polite" });
  const rows = h("div", {});
  let n = 0;
  const addRow = () => {
    n += 1;
    rows.append(h("fieldset", { class: "field" }, h("legend", {}, `Free time ${n}`),
      h("div", { class: "grid-tiles" },
        h("div", {}, h("label", { for: `d-${n}` }, "Date"), h("input", { id: `d-${n}`, type: "date", class: "input", "data-k": "date", value: n === 1 ? "2026-11-17" : "" })),
        h("div", {}, h("label", { for: `s-${n}` }, "From"), h("input", { id: `s-${n}`, type: "time", class: "input", "data-k": "start", value: n === 1 ? "14:00" : "" })),
        h("div", {}, h("label", { for: `e-${n}` }, "To"), h("input", { id: `e-${n}`, type: "time", class: "input", "data-k": "end", value: n === 1 ? "16:00" : "" })))));
  };
  addRow();
  async function run(body) {
    status.replaceChildren(Loading("Looking for free time…"));
    try {
      ctx.state.slots = await api.suggest(body);
      ctx.speakText(ctx.state.slots.spokenSummary);
      ctx.rerender();
      document.getElementById("slots-title")?.focus();
    } catch (e) { status.replaceChildren(errBox(e)); }
  }
  const r = ctx.state.slots;
  fill(root,
    PageHead("Appointments", "Plan a follow-up visit",
      "Jarvis Care isn't connected to your real calendar or any clinic's booking system. It suggests your own free times — you still call the clinic to book."),
    h("section", { class: "card section", "aria-labelledby": "src-title" },
      h("h2", { id: "src-title" }, "Where should I look for free time?"),
      h("button", { type: "button", class: "btn btn--primary", onclick: () => run({ useDemoSchedule: true }) }, icon("calendar"), "Use Sam's demo schedule"),
      h("p", { class: "hint" }, "Fictional: an exam Monday morning, classes, a library shift."),
      h("form", { style: "margin-top:1.25rem", onsubmit: (e) => {
          e.preventDefault();
          const availability = [...rows.querySelectorAll("fieldset")].map((fs) => {
            const v = (k) => fs.querySelector(`[data-k=${k}]`).value;
            return v("date") && v("start") && v("end") ? { start: `${v("date")}T${v("start")}:00`, end: `${v("date")}T${v("end")}:00` } : null;
          }).filter(Boolean);
          if (!availability.length) { status.replaceChildren(errBox(new Error("Please enter a date, start and end time."))); return; }
          run({ availability });
        } },
        h("h3", {}, "Or enter the times you're free"), rows,
        h("div", { class: "btn-row" },
          h("button", { type: "button", class: "btn", onclick: () => { addRow(); document.getElementById(`d-${n}`)?.focus(); } }, "Add another time"),
          h("button", { type: "submit", class: "btn btn--primary" }, "Find times"))),
      status),
    r ? h("section", { class: "section", "aria-labelledby": "slots-title" },
      h("div", { class: "reply__meta" }, h("h2", { id: "slots-title", tabindex: "-1", style: "margin:0" }, "Suggested free times"), DemoBadge(r.isMock)),
      h("p", {}, `From ${r.source}. These are free times on your schedule, not clinic openings.`),
      r.notes.map((t) => h("p", { class: "muted" }, t)),
      r.busy?.length ? h("details", { class: "evidence" }, h("summary", {}, "See the commitments I worked around"),
        h("ul", {}, r.busy.map((b) => h("li", {}, `${b.title}: ${fmtDate(b.start, true)}`)))) : null,
      r.slots.length ? h("ul", { class: "items" }, r.slots.map((s, i) => h("li", { class: "item" },
        h("div", { class: "item__head" }, h("h3", { class: "item__title" }, `Option ${i + 1}: ${s.label}`), StatusBadge("suggested")),
        h("div", { class: "btn-row" }, h("button", { type: "button", class: "btn btn--primary", onclick: () => ctx.planFlow(s) }, icon("calendar"), "Plan this time…", h("span", { class: "visually-hidden" }, ` ${s.label}`))))))
        : h("p", {}, "No free hour found. Try adding more times.")) : null,
  );
}

// ───────────────────────── Timeline ─────────────────────────
export function timelineView(root, ctx) {
  const list = h("div", {}, Loading("Loading your timeline…"));
  const cb = h("input", { type: "checkbox", id: "tl-academics", checked: !!ctx.state.academics,
    onchange: (e) => { ctx.state.academics = e.target.checked; draw(); } });
  async function draw() {
    try {
      const { items } = await api.timeline(ctx.state.academics);
      list.replaceChildren(items.length
        ? h("ol", { class: "timeline" }, items.map((it) => h("li", {}, h("div", { class: "item" },
            h("div", { class: "item__head" }, h("p", { class: "eyebrow", style: "margin:0" }, it.type), it.demo ? DemoBadge(true) : null),
            h("h2", { class: "item__title", style: "font-size:1.125rem" }, it.title),
            it.when ? h("p", { class: "item__note" }, h("time", { datetime: it.when }, fmtDate(it.when, it.when.length > 10))) : null,
            h("p", { class: "item__note" }, `Status: ${it.status} · ${it.source}`),
            it.path ? h("a", { class: "btn", href: it.path, "data-link": "", style: "margin-top:.5rem" }, it.next || "Open") : null))))
        : h("p", { class: "muted" }, "Nothing here yet. Saved reminders, planned visits, questions and bill questions will show up here."));
    } catch (e) { list.replaceChildren(errBox(e)); }
  }
  fill(root,
    PageHead("Timeline", "Your care timeline", "Upcoming tasks, reminders and questions in order. This is a planning list, not a medical record."),
    h("div", { class: "card section" }, h("label", { class: "check", for: "tl-academics" }, cb,
      h("span", {}, "Show my class deadlines too (uses Sam's demo schedule — your health notes are never shared with other Jarvis features)"))),
    list);
  draw();
}
