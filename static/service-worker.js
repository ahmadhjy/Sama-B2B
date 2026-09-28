// Private pages, passport files and financial records are never cached offline.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data = {title: 'HelloSama', body: 'You have a new portal update.', url: '/notifications/'};
  try { if (event.data) data = {...data, ...event.data.json()}; } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title, {body: data.body, icon: '/static/brand/icon.svg', data: {url: data.url}, tag: 'hellosama-update'}));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/notifications/', self.location.origin);
  const url = target.origin === self.location.origin ? target.href : self.location.origin + '/notifications/';
  event.waitUntil(self.clients.openWindow(url));
});
