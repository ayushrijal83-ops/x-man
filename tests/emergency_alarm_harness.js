// Runs the real app/static/js/emergency.js against stubbed DOM/fetch/AudioContext. stdin: JSON
// {responses: [/api/emergency/active bodies...], audio: 'running'|'suspended'}. Polls once per response and
// prints, per poll, whether the banner is visible, how many alarms started so far and if "sound blocked" shows.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'js', 'emergency.js'), 'utf8');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

function element() {
    return { hidden: true, textContent: '', className: '', attrs: {}, focus() {}, classList: { add() {}, remove() {} },
             setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; } };
}

async function main() {
    const elements = {};
    let alarms = 0;
    const box = element();
    box.classList = { add: (c) => { if (c === 'is-sounding') alarms++; }, remove() {} };
    elements['xman-emergency'] = box;
    const store = {};
    let registered = null;
    let call = 0;
    const node = () => ({ connect: (n) => n || node(), start() {}, stop() {}, type: '', frequency: {},
                          gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} } });
    function AudioContext() { this.state = input.audio; this.currentTime = 0; this.destination = {}; }
    AudioContext.prototype.createOscillator = node;
    AudioContext.prototype.createGain = node;
    AudioContext.prototype.resume = () => Promise.resolve();
    const document = {
        getElementById: (id) => (elements[id] = elements[id] || element()),
        querySelector: () => ({ content: '' }),
        querySelectorAll: () => [],
        addEventListener() {},
        dispatchEvent() {},
    };
    const ctx = {
        document, console, Promise, JSON, Math, Date, Uint8Array, atob: () => '',
        navigator: {},
        sessionStorage: { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } },
        CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
        fetch: async () => { const body = input.responses[call++]; return { ok: true, json: async () => body }; },
        setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {},
    };
    ctx.window = {
        AudioContext, location: { href: '/' }, isSecureContext: true, lucide: null,
        XmanLive: { every: (name, ms, task) => { registered = task; return { run() {} }; } },
    };
    vm.runInNewContext(SRC, ctx);

    const polls = [];
    for (let i = 0; i < input.responses.length; i++) {
        await registered();
        polls.push({ banner: !box.hidden, alarms, blocked: !document.getElementById('em-sound-blocked').hidden });
    }
    process.stdout.write(JSON.stringify(polls));
}

main().catch((e) => { console.error(e); process.exit(1); });
