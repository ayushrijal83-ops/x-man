/* X-MAN service worker (M12): receives Web Push and shows system notifications, including when
   no X-MAN tab is open. No caching/offline logic. The OS/browser decides sound and display. */
'use strict';

self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) { event.waitUntil(self.clients.claim()); });

function sameOriginPath(url) {
    // only ever open pages of this site
    try {
        var target = new URL(url || '/notifications', self.location.origin);
        return target.origin === self.location.origin ? target.pathname + target.search : '/notifications';
    } catch (e) {
        return '/notifications';
    }
}

self.addEventListener('push', function (event) {
    var data = {};
    try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
    var title = data.title || 'X-MAN alert';
    var options = {
        body: data.body || '',
        tag: data.tag || 'xman',
        renotify: true,
        // emergencies stay on screen until the user acts (where the platform supports it)
        requireInteraction: !!data.emergency,
        silent: false,
        data: { url: sameOriginPath(data.url), notificationId: data.notification_id || null },
        actions: [{ action: 'open', title: 'Open X-MAN' }]
    };
    event.waitUntil(
        self.registration.showNotification(title, options).then(function () {
            // open X-MAN tabs show the in-website alert straight away instead of on the next poll
            return self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        }).then(function (clients) {
            clients.forEach(function (c) { c.postMessage({ type: 'xman-push', emergency: !!data.emergency }); });
        })
    );
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    // re-checked here too: never trust a notification's stored URL to stay on this site
    var path = sameOriginPath(event.notification.data && event.notification.data.url);
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clients) {
            for (var i = 0; i < clients.length; i++) {
                if (new URL(clients[i].url).origin === self.location.origin && 'focus' in clients[i]) {
                    return clients[i].navigate(path).then(function (c) { return (c || clients[i]).focus(); });
                }
            }
            return self.clients.openWindow(path);
        })
    );
});
