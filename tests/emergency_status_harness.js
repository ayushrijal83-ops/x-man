// Runs app/static/js/emergency.js against stubbed DOM/fetch and drives its status poll with a scripted sequence
// of /api/emergency/active responses (used by test_live_updates_h0310.py). Prints one JSON object.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'js', 'emergency.js'), 'utf8');

function element() {
    return { hidden: false, textContent: '', className: '', attrs: {}, focus() {}, classList: { add() {}, remove() {} },
             setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; } };
}

async function main() {
    const elements = {};
    const badge = element();
    const pageCount = element();
    const events = [];
    let registered = null;
    const responses = [
        { alerts: [], sound_enabled: true, unread_count: 0, latest_notification_id: null },   // user has no notification
        { alerts: [], sound_enabled: true, unread_count: 1, latest_notification_id: 5 },      // first one arrives
        { alerts: [], sound_enabled: true, unread_count: 1, latest_notification_id: 5 },      // nothing new
        { alerts: [], sound_enabled: true, unread_count: 2, latest_notification_id: 7 },      // another one
        { alerts: [], sound_enabled: true, unread_count: 0, latest_notification_id: 7 },      // all read elsewhere
    ];
    let call = 0;
    const document = {
        getElementById: (id) => (id === 'unread-count' ? pageCount : (elements[id] = elements[id] || element())),
        querySelector: () => ({ content: '' }),
        querySelectorAll: (sel) => (sel === '[data-unread-badge]' ? [badge] : []),
        addEventListener() {},
        dispatchEvent: (e) => events.push(e.detail),
    };
    const ctx = {
        document, console, Promise, JSON, Math, Date, Uint8Array, atob: () => '',
        navigator: {}, sessionStorage: { getItem: () => '[]', setItem() {} },
        CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
        fetch: async () => { const body = responses[call++]; return { ok: true, json: async () => body }; },
        setTimeout, clearTimeout, setInterval, clearInterval,
    };
    ctx.window = {
        location: { href: '/' }, isSecureContext: true, lucide: null,
        XmanLive: { every: (name, ms, task, opts) => { registered = { name, ms, hiddenMs: opts && opts.hiddenMs, task }; return { run() {} }; } },
    };
    vm.runInNewContext(SRC, ctx);

    const badges = [];
    for (let i = 0; i < responses.length; i++) {
        await registered.task();
        badges.push({ text: String(badge.textContent), hidden: badge.hidden, page: String(pageCount.textContent) });
    }
    process.stdout.write(JSON.stringify({
        loop: { name: registered.name, ms: registered.ms, hiddenMs: registered.hiddenMs },
        changed: events.map((e) => e.notificationsChanged),
        badges,
    }));
}

main().catch((e) => { console.error(e); process.exit(1); });
