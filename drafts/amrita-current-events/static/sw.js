// Service worker: shows pushed headlines even when the page is closed.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { title: "Jarvis news", body: event.data?.text() || "" }; }
  const title = data.title || "Jarvis news";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/static/icon-192.png",
    badge: "/static/badge-96.png",
    tag: data.tag || undefined,
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(self.clients.openWindow(url));
});
