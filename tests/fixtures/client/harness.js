// Minimal DOM / WebAudio / WebSocket / media stubs that run the REAL inline
// scripts of a client page (client/<page>/index.html) inside node:vm with a
// controllable fake clock. Adapted from the 2026-09-24 audit probe harness.
"use strict";
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");

function extractScripts(htmlPath) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const re = /<script(\s[^>]*)?>([\s\S]*?)<\/script>/g;
  const scripts = [];
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[1] || "";
    const src = /\ssrc="([^"]+)"/.exec(attrs);
    if (src) {
      const file = path.join(path.dirname(htmlPath), src[1]);
      scripts.push({ filename: file, code: fs.readFileSync(file, "utf8") });
    } else {
      scripts.push({ filename: `${htmlPath}#inline${scripts.length}`, code: m[2] });
    }
  }
  return { html, scripts };
}

function makeClock() {
  const clock = { now: 0 };
  const timers = [];
  let seq = 1;
  function setTimeoutFake(fn, ms) {
    const id = seq++;
    timers.push({ id, at: clock.now + Math.max(0, ms || 0), fn, every: 0 });
    return id;
  }
  function setIntervalFake(fn, ms) {
    const id = seq++;
    timers.push({ id, at: clock.now + Math.max(1, ms || 0), fn, every: Math.max(1, ms || 0) });
    return id;
  }
  function clearTimeoutFake(id) {
    const i = timers.findIndex((t) => t.id === id);
    if (i >= 0) timers.splice(i, 1);
  }
  async function flush() {
    for (let i = 0; i < 30; i++) await Promise.resolve();
  }
  async function advance(ms) {
    const target = clock.now + ms;
    for (;;) {
      timers.sort((a, b) => a.at - b.at || a.id - b.id);
      const next = timers[0];
      if (!next || next.at > target) break;
      const at = next.at;
      if (next.every) next.at += next.every;
      else timers.shift();
      clock.now = Math.max(clock.now, at);
      next.fn();
      await flush();
    }
    clock.now = target;
    await flush();
  }
  return { clock, timers, setTimeoutFake, setIntervalFake, clearTimeoutFake, flush, advance };
}

function makeDom() {
  const byId = new Map();
  const created = [];
  const innerHTMLWrites = [];
  class El {
    constructor(tag, id) {
      this.tagName = String(tag || "div").toUpperCase();
      this._id = id || "";
      this._text = "";
      this.childNodes = [];
      this.parentNode = null;
      this.attributes = {};
      this.dataset = {};
      this.style = { setProperty() {}, cssText: "", display: "" };
      this._classes = new Set();
      this.handlers = {};
      this.value = "";
      this.disabled = false;
      this.hidden = false;
      this.open = false;
      this.checked = false;
      this.title = "";
      this.scrollTop = 0;
      this.scrollHeight = 0;
      this.clientHeight = 0;
      this.focused = false;
      const self = this;
      this.classList = {
        add: (...c) => c.forEach((x) => self._classes.add(x)),
        remove: (...c) => c.forEach((x) => self._classes.delete(x)),
        toggle: (c, force) => {
          const on = force === undefined ? !self._classes.has(c) : !!force;
          if (on) self._classes.add(c); else self._classes.delete(c);
          return on;
        },
        contains: (c) => self._classes.has(c),
      };
    }
    get id() { return this._id; }
    set id(v) { this._id = String(v); if (v) byId.set(String(v), this); }
    get className() { return Array.from(this._classes).join(" "); }
    set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
    get textContent() { return this._text + this.childNodes.map((c) => c.textContent).join(""); }
    set textContent(v) {
      this.childNodes.forEach((c) => { c.parentNode = null; });
      this.childNodes = [];
      this._text = v == null ? "" : String(v);
    }
    get innerHTML() { return this._innerHTML || ""; }
    set innerHTML(v) {
      innerHTMLWrites.push({ el: this, html: String(v) });
      this._innerHTML = String(v);
      this.textContent = "";
    }
    get firstChild() { return this.childNodes[0] || null; }
    get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
    get children() { return this.childNodes; }
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = this;
      this.childNodes.push(c);
      return c;
    }
    prepend(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = this;
      this.childNodes.unshift(c);
    }
    removeChild(c) {
      const i = this.childNodes.indexOf(c);
      if (i >= 0) { this.childNodes.splice(i, 1); c.parentNode = null; }
      return c;
    }
    insertAdjacentHTML(_pos, html) { innerHTMLWrites.push({ el: this, html: String(html) }); }
    setAttribute(k, v) { this.attributes[k] = String(v); if (k === "id") this.id = String(v); }
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null; }
    removeAttribute(k) { delete this.attributes[k]; }
    addEventListener(t, fn) { (this.handlers[t] = this.handlers[t] || []).push(fn); }
    removeEventListener(t, fn) { const l = this.handlers[t] || []; const i = l.indexOf(fn); if (i >= 0) l.splice(i, 1); }
    dispatchEvent(ev) {
      if (!ev.target) ev.target = this;
      (this.handlers[ev.type] || []).slice().forEach((f) => f(ev));
      return true;
    }
    fire(type, extra) {
      const ev = Object.assign({ type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} }, extra || {});
      (this.handlers[type] || []).slice().forEach((f) => f(ev));
      return ev;
    }
    click() { if (this.disabled) return; this.fire("click"); }
    focus() { this.focused = true; }
    blur() { this.focused = false; }
    select() {}
    querySelector() { return null; }
    querySelectorAll() { return []; }
    closest() { return null; }
    get options() { return this.childNodes; }
  }
  const document = {
    getElementById(id) {
      if (!byId.has(id)) byId.set(id, new El("div", id));
      return byId.get(id);
    },
    createElement(tag) { const el = new El(tag); created.push(el); return el; },
    createTextNode(text) { const el = new El("#text"); el._text = String(text); return el; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    execCommandCalls: [],
    _l: {},
    addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); },
    removeEventListener() {},
    execCommand(cmd) { this.execCommandCalls.push(cmd); return true; },
    activeElement: null,
    hidden: false,
  };
  document.body = new El("body", "body");
  return { El, document, byId, created, innerHTMLWrites };
}

