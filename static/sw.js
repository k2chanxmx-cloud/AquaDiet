const CACHE = "aquadiet-standalone-v3";

const ASSETS = [
  "/static/style.css",
  "/static/character.webp"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => {
      return cache.addAll(ASSETS);
    })
  );

  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames
          .filter(name => name !== CACHE)
          .map(name => caches.delete(name))
      );
    })
  );

  self.clients.claim();
});

self.addEventListener("fetch", event => {
  // API通信やPOSTはキャッシュしない
  if (
    event.request.method !== "GET" ||
    event.request.url.includes("/api/")
  ) {
    return;
  }

  // HTMLは常にネットワーク優先
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/"))
    );
    return;
  }

  // CSS・画像などはネットワーク優先 → 失敗時キャッシュ
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response && response.ok) {
          const clone = response.clone();

          caches.open(CACHE).then(cache => {
            cache.put(event.request, clone);
          });
        }

        return response;
      })
      .catch(() => caches.match(event.request))
  );
});