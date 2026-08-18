const CACHE = "aquadiet-final-browser-v1";

const ASSETS = [
  "/static/style.css",
  "/static/character.webp"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(
        cacheNames
          .filter(name => name !== CACHE)
          .map(name => caches.delete(name))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  // API通信とPOST/PUT/DELETE等はService Workerで触らない
  if (
    event.request.method !== "GET" ||
    event.request.url.includes("/api/")
  ) {
    return;
  }

  // HTML/navigationは常にネットワーク優先
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }

  // CSS・画像等もネットワーク優先、失敗時のみキャッシュ
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response && response.ok) {
          const clone = response.clone();
          caches.open(CACHE).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
