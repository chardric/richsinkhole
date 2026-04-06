/**
 * Service worker for RichSinkhole PWA.
 * Provides offline support with cache-first static assets,
 * network-first API and HTML strategies.
 *
 * Developed by:
 * Richard R. Ayuyang, PhD [https://chadlinuxtech.net]
 * Professor II, CSU
 *
 * Copyright (c) 2026 DownStreamTech [https://downstreamtech.net]. All rights reserved.
 */

const CACHE_NAME = 'v1-static';

const PRE_CACHE = [
  '/static/bootstrap.min.css',
  '/static/bootstrap.bundle.min.js',
  '/static/app.js',
];

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Offline - RichSinkhole</title>
  <style>
    body{font-family:Inter,system-ui,sans-serif;background:#0d1117;color:#c9d1d9;
      display:flex;align-items:center;justify-content:center;height:100vh;margin:0;
      text-align:center}
    .container{max-width:400px;padding:2rem}
    h1{color:#da3633;font-size:1.5rem;margin-bottom:1rem}
    p{color:#8b949e;line-height:1.6}
  </style>
</head>
<body>
  <div class="container">
    <h1>You are offline</h1>
    <p>RichSinkhole cannot reach the network right now. Check your connection and try again.</p>
  </div>
</body>
</html>`;

// Install: pre-cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRE_CACHE))
  );
  self.skipWaiting();
});

// Activate: purge old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Fetch: route by request type
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // API requests: network-first, no caching
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // Static assets (css, js, images, fonts): cache-first
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // HTML pages: network-first with offline fallback
  event.respondWith(networkFirstHTML(request));
});

function isStaticAsset(pathname) {
  return /\.(?:css|js|png|jpg|jpeg|gif|svg|webp|avif|ico|woff2?|ttf|eot)$/i.test(pathname)
    || pathname.startsWith('/static/');
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    return cached;
  }
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (_) {
    return new Response('', { status: 503, statusText: 'Service Unavailable' });
  }
}

async function networkFirstHTML(request) {
  try {
    const response = await fetch(request);
    return response;
  } catch (_) {
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    return new Response(OFFLINE_HTML, {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  }
}
