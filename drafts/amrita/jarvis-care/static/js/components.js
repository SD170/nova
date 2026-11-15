// Reusable, accessible building blocks.
import { h, icon, announce } from "./dom.js";

const STATUS = {
  ready: { text: "Ready", cls: "ok", icon: "check" },
  done: { text: "Done", cls: "ok", icon: "check" },
  suggested: { text: "Suggested", cls: "info", icon: "info" },
  needsConfirmation: { text: "Needs confirmation", cls: "warn", icon: "question" },
};

// Status is always text + icon, never color alone.
export function StatusBadge(status) {
  const s = STATUS[status];
  if (!s) return null;
  return h("span", { class: `badge badge--${s.cls}` }, icon(s.icon), s.text);
}

export function DemoBadge(isMock, label = "Demo data") {
  return isMock ? h("span", { class: "badge badge--demo" }, icon("info"), label) : null;
}

export function DocumentEvidence(evidence) {
  if (!evidence?.length) return null;
  return h("details", { class: "evidence" },
    h("summary", {}, evidence.length > 1 ? `View evidence (${evidence.length} sources)` : "View evidence"),
    evidence.map((e) => h("blockquote", {},
      h("p", { text: `“${e.excerpt}”` }),
      h("cite", {}, `Source: ${e.filename}${e.page ? `, page ${e.page}` : ""}${e.verified === false ? " — not an exact quote, please check the original" : " — exact quote"}`),
    )),
  );
}

export function Notice(kind, title, body) {
  return h("div", { class: `notice notice--${kind}`, role: kind === "error" ? "alert" : null },
    title ? h("strong", {}, title, " ") : null, body || "");
}

export function Loading(text = "Working on it…") {
  return h("p", { class: "loading", role: "status" }, text);
}

/** Generic card from a JarvisCareResponse. */
export function ResponseCard(card, { onSpeak } = {}) {
  const li = h("li", { class: "item", dataset: { status: card.status || "" } },
    h("div", { class: "item__head" },
      h("h4", { class: "item__title", text: card.title }),
      StatusBadge(card.status),
    ),
    card.description && card.description !== card.title
      ? h("p", { class: "item__note", style: "white-space:pre-line" }, card.description) : null,
    card.meta?.clarification ? h("p", { class: "item__note item__note--flag" }, icon("question"), " ", card.meta.clarification) : null,
    card.meta?.note ? h("p", { class: "item__note" }, card.meta.note) : null,
    DocumentEvidence(card.evidence),
    onSpeak ? h("div", { class: "btn-row" },
      h("button", { type: "button", class: "btn btn--quiet", onclick: () => onSpeak(`${card.title}. ${card.description !== card.title ? card.description : ""}`) },
        icon("speaker"), "Read aloud", h("span", { class: "visually-hidden" }, `: ${card.title}`)),
    ) : null,
  );
  return li;
}

/** Jarvis reply with captions, speech controls, cards and approval-aware actions. */
export function JarvisReply(res, { perform, speak, replay, slower, headingLevel = 3 } = {}) {
  const H = `h${headingLevel}`;
  const cards = res.cards || [];
  const actions = (res.actions || []).filter((a) => a.kind !== "setPreferences");
  return h("article", { class: "card reply", "aria-label": "Jarvis reply" },
    h("div", { class: "reply__meta" },
      h(H, { class: "eyebrow", style: "margin:0" }, "Jarvis replied"),
      DemoBadge(res.isMock, "Uses demo data"),
    ),
    h("p", { class: "reply__text", text: res.replyText }),
    h("div", { class: "btn-row", role: "group", "aria-label": "Reply controls" },
      h("button", { type: "button", class: "btn btn--quiet", onclick: replay }, icon("replay"), "Replay"),
      h("button", { type: "button", class: "btn btn--quiet", onclick: slower }, icon("slow"), "Repeat more slowly"),
    ),
    cards.length ? h("ul", { class: "items", style: "margin-top:1rem" }, cards.map((c) => ResponseCard(c, { onSpeak: speak }))) : null,
    actions.length ? h("div", { class: "btn-row" }, actions.map((a) => ActionButton(a, perform))) : null,
  );
}

export function ActionButton(action, perform) {
  const primary = action.requiresConfirmation || action.kind === "useSample";
  const ic = { saveReminder: "bell", copyQuestions: "copy", confirmAppointment: "calendar", openPage: "doc", useSample: "doc" }[action.kind];
  let label = action.label;
  if (action.requiresConfirmation) label = `${action.label}…`;
  return h("button", { type: "button", class: `btn ${primary ? "btn--primary" : ""}`, onclick: (e) => perform(action, e.currentTarget) },
    ic ? icon(ic) : null, label);
}

/**
 * ConsentDialog — shows exactly what will happen and waits for an explicit choice.
 * Resolves { confirmed, values }. Focus returns to the element that opened it.
 */
export function consent({ title, summary = [], fields = [], note = "", confirmLabel = "Confirm" }) {
  const dlg = document.getElementById("consent-dialog");
  const opener = document.activeElement;
  document.getElementById("consent-title").textContent = title;
  const desc = document.getElementById("consent-desc");
  desc.replaceChildren(summary.length
    ? h("dl", { class: "consent__summary" }, summary.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]))
    : "");
  const fieldWrap = document.getElementById("consent-fields");
  fieldWrap.replaceChildren(...fields.map((f) => {
    const id = `consent-${f.name}`;
    return h("div", { class: "field" },
      h("label", { for: id }, f.label),
      h("input", { id, name: f.name, class: "input", type: f.type || "text", value: f.value ?? "" }));
  }));
  document.getElementById("consent-note").textContent = note;
  document.getElementById("consent-confirm").textContent = confirmLabel;
  return new Promise((resolve) => {
    const onClose = () => {
      dlg.removeEventListener("close", onClose);
      const values = Object.fromEntries(fields.map((f) => [f.name, document.getElementById(`consent-${f.name}`)?.value ?? ""]));
      const confirmed = dlg.returnValue === "confirm";
      if (opener && document.contains(opener)) opener.focus();
      if (!confirmed) announce("Cancelled. Nothing was saved.");
      resolve({ confirmed, values });
    };
    dlg.returnValue = "";
    dlg.addEventListener("close", onClose);
    dlg.showModal();
    (fieldWrap.querySelector("input") || document.getElementById("consent-confirm")).focus();
  });
}

export function PageHead(eyebrow, title, intro, extra) {
  return h("header", { class: "page-head" },
    h("p", { class: "eyebrow" }, eyebrow),
    h("h1", { tabindex: "-1", id: "page-title" }, title),
    intro ? h("p", {}, intro) : null,
    extra || null,
  );
}
