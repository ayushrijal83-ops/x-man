/* X-MAN emergency alerts, browser side (M12).
 *  - Layer 2: polls the user's own active emergency alerts and shows the in-website alert, with a
 *    short beep pattern (only if the user's sound preference is on and the browser allows audio).
 *  - XmanPush: explicit opt-in to Web Push (layer 3). Permission is only requested from a click.
 * All alert text is inserted with textContent. Labels come from the server-rendered markup.
 */
(function () {
    'use strict';

    // H03.10: driven by XmanLive (live.js): 10 s while visible, 60 s in a hidden tab (Web Push covers the
    // background), immediate catch-up when the tab becomes visible, no overlapping requests.
    var POLL_MS = 10000;
    var HIDDEN_POLL_MS = 60000;
    // undefined = no status poll yet. NOT null: the API returns null when the user has no notification at all,
    // and the first notification after that must count as a change (found in H03.10 browser QA).
    var lastNotificationId;
    var ALARM_CYCLES = 10;          // beep-beep every 1.5 s, at most ~15 s, then silence
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrf = csrfMeta ? csrfMeta.content : '';

    function post(url, body) {
        return fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify(body || {})
        }).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (data) {
                data.httpStatus = r.status;
                return data;
            });
        });
    }

    // ------------------------------------------------------------------ audio (autoplay-safe)
    var audioCtx = null;
    var alarmTimer = null;

    function audio() {
        if (!audioCtx) {
            var Ctor = window.AudioContext || window.webkitAudioContext;
            if (!Ctor) return null;
            try { audioCtx = new Ctor(); } catch (e) { return null; }
        }
        return audioCtx;
    }

    function unlockAudio() {
        var c = audio();
        if (c && c.state === 'suspended') c.resume().catch(function () {});
    }
    // browsers only allow sound after a user gesture; any click/key on the site counts
    ['pointerdown', 'keydown'].forEach(function (type) {
        document.addEventListener(type, unlockAudio, { capture: true, passive: true });
    });

    function beep(c, at) {
        var osc = c.createOscillator();
        var gain = c.createGain();
        osc.type = 'square';
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(0.25, at + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.35);
        osc.connect(gain).connect(c.destination);
        osc.start(at);
        osc.stop(at + 0.4);
    }

    function stopAlarm() {
        if (alarmTimer) { clearInterval(alarmTimer); alarmTimer = null; }
        var box = document.getElementById('xman-emergency');
        if (box) box.classList.remove('is-sounding');
    }

    /** returns false when the browser has not allowed audio yet */
    function startAlarm() {
        stopAlarm();
        var c = audio();
        if (!c || c.state !== 'running') return false;
        var cycles = 0;
        function cycle() {
            if (cycles++ >= ALARM_CYCLES) { stopAlarm(); return; }
            beep(c, c.currentTime + 0.02);
            beep(c, c.currentTime + 0.5);
        }
        cycle();
        alarmTimer = setInterval(cycle, 1500);
        document.getElementById('xman-emergency').classList.add('is-sounding');
        return true;
    }

    // ------------------------------------------------------------------ layer 2: in-website alert
    var SEVERITIES = ['low', 'medium', 'high', 'critical'];
    var current = null;
    var soundEnabled = true;

    function alarmedIds() {
        try { return JSON.parse(sessionStorage.getItem('xman-alarmed') || '[]'); } catch (e) { return []; }
    }
    function rememberAlarmed(id) {
        try {
            var ids = alarmedIds();
            ids.push(id);
            sessionStorage.setItem('xman-alarmed', JSON.stringify(ids.slice(-50)));
        } catch (e) {}
    }

    function setText(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = value || '';
    }

    function render(alerts) {
        var box = document.getElementById('xman-emergency');
        if (!box) return;
        if (!alerts.length) { hide(); return; }
        var a = alerts[0];
        var changed = !current || current.id !== a.id;
        current = a;
        var hazard = a.hazard || {};
        setText('em-title', a.title);
        setText('em-body', a.message);
        setText('em-area', (hazard.affected_districts || []).join(', ') || hazard.district_name || '');
        var level = SEVERITIES.indexOf(a.severity) >= 0 ? a.severity : 'high';
        var sev = document.getElementById('em-sev');
        sev.className = 'sev sev-' + level;
        var labels = document.getElementById('em-sev-labels');
        setText('em-sev-text', ((labels && labels.getAttribute('data-' + level)) || level).toUpperCase());
        var when = a.created_at ? new Date(a.created_at + (/[zZ]|[+-]\d\d:?\d\d$/.test(a.created_at) ? '' : 'Z')) : null;
        setText('em-time', when && !isNaN(when) ? when.toLocaleString() : '');
        var more = document.getElementById('em-more');
        more.hidden = alerts.length < 2;
        setText('em-more-count', String(alerts.length - 1));
        document.getElementById('em-view').setAttribute('href', a.link || '/notifications');
        box.hidden = false;
        if (changed) {
            var heading = document.getElementById('em-title');
            if (heading) heading.focus({ preventScroll: true });
        }
        document.getElementById('em-sound-blocked').hidden = true;
        if (soundEnabled && alarmedIds().indexOf(a.id) < 0) {
            if (startAlarm()) rememberAlarmed(a.id);
            else document.getElementById('em-sound-blocked').hidden = false;
        }
        if (window.lucide && window.lucide.createIcons) window.lucide.createIcons();
    }

    function hide() {
        var box = document.getElementById('xman-emergency');
        if (box) box.hidden = true;
        stopAlarm();
        current = null;
    }

    // One request per page drives: the emergency alert (layer 2), the navbar unread badge, and
    // pages that refresh when a new notification arrives (xman:status). It only reads; it never creates.
    function setUnreadBadges(count) {
        document.querySelectorAll('[data-unread-badge]').forEach(function (b) {
            b.textContent = count;
            b.hidden = !count;
        });
        var page = document.getElementById('unread-count');
        if (page) page.textContent = count;
    }

    function poll() {
        if (!document.getElementById('xman-emergency')) return Promise.resolve();
        return fetch('/api/emergency/active', { credentials: 'same-origin', cache: 'no-store' })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (data) {
                soundEnabled = !!data.sound_enabled;
                render(data.alerts || []);
                if (typeof data.unread_count === 'number') setUnreadBadges(data.unread_count);
                var latest = data.latest_notification_id;
                var changed = lastNotificationId !== undefined && latest !== lastNotificationId;
                lastNotificationId = latest;
                document.dispatchEvent(new CustomEvent('xman:status', {
                    detail: { unreadCount: data.unread_count, latestNotificationId: latest, notificationsChanged: changed }
                }));
            });
    }

    function markRead(id) {
        return post('/api/notifications/' + encodeURIComponent(id) + '/read', {});
    }

    document.addEventListener('click', function (e) {
        if (!current) return;
        if (e.target.closest('#em-mute')) { stopAlarm(); rememberAlarmed(current.id); return; }
        if (e.target.closest('#em-play')) {
            unlockAudio();
            setTimeout(function () { if (startAlarm()) { rememberAlarmed(current.id); document.getElementById('em-sound-blocked').hidden = true; } }, 50);
            return;
        }
        if (e.target.closest('#em-dismiss')) { stopAlarm(); markRead(current.id).then(refreshStatus); return; }
        var view = e.target.closest('#em-view');
        if (view) {
            e.preventDefault();
            stopAlarm();
            var href = view.getAttribute('href');
            markRead(current.id).then(function () { window.location.href = href; });
        }
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && current) stopAlarm();
    });

    var statusLoop = null;
    function refreshStatus() { if (statusLoop) statusLoop.run(); else poll().catch(function () {}); }
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.addEventListener('message', function (e) {
            if (e.data && e.data.type === 'xman-push') refreshStatus();  // a push arrived: show it now
        });
    }
    if (document.getElementById('xman-emergency')) {
        if (window.XmanLive) statusLoop = window.XmanLive.every('status', POLL_MS, poll, { hiddenMs: HIDDEN_POLL_MS });
        else poll().catch(function () {});
    }

    // ------------------------------------------------------------------ layer 3: Web Push opt-in
    function keyBytes(base64url) {
        var padded = (base64url + '===='.slice((base64url.length % 4) || 4)).replace(/-/g, '+').replace(/_/g, '/');
        var raw = atob(padded);
        var out = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
        return out;
    }

    var XmanPush = {
        supported: function () {
            return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
        },
        secure: function () { return window.isSecureContext === true; },
        registration: function () {
            return navigator.serviceWorker.register('/sw.js');
        },
        /** browser-side truth: {permission: default|granted|denied|unsupported|insecure, subscribed} */
        browserState: function () {
            if (!XmanPush.supported()) return Promise.resolve({ permission: 'unsupported', subscribed: false });
            if (!XmanPush.secure()) return Promise.resolve({ permission: 'insecure', subscribed: false });
            return XmanPush.registration().then(function (reg) {
                return reg.pushManager.getSubscription();
            }).then(function (sub) {
                return { permission: Notification.permission, subscribed: !!sub, subscription: sub };
            }).catch(function () {
                return { permission: Notification.permission, subscribed: false };
            });
        },
        /** Must be called from a click: asks the browser for permission, then subscribes. */
        enable: function (publicKey, sound) {
            if (!XmanPush.supported() || !XmanPush.secure()) {
                return post('/api/push/state', { state: 'unsupported' }).then(function () { return { ok: false, reason: 'unsupported' }; });
            }
            unlockAudio();
            var permission = Notification.requestPermission();
            return Promise.resolve(permission).then(function (result) {
                if (result !== 'granted') {
                    return post('/api/push/state', { state: result === 'denied' ? 'denied' : 'not_requested' })
                        .then(function () { return { ok: false, reason: result === 'denied' ? 'denied' : 'dismissed' }; });
                }
                return XmanPush.registration().then(function (reg) {
                    return navigator.serviceWorker.ready.then(function () { return reg.pushManager.getSubscription(); })
                        .then(function (sub) {
                            return sub || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) });
                        });
                }).then(function (sub) {
                    return post('/api/push/subscribe', { subscription: sub.toJSON() });
                }).then(function (data) {
                    if (data.httpStatus !== 201) return { ok: false, reason: 'server', error: data.error };
                    return post('/api/emergency/sound', { enabled: sound !== false }).then(function () { return { ok: true }; });
                }).catch(function () { return { ok: false, reason: 'subscribe' }; });
            });
        },
        disable: function () {
            var browser = XmanPush.supported() && XmanPush.secure()
                ? XmanPush.browserState().then(function (s) { return s.subscription ? s.subscription.unsubscribe() : null; }).catch(function () {})
                : Promise.resolve();
            return browser.then(function () { return post('/api/push/unsubscribe', {}); });
        },
        /** keep server + browser consistent on page load (never prompts) */
        reconcile: function (server) {
            return XmanPush.browserState().then(function (b) {
                if (server.state === 'disabled_by_user' && b.subscription) {
                    return b.subscription.unsubscribe().then(function () { return b; }, function () { return b; });
                }
                if (b.permission === 'granted' && b.subscription && server.configured &&
                        server.state !== 'disabled_by_user' && (server.state !== 'granted' || !server.subscriptions)) {
                    return post('/api/push/subscribe', { subscription: b.subscription.toJSON() }).then(function () { return b; });
                }
                if (!server.subscriptions && server.state !== 'disabled_by_user') {
                    var reported = b.permission === 'denied' ? 'denied'
                        : (b.permission === 'unsupported' || b.permission === 'insecure') ? 'unsupported' : null;
                    if (reported && reported !== server.state) {
                        return post('/api/push/state', { state: reported }).then(function () { return b; });
                    }
                }
                return b;
            });
        },
        test: function () { return post('/api/push/test', {}); },
        setSound: function (enabled) {
            if (enabled) unlockAudio(); else stopAlarm();
            return post('/api/emergency/sound', { enabled: !!enabled });
        },
        previewSound: function () {
            unlockAudio();
            setTimeout(function () {
                var c = audio();
                if (c && c.state === 'running') { beep(c, c.currentTime + 0.02); beep(c, c.currentTime + 0.5); }
            }, 50);
        }
    };
    window.XmanPush = XmanPush;
})();
