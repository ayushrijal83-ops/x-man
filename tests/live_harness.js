// Runs app/static/js/live.js against a fake clock, document and fetch (used by test_live_updates_h0310.py).
// Prints one JSON object with the observations of each scenario.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'js', 'live.js'), 'utf8');

function makeEnv() {
    let now = 0, seq = 0;
    const timers = new Map();
    const listeners = {};
    const env = {
        calls: 0,
        document: {
            hidden: false, readyState: 'complete', body: { getAttribute: () => null },
            querySelectorAll: () => [],
            addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); },
            dispatchEvent: (e) => { (listeners[e.type] || []).forEach((fn) => fn(e)); },
        },
    };
    env.setTimeout = (fn, ms) => { const id = ++seq; timers.set(id, { at: now + ms, fn }); return id; };
    env.clearTimeout = (id) => timers.delete(id);
    env.advance = async (ms) => {      // run due timers in order, letting promises settle in between
        const end = now + ms;
        for (;;) {
            let next = null;
            for (const [id, t] of timers) if (t.at <= end && (!next || t.at < next[1].at)) next = [id, t];
            if (!next) break;
            timers.delete(next[0]);
            now = next[1].at;
            next[1].fn();
            await flush();
        }
        now = end;
    };
    env.setHidden = async (h) => {
        env.document.hidden = h;
        (listeners.visibilitychange || []).forEach((fn) => fn());
        await flush();
    };
    env.pendingDelays = () => [...timers.values()].map((t) => t.at - now).sort((a, b) => a - b);
    return env;
}

async function flush() { for (let i = 0; i < 20; i++) await Promise.resolve(); }

function load(env, extra) {
    const ctx = {
        window: {}, document: env.document, setTimeout: env.setTimeout, clearTimeout: env.clearTimeout,
        Promise, CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
        console, ...extra,
    };
    ctx.window.location = { href: 'https://x-man.example/page' };
    vm.runInNewContext(SRC, ctx);
    return ctx.window.XmanLive;
}

async function main() {
    const out = {};

    // 1. schedule, no overlap, duplicate names
    {
        const env = makeEnv();
        const live = load(env);
        let resolve;
        let starts = 0;
        const loop = live.every('a', 10000, () => { starts++; return new Promise((r) => { resolve = r; }); });
        await flush();
        loop.run(); loop.run();                       // while the first request is still running
        await flush();
        out.noOverlap = { startsWhileRunning: starts };
        resolve(); await flush();
        out.noOverlap.nextDelay = env.pendingDelays()[0];
        let other = 0;
        const again = live.every('a', 1000, () => { other++; return Promise.resolve(); });
        out.duplicate = { sameLoop: again === loop, secondTaskCalls: other };
        await env.advance(10000);
        out.noOverlap.startsAfterInterval = starts;
    }

    // 2. hidden tab pauses, visible catches up at once
    {
        const env = makeEnv();
        const live = load(env);
        let calls = 0;
        live.every('b', 5000, () => { calls++; return Promise.resolve(); });
        await flush();
        await env.setHidden(true);
        const timersWhileHidden = env.pendingDelays().length;
        await env.advance(60000);
        const callsWhileHidden = calls - 1;
        await env.setHidden(false);
        out.visibility = { timersWhileHidden, callsWhileHidden, callsAfterVisible: calls };
    }

    // 3. hiddenMs slows instead of pausing
    {
        const env = makeEnv();
        const live = load(env);
        let calls = 0;
        live.every('c', 10000, () => { calls++; return Promise.resolve(); }, { hiddenMs: 60000 });
        await flush();
        await env.setHidden(true);
        const delay = env.pendingDelays()[0];
        await env.advance(60000);
        out.hiddenSlow = { delay, calls };
    }

    // 4. silent backoff and recovery
    {
        const env = makeEnv();
        const live = load(env);
        let fail = true;
        const delays = [];
        live.every('d', 10000, () => (fail ? Promise.reject(new Error('down')) : Promise.resolve()));
        for (let i = 0; i < 5; i++) { await flush(); delays.push(env.pendingDelays()[0]); await env.advance(delays[i]); }
        fail = false;
        await flush();
        const afterRecovery = env.pendingDelays()[0];
        await env.advance(afterRecovery); await flush();
        out.backoff = { delays, afterRecoveryFirst: afterRecovery, afterRecoveryNext: env.pendingDelays()[0] };
        const thrower = live.every('e', 1000, () => { throw new Error('sync'); });
        await flush();
        out.backoff.syncThrowScheduled = env.pendingDelays().length > 0;
    }

    // 5. regions: only changed regions swapped; redirects/errors never swap
    {
        const env = makeEnv();
        const mk = (key, html) => ({ key, innerHTML: html, attrs: { 'data-live': key }, getAttribute(n) { return this.attrs[n]; }, setAttribute(n, v) { this.attrs[n] = v; } });
        const regions = [mk('one', 'A'), mk('two', 'B')];
        regions.forEach((r) => r.setAttribute('data-live-html', r.innerHTML));
        env.document.querySelectorAll = (sel) => (sel === '[data-live]' ? regions : []);
        const pages = {};
        let response = null;
        const events = [];
        env.document.addEventListener('xman:regions-updated', () => events.push('updated'));
        const live = load(env, {
            fetch: async (url, opts) => { response.headersSent = opts.headers; response.url = url; return response; },
            DOMParser: function () { this.parseFromString = (html) => ({ querySelector: (sel) => { const k = /data-live="([\w-]+)"/.exec(sel)[1]; return pages[html][k] ? { innerHTML: pages[html][k] } : null; } }); },
        });
        pages.v2 = { one: 'A', two: 'B-changed' };
        response = { ok: true, redirected: false, text: async () => 'v2' };
        await live.refreshRegions();
        const afterChange = regions.map((r) => r.innerHTML);
        const liveHeader = response.headersSent['X-Xman-Live'];
        pages.login = { one: 'LOGIN', two: 'LOGIN' };
        response = { ok: true, redirected: true, text: async () => 'login' };
        let redirectRejected = false;
        await live.refreshRegions().catch(() => { redirectRejected = true; });
        response = { ok: false, status: 500, redirected: false, text: async () => 'login' };
        let errorRejected = false;
        await live.refreshRegions().catch(() => { errorRejected = true; });
        pages.missing = {};
        response = { ok: true, redirected: false, text: async () => 'missing' };
        await live.refreshRegions();
        out.regions = { afterChange, afterRedirectAndError: regions.map((r) => r.innerHTML), redirectRejected,
                        errorRejected, events, liveHeader, url: response.url };
    }

    process.stdout.write(JSON.stringify(out));
}

main().catch((e) => { console.error(e); process.exit(1); });
