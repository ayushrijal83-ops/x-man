// Runs app/static/js/sw.js against a mocked service-worker global (used by test_final_qa.py).
// Prints one JSON object describing what the worker did.
'use strict';
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'js', 'sw.js'), 'utf8');
const ORIGIN = 'https://x-man.example';
const handlers = {};
const shown = [];
const opened = [];
const navigated = [];
const posted = [];
const clientsList = [{
    url: ORIGIN + '/districts',
    focus: async function () { return this; },
    navigate: async function (u) { navigated.push(u); return this; },
    postMessage: (m) => posted.push(m),
}];
const self = {
    location: new URL(ORIGIN + '/sw.js'),
    addEventListener: (type, fn) => { handlers[type] = fn; },
    skipWaiting: () => {},
    registration: { showNotification: async (title, options) => { shown.push({ title, options }); } },
    clients: {
        claim: async () => {},
        matchAll: async () => clientsList,
        openWindow: async (u) => { opened.push(u); },
    },
};
new Function('self', 'URL', src)(self, URL);

async function fire(type, event) {
    let pending = Promise.resolve();
    event.waitUntil = (p) => { pending = p; };
    handlers[type](event);
    await pending;
}

(async () => {
    await fire('push', { data: { json: () => ({ title: 'X-MAN EMERGENCY ALERT: Flood', body: 'b',
        url: '/rivers/status?district_id=1', tag: 'xman-hazard-1', emergency: true }) } });
    await fire('push', { data: { json: () => ({ title: 'Resolved', url: 'https://evil.example/phish', emergency: false }) } });
    await fire('push', { data: { json: () => { throw new Error('not json'); } } });
    await fire('notificationclick', { notification: { close() {}, data: { url: 'https://evil.example/x' } } });
    clientsList.length = 0; // no open tab: a new window is opened
    await fire('notificationclick', { notification: { close() {}, data: { url: '/hazards/1/response' } } });
    console.log(JSON.stringify({
        events: Object.keys(handlers).sort(),
        shown: shown.map((s) => ({ title: s.title, url: s.options.data.url, requireInteraction: s.options.requireInteraction,
                                   tag: s.options.tag })),
        posted: posted.length,
        navigated,
        opened,
    }));
})();
