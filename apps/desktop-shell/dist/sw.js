// Minimal service worker — exists mainly so Chrome/Android will offer
// "Install app". Caches the static shell only; every /api/* call always
// goes to the network since Atlas's data is never meant to be stale.

const CACHE = "atlas-shell-v2";
const SHELL = ["/", "/index.html", "/manifest.json", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Morning briefing arrives here — the server pushes a JSON payload
// ({title, body, url}), this shows it as a real OS notification even if
// Atlas isn't open in a tab.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { title: "Atlas", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Atlas";
  const options = {
    body: data.body || "",
    icon: "/icon.svg",
    badge: "/icon.svg",
    data: { url: data.url || "/" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return; // never cache API calls

  event.respondWith(
    fetch(event.request)
    .then((res) => {
      if (res.ok) caches.open(CACHE).then((cache) => cache.put(event.request, res.clone()));
      return res;
    })
    .catch(() => caches.match(event.request))
    );
});
