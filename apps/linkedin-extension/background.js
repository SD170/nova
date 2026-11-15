// Service worker: forwards batches from the content script to the browser agent
// (content scripts can't call localhost / the tunnel because of page CORS) and tells
// the side panel to refresh.
importScripts("api.js");

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
});

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "observe") {
    JarvisApi.call("POST", "/linkedin/observe", msg.payload)
      .then((res) => {
        chrome.storage.local.set({ lastObserve: { ok: true, at: Date.now(), res } });
        chrome.runtime.sendMessage({ type: "observed", res }).catch(() => {}); // panel may be closed
        reply({ ok: true, res });
      })
      .catch((err) => {
        chrome.storage.local.set({ lastObserve: { ok: false, at: Date.now(), error: String(err.message || err) } });
        reply({ ok: false, error: String(err.message || err) });
      });
    return true; // async reply
  }
  return false;
});
