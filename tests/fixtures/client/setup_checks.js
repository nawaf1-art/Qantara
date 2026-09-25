// Behavioural checks for client/setup/index.html.
// Run: node setup_checks.js <check-name>   (exit code 0 = pass)
"use strict";
const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const { loadPage, walk, REPO_ROOT } = require("./harness");

const PAGE = path.join(REPO_ROOT, "client", "setup", "index.html");

function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body };
}

function makeFetch(routes) {
  return async (url, init) => {
    for (const [prefix, handler] of Object.entries(routes)) {
      if (url.startsWith(prefix)) return jsonResponse(typeof handler === "function" ? handler(url, init) : handler);
    }
    if (url.startsWith("/api/auth/status")) return jsonResponse({ required: false, authenticated: true });
    if (url.startsWith("/api/mesh/")) return jsonResponse({ enabled: false, peers: [] });
    return jsonResponse({});
  };
}

async function boot(opts) {
  const h = loadPage(Object.assign({ page: "setup", location: { protocol: "http:", host: "127.0.0.1:8765", hostname: "127.0.0.1", port: "8765", href: "http://127.0.0.1:8765/setup/index.html", search: "" } }, opts));
  await h.flush();
  return h;
}

async function finishProbe(h, backends) {
  const es = h.eventSources.find((e) => e.url === "/api/backends/stream");
  assert.ok(es, "setup streams backend probes");
  h.lastBackends = backends;
  es._emit("done", { backends });
  await h.flush();
  await h.advance(0);
  await h.flush();
}

function cards(h) {
  return h.$("backend-list").childNodes.filter((c) => c.className.includes("backend-card"));
}

function card(h, type) {
  const all = cards(h);
  const byData = all.find((c) => c.dataset.backendType === type);
  if (byData) return byData;
  // Cards render in payload order (also true for pages without data attributes).
  const order = (h.lastBackends || []).map((b) => b.type);
  return all[order.indexOf(type)];
}

function findAll(root, pred) {
  const out = [];
  walk(root, (n) => { if (pred(n)) out.push(n); });
  return out;
}

const OLLAMA = { type: "ollama", name: "Ollama", available: true, models: [{ name: "m1" }, { name: "m2" }] };
const MOCK = { type: "mock", name: "Mock", available: true };
const OPENAI_MANUAL = { type: "openai_compatible", name: "OpenAI-Compatible", available: true, auto_detected: false, servers: [] };
const OFFLINE = { type: "openclaw", name: "OpenClaw", available: false, installed: false };