function walk(el, fn) {
  fn(el);
  (el.childNodes || []).forEach((c) => walk(c, fn));
}

// ---------------------------------------------------------------- WebSocket
function makeWebSocketClass(sockets) {
  class FakeWebSocket {
    constructor(url) {
      this.url = url; this.readyState = 0; this.sent = []; this.binaryType = "blob"; this._l = {};
      sockets.push(this);
    }
    addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); }
    _emit(t, ev) {
      const prop = this["on" + t];
      if (prop) prop(ev);
      (this._l[t] || []).forEach((f) => f(ev));
    }
    send(data) {
      if (this.readyState !== 1) throw new Error("InvalidStateError: not open");
      this.sent.push(data);
    }
    close(code) { if (this.readyState === 3) return; this.readyState = 3; this._emit("close", { code: code || 1000, wasClean: true, reason: "" }); }
    _open() { this.readyState = 1; this._emit("open", {}); }
    _drop(code = 1006) { this.readyState = 3; this._emit("close", { code, wasClean: false, reason: "" }); }
    _recvJson(obj) { this._emit("message", { data: JSON.stringify(obj) }); }
    _recvPcm(samples) {
      const buf = new ArrayBuffer(1 + samples.length * 2);
      const dv = new DataView(buf); dv.setUint8(0, 1);
      for (let i = 0; i < samples.length; i++) dv.setInt16(1 + 2 * i, samples[i], true);
      this._emit("message", { data: buf });
    }
    json() { return this.sent.filter((d) => typeof d === "string").map((d) => JSON.parse(d)); }
    types() { return this.json().map((m) => m.type); }
    pcmFrames() { return this.sent.filter((d) => typeof d !== "string"); }
  }
  FakeWebSocket.CONNECTING = 0; FakeWebSocket.OPEN = 1; FakeWebSocket.CLOSING = 2; FakeWebSocket.CLOSED = 3;
  return FakeWebSocket;
}

