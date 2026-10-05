/* X-MAN live updates (H03.10): one small scheduler for every polling loop on a page.
 *
 *   XmanLive.every(name, ms, task, {hiddenMs})  task() returns a Promise. One loop per name (a second
 *       registration with the same name is ignored), never overlapping: the next run is scheduled only
 *       after the previous one settled. Hidden tab: paused (or slowed to hiddenMs); visible again: runs at
 *       once (catch-up). Failures are silent and back off (x2, at most 60 s), then recover by themselves.
 *   XmanLive.refreshRegions()  re-fetches this page's own URL (same route = same authorization and
 *       scoping) and replaces only the [data-live="key"] elements whose HTML changed. Forms, maps and
 *       anything not marked data-live are never touched, so scroll position, inputs and map state survive.
 *   Pages opt in with <body data-live-interval="ms"> (timer) and/or data-live-on="notifications"
 *   (refresh only when the global status loop reports a new notification).
 *
 * Polling is not a notification channel: notifications are created only by the server; Web Push stays the
 * background/OS channel.
 */
(function () {
    'use strict';
    var MAX_BACKOFF_MS = 60000;
    var loops = {};

    function every(name, ms, task, options) {
        if (loops[name]) return loops[name];
        var hiddenMs = options && options.hiddenMs;
        var loop = { timer: null, running: false, failures: 0 };
        loops[name] = loop;

        function delay() {
            var base = document.hidden ? hiddenMs : ms;
            return loop.failures ? Math.min(base * Math.pow(2, loop.failures), MAX_BACKOFF_MS) : base;
        }
        function schedule() {
            clearTimeout(loop.timer);
            loop.timer = null;
            if (document.hidden && !hiddenMs) return;  // paused; visibilitychange resumes
            loop.timer = setTimeout(run, delay());
        }
        function run() {
            if (loop.running) return;          // never two requests for the same data at once
            clearTimeout(loop.timer);
            loop.running = true;
            var settled = function (ok) { loop.running = false; loop.failures = ok ? 0 : Math.min(loop.failures + 1, 6); schedule(); };
            var p;
            try { p = Promise.resolve(task()); } catch (e) { p = Promise.reject(e); }
            p.then(function () { settled(true); }, function () { settled(false); });
        }
        loop.run = run;
        document.addEventListener('visibilitychange', function () {
            if (document.hidden) schedule(); else run();   // hidden: pause/slow; visible: catch up now
        });
        run();
        return loop;
    }

    function fetchJson(url) {
        return fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' }, cache: 'no-store' })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    }

    function refreshRegions() {
        var regions = document.querySelectorAll('[data-live]');
        if (!regions.length) return Promise.resolve();
        return fetch(window.location.href, { credentials: 'same-origin', headers: { 'Accept': 'text/html', 'X-Xman-Live': '1' }, cache: 'no-store' })
            .then(function (r) {
                // a redirect (e.g. to the login page) or an error page must never replace live content
                if (!r.ok || r.redirected) throw new Error(r.status);
                return r.text();
            })
            .then(function (html) {
                var doc = new DOMParser().parseFromString(html, 'text/html');
                var changed = false;
                regions.forEach(function (el) {
                    var fresh = doc.querySelector('[data-live="' + el.getAttribute('data-live') + '"]');
                    if (fresh && fresh.innerHTML !== el.getAttribute('data-live-html')) {
                        el.setAttribute('data-live-html', fresh.innerHTML);
                        if (el.innerHTML !== fresh.innerHTML) { el.innerHTML = fresh.innerHTML; changed = true; }
                    }
                });
                if (changed) {
                    if (window.lucide) window.lucide.createIcons();
                    document.dispatchEvent(new CustomEvent('xman:regions-updated'));
                }
            });
    }

    window.XmanLive = { every: every, fetchJson: fetchJson, refreshRegions: refreshRegions };

    // Page opt-in (see header). Runs after the DOM is ready.
    function init() {
        var regions = document.querySelectorAll('[data-live]');
        regions.forEach(function (el) { el.setAttribute('data-live-html', el.innerHTML); });
        var interval = parseInt(document.body.getAttribute('data-live-interval') || '0', 10);
        if (regions.length && interval > 0) every('regions', interval, refreshRegions);
        if (regions.length && document.body.getAttribute('data-live-on') === 'notifications') {
            document.addEventListener('xman:status', function (e) {
                if (e.detail && e.detail.notificationsChanged) refreshRegions().catch(function () {});
            });
        }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
