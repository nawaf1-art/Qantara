// Behavioural checks for client/translate/index.html.
// Run: node translate_checks.js <check-name>   (exit code 0 = pass)
"use strict";
const assert = require("assert/strict");
const { loadPage } = require("./harness");

async function boot(opts = {}) {
  const h = loadPage(Object.assign({ page: "translate", location: { protocol: "http:", host: "127.0.0.1:8765", hostname: "127.0.0.1", port: "8765", href: "http://127.0.0.1:8765/translate/index.html", search: "" } }, opts));
  await h.flush();
  const ws = h.lastSocket();
  assert.ok(ws, "translate page connects");
  assert.equal(ws.url, "ws://127.0.0.1:8765/ws");
  ws._open();
  await h.flush();
  return { h, ws, btn: h.$("talk-btn"), status: () => h.$("status").textContent };
}

const checks = {
  // U-7: a quick tap while the permission prompt is pending must not start recording.
  async quick_tap_during_permission_prompt() {
    const { h, ws, btn, status } = await boot({ gum: ["defer"] });
    btn.fire("mousedown");
    btn.fire("mouseup");
    h.media.pending[0].resolve();
    await h.flush(); await h.flush();
    assert.ok(!ws.types().includes("mic_stream_started"), "no recording after release");
    assert.equal(status(), "Hold the button to speak");
    assert.equal(btn.classList.contains("active"), false);
    // A real press-and-hold now records and translates on release.
    btn.fire("mousedown");
    await h.flush(); await h.flush();
    assert.ok(ws.types().includes("mic_stream_started"));
    assert.equal(status(), "Listening…");
    btn.fire("mouseup");
    assert.deepEqual(ws.types().slice(-2), ["mic_stream_stopped", "transcribe_recent_audio"]);
    assert.equal(status(), "Translating…");
  },

  // First press that stays held through the prompt records.
  async held_press_through_prompt_records() {
    const { h, ws, btn } = await boot({ gum: ["defer"] });
    btn.fire("mousedown");
    h.media.pending[0].resolve();
    await h.flush(); await h.flush();
    assert.ok(ws.types().includes("mic_stream_started"));
    btn.fire("mouseup");
    assert.ok(ws.types().includes("transcribe_recent_audio"));
  },

  // U-5: Space bar hold-to-talk + touchcancel.
  async keyboard_and_touchcancel() {
    const { h, ws, btn } = await boot();
    const down = btn.fire("keydown", { code: "Space", key: " ", repeat: false });
    assert.equal(down.defaultPrevented, true);
    await h.flush(); await h.flush();
    assert.ok(ws.types().includes("mic_stream_started"));
    btn.fire("keydown", { code: "Space", key: " ", repeat: true });
    await h.flush();
    assert.equal(ws.types().filter((t) => t === "mic_stream_started").length, 1, "auto-repeat ignored");
    btn.fire("keyup", { code: "Space", key: " " });
    assert.ok(ws.types().includes("transcribe_recent_audio"));
    btn.fire("touchstart");
    await h.flush(); await h.flush();
    assert.equal(ws.types().filter((t) => t === "mic_stream_started").length, 2);
    btn.fire("touchcancel");
    assert.equal(ws.types().filter((t) => t === "transcribe_recent_audio").length, 2, "touchcancel ends the recording");
  },

  // U-7: "Translating..." clears on failure and on success.
  async translating_status_clears() {
    const { h, ws, btn, status } = await boot();
    btn.fire("mousedown");
    await h.flush(); await h.flush();
    btn.fire("mouseup");
    assert.equal(status(), "Translating…");
    ws._recvJson({ type: "turn_failed", message: "backend timed out" });
    assert.match(status(), /Translation failed: backend timed out/);
    btn.fire("mousedown");
    await h.flush(); await h.flush();
    btn.fire("mouseup");
    ws._recvJson({ type: "transcript_result", text: "hello", engine: "fw" });
    ws._recvJson({ type: "assistant_text_final", text: "こんにちは" });
    assert.equal(status(), "Hold the button to speak");
    const right = h.$("turns-right").childNodes;
    assert.equal(right[right.length - 1].getAttribute("dir"), "auto");
    ws._recvJson({ type: "transcript_result", text: "", engine: "fw", error: "decoder crashed" });
    assert.match(status(), /decoder crashed/);
  },

  async insecure_context_is_explained() {
    const { h, ws, btn, status } = await boot({ isSecureContext: false });
    btn.fire("mousedown");
    await h.flush();
    assert.equal(h.media.calls.length, 0);
    assert.match(status(), /HTTPS/);
    assert.ok(!ws.types().includes("mic_stream_started"));
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
