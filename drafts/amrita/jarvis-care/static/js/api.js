// Thin client for /api/health/*. Errors become friendly, speakable messages.
import * as prefs from "./prefs.js";

function newId() {
  return (crypto.randomUUID?.() || `s-${Date.now()}-${Math.random().toString(16).slice(2)}`);
}

export const sessionId = (() => {
  try {
    let id = sessionStorage.getItem("jarvisCare.session");
    if (!id) { id = newId(); sessionStorage.setItem("jarvisCare.session", id); }
    return id;
  } catch { return newId(); }
})();

export class ApiError extends Error {}

async function request(method, path, body, isForm = false) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body && !isForm ? { "Content-Type": "application/json" } : undefined,
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
    });
  } catch {
    throw new ApiError("I can't reach the Jarvis Care server right now. Check that it's running, then try again.");
  }
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail
      : Array.isArray(detail) ? "Some details are missing or not in the right format. Please check and try again."
      : "Something went wrong. Please try again.";
    throw new ApiError(msg);
  }
  return data;
}

const q = (extra = "") => `?sessionId=${encodeURIComponent(sessionId)}${extra}`;

export const api = {
  config: () => request("GET", "/api/health/config"),
  ask: (utterance, extra = {}) => {
    const p = prefs.get();
    return request("POST", "/api/health/handle", {
      requestId: newId(),
      sessionId,
      source: extra.source || "text",
      utterance,
      ...extra,
      preferences: {
        simpleLanguage: p.simpleLanguage, speak: p.speechEnabled, locale: p.locale,
        textScale: p.textScale, speechRate: p.speechRate,
      },
    });
  },
  samples: () => request("GET", "/api/health/samples"),
  document: (id) => request("GET", `/api/health/documents/${encodeURIComponent(id)}${q()}`),
  upload: (file, kind) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("sessionId", sessionId);
    if (kind) fd.append("kind", kind);
    return request("POST", "/api/health/documents", fd, true);
  },
  paste: (text, kind, name) => request("POST", "/api/health/documents/paste", { sessionId, text, kind, name }),
  carePlan: (documentId) => request("POST", "/api/health/care-plan", { sessionId, documentId }),
  saveReminder: (r) => request("POST", "/api/health/reminders", { sessionId, ...r, approved: true }),
  reminders: () => request("GET", `/api/health/reminders${q()}`),
  deleteReminder: (id) => request("DELETE", `/api/health/reminders/${encodeURIComponent(id)}${q()}`),
  compareBills: (billId, eobId) => request("POST", "/api/health/bills/compare", { sessionId, billId, eobId }),
  checkin: (c) => request("POST", "/api/health/checkins", { sessionId, ...c }),
  visitPrep: () => request("GET", `/api/health/visit-prep${q()}`),
  saveQuestions: (questions) => request("PUT", "/api/health/visit-prep/questions", { sessionId, questions }),
  exportUrl: () => `/api/health/visit-prep/export${q()}`,
  suggest: (body) => request("POST", "/api/health/appointments/suggest", { sessionId, ...body }),
  planVisit: (slot) => request("POST", "/api/health/appointments/plan", { sessionId, slot, approved: true }),
  timeline: (academics) => request("GET", `/api/health/timeline${q(`&academics=${academics ? "true" : "false"}`)}`),
  clear: () => request("DELETE", `/api/health/session/${encodeURIComponent(sessionId)}`),
};
