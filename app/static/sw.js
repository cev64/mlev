/* Service worker — app shell cache and an offline fallback for the API.
 *
 * Note on when this actually runs: service workers require a secure context.
 * Over http://<your-mac>:8733 on a phone that is not met, so this registers
 * only on localhost or behind HTTPS. The Android app does not rely on it — it
 * uses the localStorage snapshot in app.js instead, which works everywhere.
 */
const VERSION = 'mlev-v1';
const SHELL = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API: always prefer the live answer, fall back to the last one seen. A stale
  // prediction is far more useful than an error page when the Mac is asleep.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then(response => {
          const copy = response.clone();
          caches.open(VERSION).then(c => c.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Shell: cache first, it barely changes.
  event.respondWith(caches.match(request).then(hit => hit || fetch(request)));
});