// ---------------------------------------------------------------- WebAudio
function makeAudio(clock, opts) {
  const audio = { contexts: [], sources: [], processors: [], workletNodes: [], addModuleCalls: [] };
  class FakeAudioContext {
    constructor(o) {
      this.sampleRate = (o && o.sampleRate) || opts.deviceRate || 48000;
      this.state = opts.initialAudioState || "running";
      this.destination = { kind: "destination" };
      this._l = {};
      this.resumeCalls = 0;
      const ctx = this;
      if (opts.worklet !== false) {
        this.audioWorklet = {
          addModule(url) {
            audio.addModuleCalls.push(url);
            return opts.workletAddModuleFails ? Promise.reject(new Error("addModule failed")) : Promise.resolve();
          },
        };
      }
      audio.contexts.push(ctx);
    }
    get currentTime() { return clock.now / 1000; }
    addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); }
    _setState(s) { this.state = s; (this._l.statechange || []).forEach((f) => f({})); if (this.onstatechange) this.onstatechange({}); }
    resume() { this.resumeCalls += 1; if (!opts.resumeBlocked) this.state = "running"; return Promise.resolve(); }
    close() { this.state = "closed"; return Promise.resolve(); }
    createAnalyser() { return { connect() {}, fftSize: 256, smoothingTimeConstant: 0, getByteTimeDomainData() {} }; }
    createBuffer(ch, len, rate) { return { duration: len / rate, length: len, sampleRate: rate, copyToChannel() {} }; }
    createBufferSource() {
      const s = { buffer: null, playbackRate: { value: 1 }, detune: { value: 0 }, connect() {},
        start(t) { this.startAt = t; }, stop() { this.stopped = true; }, onended: null };
      audio.sources.push(s); return s;
    }
    createMediaStreamSource(stream) { return { stream, connect(n) { this.target = n; }, disconnect() {} }; }
    createScriptProcessor(n) {
      const p = { bufferSize: n, connect() {}, disconnect() { this.disconnected = true; }, onaudioprocess: null };
      audio.processors.push(p); return p;
    }
  }
  class FakeAudioWorkletNode {
    constructor(ctx, name, options) {
      this.context = ctx; this.name = name; this.options = options;
      this.port = { messages: [], postMessage(m) { this.messages.push(m); }, onmessage: null };
      audio.workletNodes.push(this);
    }
    connect() {}
    disconnect() { this.disconnected = true; }
  }
  return { audio, FakeAudioContext, FakeAudioWorkletNode };
}

// ---------------------------------------------------------------- media
function makeMedia(opts) {
  const media = { calls: [], tracks: [], listeners: {}, behaviors: (opts.gum || []).slice(), pending: [] };
  function makeTrack(constraints) {
    const t = {
      kind: "audio", readyState: "live", _l: {}, stopped: false,
      addEventListener(type, f) { (this._l[type] = this._l[type] || []).push(f); },
      removeEventListener(type, f) { const l = this._l[type] || []; const i = l.indexOf(f); if (i >= 0) l.splice(i, 1); },
      stop() { this.stopped = true; this.readyState = "ended"; },
      getSettings() {
        const ec = constraints && constraints.audio && constraints.audio.echoCancellation;
        return { echoCancellation: ec && typeof ec === "object" ? ec.ideal : (ec === undefined ? true : ec) };
      },
      _end() { this.readyState = "ended"; (this._l.ended || []).slice().forEach((f) => f({})); },
    };
    media.tracks.push(t);
    return t;
  }
  function streamFor(constraints) {
    const track = makeTrack(constraints);
    return { getTracks: () => [track], getAudioTracks: () => [track], track };
  }
  const mediaDevices = {
    getSupportedConstraints() { return opts.supportedConstraints || { echoCancellation: true }; },
    getUserMedia(constraints) {
      media.calls.push(constraints);
      const behavior = media.behaviors.length ? media.behaviors.shift() : "ok";
      if (behavior === "defer") {
        return new Promise((resolve, reject) => media.pending.push({ resolve: () => resolve(streamFor(constraints)), reject }));
      }
      if (behavior && typeof behavior === "object" && behavior.error) {
        const e = new Error(behavior.message || behavior.error);
        e.name = behavior.error;
        return Promise.reject(e);
      }
      return Promise.resolve(streamFor(constraints));
    },
    addEventListener(t, f) { (media.listeners[t] = media.listeners[t] || []).push(f); },
    _fire(t) { (media.listeners[t] || []).forEach((f) => f({})); },
  };
  return { media, mediaDevices };
}