const checks = {
  // Q-09: mesh peers from mDNS are rendered as text.
  async mesh_peers_rendered_as_text() {
    const evil = "<img src=x onerror=alert(1)>";
    const h = await boot({
      fetch: makeFetch({
        "/api/mesh/status": { enabled: true, node_id: "node-a", role: "coordinator" },
        "/api/mesh/peers": { enabled: true, peers: [{ node_id: evil, role: "<svg onload=x>", host: "10.0.0.2", port: 9000 }] },
      }),
    });
    await h.advance(10);
    const list = h.$("mesh-peers-list");
    assert.equal(h.$("mesh-panel").hidden, false);
    assert.ok(list.textContent.includes(evil), "peer id shown literally");
    assert.ok(list.textContent.includes("<svg onload=x> @ 10.0.0.2:9000"));
    assert.equal(h.dom.innerHTMLWrites.filter((w) => w.html.includes("onerror")).length, 0);
  },

  // Q-09 + CSP prep: no innerHTML / insertAdjacentHTML / inline handlers.
  async no_markup_injection_or_inline_handlers() {
    for (const page of ["setup", "translate", "transport-spike"]) {
      const src = fs.readFileSync(path.join(REPO_ROOT, "client", page, "index.html"), "utf8");
      assert.ok(!/\son[a-z]+\s*=\s*["']/i.test(src), `${page}: no inline on*= handlers`);
      assert.ok(!/\.innerHTML\s*=(?!=)/.test(src), `${page}: no innerHTML assignments`);
      assert.ok(!/insertAdjacentHTML|outerHTML\s*=/.test(src), `${page}: no HTML string insertion`);
    }
    const h = await boot({ fetch: makeFetch({}) });
    await finishProbe(h, [{ type: "probe", name: "<b>x</b>", available: false }, MOCK]);
    assert.equal(h.dom.innerHTMLWrites.length, 0, "rendering never writes innerHTML");
  },

  // CL-13: copy buttons work without navigator.clipboard (plain-HTTP LAN).
  async copy_button_falls_back() {
    const h = await boot({ fetch: makeFetch({}), clipboard: null });
    await finishProbe(h, [Object.assign({}, OLLAMA, { available: false }), MOCK]);
    const btns = findAll(h.$("getting-started-area"), (n) => n.className === "copy-btn");
    assert.ok(btns.length >= 1, "getting-started copy button rendered");
    btns[0].click();
    assert.deepEqual(h.dom.document.execCommandCalls, ["copy"], "execCommand fallback used");
    assert.equal(btns[0].textContent, "Copied");
    const scan = findAll(h.$("getting-started-area"), (n) => n.className === "scan-btn");
    assert.equal(scan.length, 1);
    assert.ok((scan[0].handlers.click || []).length === 1, "Scan Again wired with addEventListener");

    const writes = [];
    const h2 = await boot({ fetch: makeFetch({}), clipboard: { writeText: async (t) => { writes.push(t); } } });
    await finishProbe(h2, [Object.assign({}, OLLAMA, { models: [] }), MOCK]);
    card(h2, "ollama").click();
    const cfgCopy = findAll(h2.$("config-area"), (n) => n.className === "copy-btn");
    assert.equal(cfgCopy.length, 1, "no-models copy button rendered");
    cfgCopy[0].click();
    await h2.flush();
    assert.deepEqual(writes, ["ollama pull qwen3.5:2b"]);
    assert.equal(cfgCopy[0].textContent, "Copied");
    await h2.advance(1600);
    assert.equal(cfgCopy[0].textContent, "Copy");
  },

  // U-4: restore saved settings once; never after the user interacts.
  async restore_saved_settings_once() {
    const saved = { type: "openai_compatible", url: "http://10.0.0.5:1234", model: "qwen" };
    let backendsPayload = [OPENAI_MANUAL, MOCK, OFFLINE];
    const h = await boot({
      localStorage: { qantara_backend: JSON.stringify(saved) },
      fetch: makeFetch({
        "/api/test-url": (_u, init) => {
          const body = JSON.parse(init.body);
          return { ok: true, url: body.url, models: ["llama", "qwen"] };
        },
        "/api/backends": () => ({ backends: backendsPayload }),
      }),
    });
    await finishProbe(h, backendsPayload);
    await h.advance(10);
    assert.ok(card(h, "openai_compatible").classList.contains("selected"), "saved backend restored");
    assert.equal(h.$("cfg-openai-url").value, saved.url);
    assert.equal(h.$("cfg-openai-model").value, "qwen", "saved model restored after the Test call returns");
    // User picks Mock with the keyboard.
    card(h, "mock").fire("keydown", { key: "Enter" });
    assert.ok(card(h, "mock").classList.contains("selected"));
    // No real backend -> the page polls every 5 s; the poll must not undo the user's choice.
    await h.advance(5100);
    await h.advance(5100);
    assert.ok(h.fetchCalls.filter((c) => c.url === "/api/backends").length >= 2, "polling happened");
    assert.ok(card(h, "mock").classList.contains("selected"), "poll did not re-apply saved settings");
    assert.ok(!card(h, "openai_compatible").classList.contains("selected"));
  },

  async restore_waits_for_backend_then_stops() {
    const saved = { type: "ollama", model: "m2" };
    let payload = [Object.assign({}, OLLAMA, { available: false }), MOCK];
    const h = await boot({
      localStorage: { qantara_backend: JSON.stringify(saved) },
      fetch: makeFetch({ "/api/backends": () => ({ backends: payload }) }),
    });
    await finishProbe(h, payload);
    assert.ok(!cards(h).some((c) => c.classList.contains("selected")), "nothing selected while Ollama is down");
    payload = [OLLAMA, MOCK];
    h.lastBackends = payload;
    await h.advance(5100);
    assert.ok(card(h, "ollama").classList.contains("selected"), "restored once Ollama appears");
    assert.equal(h.$("cfg-model").value, "m2");
    h.$("cfg-model").value = "m1";
    h.$("cfg-model").fire("change");
    await h.advance(5100);
    assert.equal(h.$("cfg-model").value, "m1", "user's model kept");
  },

  // U-5: backend and LAN cards are keyboard operable.
  async cards_are_keyboard_operable() {
    const h = await boot({ fetch: makeFetch({}) });
    await finishProbe(h, [OLLAMA, MOCK, OFFLINE]);
    const c = card(h, "ollama");
    assert.equal(c.getAttribute("role"), "button");
    assert.equal(c.getAttribute("tabindex"), "0");
    assert.equal(c.getAttribute("aria-pressed"), "false");
    const ev = c.fire("keydown", { key: " " });
    assert.equal(ev.defaultPrevented, true, "Space does not scroll the page");
    assert.ok(card(h, "ollama").classList.contains("selected"));
    assert.equal(card(h, "ollama").getAttribute("aria-pressed"), "true");
    assert.equal(card(h, "ollama").focused, true, "focus follows the re-rendered card");
    assert.equal(card(h, "openclaw").getAttribute("aria-disabled"), "true");
    assert.equal(card(h, "openclaw").getAttribute("tabindex"), null);
    c.fire("keydown", { key: "a" });
    // OpenClaw agent list uses real radio inputs.
    const h2 = await boot({ fetch: makeFetch({}) });
    await finishProbe(h2, [{ type: "openclaw", name: "OpenClaw", available: true, installed: true, gateway_running: true, agents: [{ id: "a1", name: "One" }, { id: "a2", name: "Two" }] }, MOCK]);
    card(h2, "openclaw").fire("keydown", { key: "Enter" });
    const radio = h2.$("cfg-agent-1");
    assert.equal(radio.type, "radio");
    radio.checked = true;
    radio.fire("change");
    assert.equal(h2.$("start-btn").disabled, false, "agent chosen via radio enables Start");
    assert.equal(h2.$("cfg-agent-1").focused, true);
    // LAN discovery cards.
    const h3 = await boot({ fetch: makeFetch({}) });
    h3.$("scan-lan-btn").click();
    const es = h3.eventSources.find((e) => e.url === "/api/discovery/scan");
    es._emit("found", { server_type: "vLLM", url: "http://10.0.0.9:8000", health: "healthy", latency_ms: 12, models: [] });
    const lan = h3.$("lan-results").childNodes[0];
    assert.equal(lan.getAttribute("role"), "button");
    assert.equal(lan.getAttribute("tabindex"), "0");
    assert.ok((lan.handlers.keydown || []).length === 1);
  },

  async status_messages_are_live_regions() {
    const src = fs.readFileSync(PAGE, "utf8");
    assert.ok(/id="status-msg"[^>]*aria-live="polite"/.test(src));
    assert.ok(/id="auth-status"[^>]*aria-live="polite"/.test(src));
  },
};

const name = process.argv[2];
if (name === "--list") {
  console.log(Object.keys(checks).join("\n"));
  process.exit(0);
}
if (!checks[name]) {
  console.error(`unknown check ${name}`);
  process.exit(2);
}
checks[name]().then(
  () => process.exit(0),
  (err) => { console.error(err && err.stack ? err.stack : err); process.exit(1); },
);
