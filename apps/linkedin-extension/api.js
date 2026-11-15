// Shared by background.js and the side panel: talk to the Jarvis browser agent.
/* exported JarvisApi */
const JarvisApi = (() => {
  const DEFAULTS = { apiBase: "http://localhost:9001", apiKey: "" };

  function config() {
    return new Promise((resolve) => chrome.storage.local.get(DEFAULTS, resolve));
  }

  async function call(method, path, body) {
    const { apiBase, apiKey } = await config();
    const headers = { "Content-Type": "application/json" };
    if (apiKey) headers["X-Canvas-Key"] = apiKey;
    const resp = await fetch(apiBase.replace(/\/+$/, "") + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try { data = await resp.json(); } catch (_) { /* empty body */ }
    if (!resp.ok) {
      const detail = (data && (data.detail || data.error)) || resp.statusText;
      throw new Error(`${resp.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    }
    return data;
  }

  return { DEFAULTS, config, call };
})();