/**
 * Load a client page. opts:
 *   page: "transport-spike" | "setup" | "translate"
 *   location, localStorage, isSecureContext, noMediaDevices, gum (behaviors),
 *   fetch(url, init) -> {ok, status, json}, worklet (false disables),
 *   deviceRate, initialAudioState, resumeBlocked, clipboard (object|null)
 */
function loadPage(opts = {}) {
  const page = opts.page || "transport-spike";
  const clientRoot = process.env.QANTARA_CLIENT_ROOT || path.join(REPO_ROOT, "client");
  const htmlPath = path.join(clientRoot, page, "index.html");
  const { html, scripts } = extractScripts(htmlPath);
  const clk = makeClock();
  const dom = makeDom();
  const sockets = [];
  const FakeWebSocket = makeWebSocketClass(sockets);
  const { audio, FakeAudioContext, FakeAudioWorkletNode } = makeAudio(clk.clock, opts);
  const { media, mediaDevices } = makeMedia(opts);

  const store = new Map(Object.entries(opts.localStorage || {}));
  const localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  const fetchCalls = [];
  const defaultFetch = async (url) => ({ ok: true, status: 200, json: async () => (String(url).includes("/api/auth/status") ? { required: false } : { presets: [] }) });
  const fetchImpl = async (url, init) => {
    fetchCalls.push({ url: String(url), init });
    const r = await (opts.fetch || defaultFetch)(String(url), init);
    return r;
  };
  const eventSources = [];
  class FakeEventSource {
    constructor(url) { this.url = url; this._l = {}; this.closed = false; eventSources.push(this); }
    addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); }
    close() { this.closed = true; }
    _emit(t, data) { (this._l[t] || []).forEach((f) => f({ data: JSON.stringify(data) })); }
  }

  const loc = opts.location || { protocol: "http:", hostname: "127.0.0.1", port: "8765", host: "127.0.0.1:8765", href: "http://127.0.0.1:8765/spike/index.html", search: "" };
  const windowListeners = {};
  const navigatorObj = { userAgent: "node-harness" };
  if (!opts.noMediaDevices) navigatorObj.mediaDevices = mediaDevices;
  if (opts.clipboard !== undefined) {
    if (opts.clipboard) navigatorObj.clipboard = opts.clipboard;
  }
  const sandbox = {
    document: dom.document, localStorage, console,
    WebSocket: FakeWebSocket, AudioContext: FakeAudioContext, EventSource: FakeEventSource,
    setTimeout: clk.setTimeoutFake, clearTimeout: clk.clearTimeoutFake,
    setInterval: clk.setIntervalFake, clearInterval: clk.clearTimeoutFake,
    requestAnimationFrame: () => 0, cancelAnimationFrame: () => {},
    performance: { now: () => clk.clock.now },
    crypto: { randomUUID: () => "uuid-1" },
    navigator: navigatorObj,
    fetch: fetchImpl,
    TextDecoder, TextEncoder, DataView, ArrayBuffer, Uint8Array, Int16Array, Float32Array, Math, JSON, Number, String, Date, Promise, Set, Map, Error, TypeError, Array, Object, RegExp, Symbol, Infinity, NaN, isNaN, parseInt, parseFloat,
    Event: class { constructor(t) { this.type = t; } },
    isSecureContext: opts.isSecureContext !== undefined ? opts.isSecureContext : true,
  };
  if (opts.worklet !== false) sandbox.AudioWorkletNode = FakeAudioWorkletNode;
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.location = loc;
  sandbox.addEventListener = (t, fn) => { (windowListeners[t] = windowListeners[t] || []).push(fn); };
  const ctx = vm.createContext(sandbox);
  for (const s of scripts) {
    vm.runInContext(s.code, ctx, { filename: s.filename });
  }
  const evalIn = (code) => vm.runInContext(code, ctx);
  const $ = (id) => dom.document.getElementById(id);
  return {
    html, scripts, sandbox, ctx, evalIn, $, dom, store, sockets, audio, media, fetchCalls, eventSources, windowListeners,
    clock: clk.clock, timers: clk.timers, advance: clk.advance, flush: clk.flush,
    lastSocket: () => sockets[sockets.length - 1],
  };
}

function textOf(el) {
  return el ? el.textContent : "";
}

module.exports = { loadPage, extractScripts, walk, textOf, REPO_ROOT };
