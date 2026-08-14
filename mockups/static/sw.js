/* Self-destroying service worker. Do not delete this file.

   The site this one replaces (a Jekyll "sleek" theme) registered a service worker at
   exactly this path, and its precache list included "/" and "/index.html". Every browser
   that ever loaded www.steinmetzlab.net still has that worker installed, and it answers
   navigations from its own cache -- so those visitors would keep being served the old
   homepage after the new one went live, with no way to tell that anything had changed.

   Shipping a worker at the same URL is the only way to reach them: the browser re-fetches
   the script on navigation, finds this one instead, installs it, and this one throws away
   every cache and unregisters itself. After that the site is served from the network like
   any ordinary static site, and nothing here runs again.

   The new pages call navigator.serviceWorker.register() nowhere, so this file only ever
   executes for someone carrying the old registration. */

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) await caches.delete(key);
    await self.registration.unregister();
    // Reload whatever tabs this worker still controls, so the visitor lands on the new
    // page in this visit rather than the next one.
    for (const client of await self.clients.matchAll({ type: 'window' })) {
      try { await client.navigate(client.url); } catch (e) { /* client may be gone */ }
    }
  })());
});
