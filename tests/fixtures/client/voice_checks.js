// Behavioural checks for client/transport-spike/index.html (the voice page).
// Run: node voice_checks.js <check-name>   (exit code 0 = pass)
"use strict";
const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { loadPage, walk, REPO_ROOT } = require("./harness");

const FRAME_MS = 40;
const PAGE = path.join(REPO_ROOT, "client", "transport-spike", "index.html");
const WORKLET = path.join(REPO_ROOT, "client", "transport-spike", "mic-capture-worklet.js");

async function boot(opts = {}) {
  const h = loadPage(Object.assign({ page: "transport-spike" }, opts));
  await h.flush();
  return h;
}

async function openSocket(h) {
  const ws = h.lastSocket();
  assert.ok(ws, "page should auto-connect on load");
  ws._open();
  await h.flush();
  return ws;
}

async function pressStart(h) {
  h.$("startBtn").click();
  await h.flush();
  await h.flush();
}

async function ready(opts = {}) {
  const h = await boot(opts);
  const ws = await openSocket(h);
  await pressStart(h);
  assert.equal(h.evalIn("micActive"), true, "mic should be running after Start");
  return { h, ws };
}

function workletNode(h) {
  const nodes = h.audio.workletNodes;
  assert.ok(nodes.length > 0, "AudioWorkletNode expected");
  return nodes[nodes.length - 1];
}

async function feed(h, rms, frames) {
  const node = workletNode(h);
  for (let i = 0; i < frames; i++) {
    node.port.onmessage({ data: { pcm: new Int16Array(640), rms } });
    await h.advance(FRAME_MS);
  }
}

function count(ws, type) {
  return ws.types().filter((t) => t === type).length;
}

function collectText(el) {
  const out = [];
  walk(el, (n) => { if (n._text) out.push(n._text); });
  return out.join("|");
}

async function startReply(h, ws, rate = 22050) {
  ws._recvJson({ type: "turn_state", state: "active" });
  ws._recvJson({ type: "tts_status", engine: "piper", sample_rate: rate });
  ws._recvPcm(new Array(1920).fill(1000));
  await h.flush();
}

const checks = {
  // Q-02: URL must come from location.host (works behind the HTTPS proxy).
  async ws_url_uses_location_host() {
    const cases = [
      [{ protocol: "https:", hostname: "qantara.local", port: "", host: "qantara.local" }, "wss://qantara.local/ws"],
      [{ protocol: "http:", hostname: "127.0.0.1", port: "8765", host: "127.0.0.1:8765" }, "ws://127.0.0.1:8765/ws"],
      [{ protocol: "https:", hostname: "box", port: "8443", host: "box:8443" }, "wss://box:8443/ws"],
      [{ protocol: "file:", hostname: "", port: "", host: "" }, "ws://127.0.0.1:8765/ws"],
    ];
    for (const [loc, expected] of cases) {
      const h = await boot({ location: Object.assign({ href: "x", search: "" }, loc) });
      assert.equal(h.sockets.length, 1, "auto-connect opens exactly one socket");
      assert.equal(h.sockets[0].url, expected);
      assert.equal(h.evalIn("buildWsUrl")(loc), expected);
    }
    const src = fs.readFileSync(PAGE, "utf8");
    assert.ok(!/location\.port/.test(src), "voice page must not build URLs from location.port");
  },

  // U-2: double Connect / stale socket handlers.
  async double_connect_and_stale_socket() {
    const h = await boot();
    assert.equal(h.sockets.length, 1);
    const btn = h.$("connectBtn");
    btn.disabled = false; // even if the button were clickable
    btn.click(); btn.click();
    await h.flush();
    assert.equal(h.sockets.length, 1, "no duplicate socket while connecting");
    const ws1 = h.sockets[0];
    ws1._open(); await h.flush();
    h.$("connectBtn").click(); await h.flush();
    assert.equal(h.sockets.length, 1, "no duplicate socket while connected");
    assert.equal(h.$("connectBtn").disabled, true);
    // Network drop -> reconnect creates ws2; a late event from ws1 is ignored.
    ws1._drop(1006); await h.flush();
    await h.advance(1000);
    assert.equal(h.sockets.length, 2);
    const ws2 = h.sockets[1];
    ws2._open(); await h.flush();
    ws1._emit("close", { code: 1006, wasClean: false, reason: "" });
    ws1._emit("message", { data: JSON.stringify({ type: "turn_state", state: "active" }) });
    await h.flush();
    assert.equal(h.evalIn("isSocketOpen()"), true, "stale close must not tear down the live socket");
    assert.equal(h.evalIn("backendTurnActive"), false, "stale message must be ignored");
  },

  // U-2: double Start Mic.
  async double_start_mic_is_guarded() {
    const h = await boot({ gum: ["defer"] });
    await openSocket(h);
    h.$("startBtn").click();
    h.$("startBtn").click();
    h.$("micBtn").click();
    await h.flush();
    assert.equal(h.media.calls.length, 1, "getUserMedia requested once");
    assert.equal(h.$("startBtn").disabled, true, "Start disabled while the mic starts");
    h.media.pending[0].resolve();
    await h.flush(); await h.flush();
    assert.equal(h.audio.workletNodes.length, 1, "one capture pipeline");
    assert.equal(h.evalIn("micActive"), true);
    assert.equal(h.$("startBtn").textContent, "Stop");
  },

  // U-2: auto-reconnect keeps (or restarts) the mic.
  async reconnect_restores_mic() {
    const { h, ws } = await ready();
    ws._drop(1006); await h.flush();
    await h.advance(1000);
    const ws2 = h.lastSocket();
    assert.notEqual(ws2, ws);
    ws2._open(); await h.flush(); await h.flush();
    assert.equal(h.evalIn("micActive"), true, "mic still on after reconnect");
    assert.ok(ws2.types().includes("mic_stream_started"), "new session told the mic is streaming");
    await feed(h, 0.001, 2);
    assert.ok(ws2.pcmFrames().length >= 2, "audio flows to the new socket");
  },

  // U-2: track ended + devicechange; AudioContext statechange.
  async device_loss_and_recovery() {
    const { h } = await ready();
    const track = h.media.tracks[0];
    track._end(); await h.flush();
    assert.equal(h.evalIn("micActive"), false);
    assert.equal(h.$("convoNotice").hidden, false);
    assert.match(h.$("convoNotice").textContent, /microphone was disconnected/i);
    h.media.mediaDevicesFire = null;
    h.sandbox.navigator.mediaDevices._fire("devicechange");
    await h.flush(); await h.flush();
    assert.equal(h.media.calls.length, 2, "devicechange restarts capture");
    assert.equal(h.evalIn("micActive"), true);
  },

  async audio_context_suspend_is_handled() {
    const { h } = await ready({ resumeBlocked: true });
    const ctx = h.audio.contexts[0];
    ctx._setState("suspended");
    await h.flush(); await h.flush();
    assert.ok(ctx.resumeCalls >= 1, "tries to resume after a suspend");
    assert.equal(h.$("startBtn").textContent, "Resume");
    assert.match(h.$("stateCaption").textContent, /paused/i);
    ctx._setState("running");
    await h.flush();
    assert.equal(h.$("startBtn").textContent, "Stop");
  },

  // Q-05b: playback_cleared re-arms barge-in even without playback_stopped.
  async bargein_rearms_on_playback_cleared() {
    const { h, ws } = await ready();
    ws._recvJson({ type: "turn_state", state: "active" });
    await feed(h, 0.05, 5);
    assert.equal(count(ws, "clear_playback"), 1);
    ws._recvJson({ type: "cancel_status", result: { status: "cancelled" } });
    ws._recvJson({ type: "turn_interrupted", partial_text: "", resumable: true, interrupted_during_state: "thinking" });
    ws._recvJson({ type: "playback_cleared", generation: 1 });
    ws._recvJson({ type: "turn_state", state: "idle" });
    await feed(h, 0.0, 10);
    assert.equal(h.evalIn("clearPending"), false, "clearPending released by playback_cleared");
    assert.equal(h.$("clearBtn").textContent, "Clear Playback");
    await h.advance(3000);
    await startReply(h, ws);
    await feed(h, 0.05, 5);
    assert.equal(count(ws, "clear_playback"), 2, "second reply can be interrupted");
    assert.ok(h.audio.sources.some((s) => s.stopped), "second barge-in stops playback");
  },

  // Q-05b: frames between clear and its ack are dropped.
  async late_frames_after_clear_are_dropped() {
    const { h, ws } = await ready();
    await startReply(h, ws);
    const before = h.audio.sources.length;
    assert.equal(before, 1);
    await feed(h, 0.05, 5);
    assert.equal(count(ws, "clear_playback"), 1);
    ws._recvPcm(new Array(1920).fill(1000)); // sent before the server saw the clear
    await h.flush();
    assert.equal(h.audio.sources.length, before, "late frame not scheduled");
    ws._recvJson({ type: "playback_stopped", reason: "cleared" });
    ws._recvPcm(new Array(1920).fill(1000));
    await h.flush();
    assert.equal(h.audio.sources.length, before, "still dropped until playback_cleared");
    ws._recvJson({ type: "playback_cleared", generation: 2 });
    ws._recvPcm(new Array(1920).fill(1000));
    await h.flush();
    assert.equal(h.audio.sources.length, before + 1, "new-generation audio plays");
  },

  async clear_ack_timeout_rearms() {
    const { h, ws } = await ready();
    await startReply(h, ws);
    await feed(h, 0.05, 5);
    assert.equal(h.evalIn("clearPending"), true);
    await h.advance(3100);
    assert.equal(h.evalIn("clearPending"), false, "missing ack does not wedge barge-in");
  },

  // CL-13: weak-speech filter really rejects short bursts.
  async weak_speech_filter_rejects_short_bursts() {
    const { h, ws } = await ready({ localStorage: { qantara_audio_mode: "headset" } });
    await h.advance(2000);
    await feed(h, 0.03, 5); // 200 ms cough
    await feed(h, 0.0, 10);
    await h.advance(1500);
    assert.equal(h.evalIn("weakSpeechSkipCount"), 1);
    assert.equal(count(ws, "transcribe_recent_audio"), 0);
    await feed(h, 0.03, 15); // 600 ms utterance
    await feed(h, 0.0, 10);
    await h.advance(1500);
    assert.equal(count(ws, "transcribe_recent_audio"), 1);
    assert.equal(h.evalIn("weakSpeechSkipCount"), 1);
    const pure = h.evalIn("isWeakUtterance");
    assert.equal(pure({ durationMs: 280, avgRms: 0.05, peakRms: 0.1 }), true);
    assert.equal(pure({ durationMs: 320, avgRms: 0.05, peakRms: 0.1 }), false);
  },

  // V-7: default audio mode is headset.
  async default_audio_mode_is_headset() {
    const h = await boot();
    assert.equal(h.evalIn("audioMode"), "headset");
    assert.equal(h.$("audioMode").value, "headset");
    const h2 = await boot({ localStorage: { qantara_audio_mode: "speakers" } });
    assert.equal(h2.evalIn("audioMode"), "speakers");
  },

  // V-7: barge-in utterances are exempt from the cooldown and a submit that
  // lands while the turn is still winding down is deferred, not dropped.
  async speakers_bargein_utterance_is_submitted() {
    for (const idleDelay of [100, 800, 2500]) {
      const { h, ws } = await ready({ localStorage: { qantara_audio_mode: "speakers" } });
      await startReply(h, ws);
      let t = 0; let clearAt = null; let idleSent = false; let idleAt = null; let submitAt = null;
      for (let i = 0; i < 110; i++) {
        await feed(h, t < 1000 ? 0.08 : 0.0, 1);
        t += FRAME_MS;
        if (submitAt == null && count(ws, "transcribe_recent_audio")) submitAt = t;
        if (clearAt == null && count(ws, "clear_playback")) {
          clearAt = t;
          ws._recvJson({ type: "playback_cleared", generation: 1 });
          ws._recvJson({ type: "playback_stopped", reason: "cleared", kind: "piper_tts" });
          ws._recvJson({ type: "turn_interrupted", partial_text: "Sure", resumable: true, interrupted_during_state: "speaking" });
        }
        if (clearAt != null && !idleSent && t >= clearAt + idleDelay) {
          idleSent = true;
          idleAt = t;
          ws._recvJson({ type: "turn_state", state: "idle" });
        }
      }
      // Endpoint: speech ends at 1000 ms, +7 silent frames, +1200 ms.
      const endpointAt = 1000 + 7 * FRAME_MS + 1200;
      assert.ok(submitAt != null && submitAt - Math.max(endpointAt, idleAt) <= 3 * FRAME_MS,
        `submitted promptly, not after the echo cooldown (submit ${submitAt}, endpoint ${endpointAt}, idle ${idleAt})`);
      assert.ok(clearAt != null, "speakers-mode barge-in fires");
      assert.equal(count(ws, "transcribe_recent_audio"), 1, `interrupting utterance submitted (idle after ${idleDelay} ms)`);
    }
  },

  async deferred_submit_expires() {
    const { h, ws } = await ready();
    ws._recvJson({ type: "turn_state", state: "active" });
    ws._recvJson({ type: "cancel_status", result: {} });
    await feed(h, 0.05, 15);
    // server never acknowledges the clear and never ends the turn
    await feed(h, 0.0, 10);
    await h.advance(1300);
    assert.equal(h.evalIn("deferredSubmit") !== null, true, "deferred while the turn is active");
    await h.advance(5000);
    assert.equal(count(ws, "transcribe_recent_audio"), 0);
    assert.equal(h.evalIn("deferredSubmit"), null, "deferral gives up eventually");
  },

  // V-7: speakers barge-in gate is relative to the measured echo.
  async speakers_threshold_tracks_echo() {
    const thr = (await boot()).evalIn("computeSpeakersBargeInThreshold");
    assert.equal(thr(null), 0.06);
    assert.equal(thr(0.005), 0.025, "floor");
    assert.ok(Math.abs(thr(0.03) - 0.06) < 1e-9);
    assert.equal(thr(0.5), 0.12, "ceiling");

    // Quiet echo (good AEC): a phone-level interruption (0.04) gets through.
    {
      const { h, ws } = await ready({ localStorage: { qantara_audio_mode: "speakers" } });
      await startReply(h, ws);
      await feed(h, 0.008, 20);
      assert.ok(h.evalIn("echoLevel") < 0.01);
      await feed(h, 0.04, 10);
      assert.equal(count(ws, "clear_playback"), 1, "phone-level barge-in accepted over quiet echo");
    }
    // Loud echo with short peaks: no self-interruption.
    {
      const { h, ws } = await ready({ localStorage: { qantara_audio_mode: "speakers" } });
      await startReply(h, ws);
      for (let k = 0; k < 10; k++) {
        await feed(h, 0.05, 5);
        await feed(h, 0.075, 3);
      }
      assert.equal(count(ws, "clear_playback"), 0, "echo does not self-trigger barge-in");
      assert.ok(h.evalIn("computeSpeakersBargeInThreshold(echoLevel)") > 0.075);
    }
  },

  // V-4: playout cushion, underrun growth and detune-aware scheduling.
  async playout_scheduler_cushion_and_detune() {
    const eff = (await boot()).evalIn("effectivePlaybackRate");
    assert.ok(Math.abs(eff({ playbackRate: 0.95, detune: -140 }) - 0.95 * Math.pow(2, -140 / 1200)) < 1e-12);
    for (const preset of ["steady", "warm", "bright", "swift"]) {
      const { h, ws } = await ready({ localStorage: { qantara_voice_preset: preset } });
      ws._recvJson({ type: "tts_status", engine: "piper", sample_rate: 22050 });
      const t0 = h.clock.now / 1000;
      // A 250 ms burst up front then real-time pacing (server lead).
      for (let k = 0; k < 4; k++) ws._recvPcm(new Array(1920).fill(1000));
      await h.flush();
      const src = h.audio.sources;
      assert.ok(Math.abs(src[0].startAt - (t0 + 0.1)) < 1e-9, "first chunk gets a 100 ms cushion");
      for (let k = 1; k < src.length; k++) {
        const p = src[k - 1];
        const rate = p.playbackRate.value * Math.pow(2, p.detune.value / 1200);
        const end = p.startAt + p.buffer.duration / rate;
        assert.ok(Math.abs(src[k].startAt - end) < 1e-9, `${preset}: chunks are contiguous (no gap/overlap)`);
      }
    }
    // Underrun grows the cushion, capped at 250 ms.
    const { h, ws } = await ready();
    ws._recvJson({ type: "tts_status", engine: "piper", sample_rate: 16000 });
    ws._recvPcm(new Array(640).fill(1000));
    await h.flush();
    for (let k = 0; k < 6; k++) {
      await h.advance(400); // queue runs dry
      ws._recvPcm(new Array(640).fill(1000));
      await h.flush();
    }
    assert.equal(h.evalIn("playbackUnderruns"), 6);
    assert.ok(Math.abs(h.evalIn("playoutCushionS") - 0.25) < 1e-9);
    const last = h.audio.sources[h.audio.sources.length - 1];
    assert.ok(Math.abs(last.startAt - (h.clock.now / 1000 + 0.25)) < 1e-9);
  },

  async jitter_produces_no_gaps() {
    let seed = 7;
    const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
    const { h, ws } = await ready();
    ws._recvJson({ type: "tts_status", engine: "piper", sample_rate: 22050 });
    const D = 1920 / 22050 * 1000;
    const base = h.clock.now;
    const arrivals = [];
    for (let k = 0; k < 115; k++) arrivals.push(base + k * D + rnd() * 60);
    arrivals.sort((a, b) => a - b);
    for (const t of arrivals) { await h.advance(t - h.clock.now); ws._recvPcm(new Array(1920).fill(1000)); }
    await h.flush();
    let gaps = 0;
    const src = h.audio.sources;
    for (let k = 1; k < src.length; k++) {
      const p = src[k - 1];
      if (src[k].startAt - (p.startAt + p.buffer.duration) > 0.0005) gaps++;
    }
    assert.equal(gaps, 0, `60 ms jitter must not cause gaps (got ${gaps})`);
    assert.equal(h.evalIn("playbackUnderruns"), 0);
  },

  // V-4: sample rate never changes mid-utterance; tone plays at 16 kHz.
  async sample_rate_changes_only_between_utterances() {
    const { h, ws } = await ready();
    ws._recvJson({ type: "tts_status", engine: "piper", sample_rate: 22050 });
    ws._recvPcm(new Array(1920).fill(1));
    ws._recvJson({ type: "session_updated", sample_rate: 24000 });
    ws._recvPcm(new Array(1920).fill(1));
    await h.flush();
    const rates = () => h.audio.sources.map((s) => s.buffer.sampleRate);
    assert.deepEqual(rates(), [22050, 22050]);
    ws._recvJson({ type: "playback_stopped", reason: "piper_tts_complete", kind: "piper_tts" });
    ws._recvPcm(new Array(1920).fill(1));
    await h.flush();
    assert.deepEqual(rates(), [22050, 22050, 24000]);
    ws._recvJson({ type: "playback_stopped", reason: "piper_tts_complete", kind: "piper_tts" });
    h.$("toneBtn").click(); await h.flush();
    ws._recvPcm(new Array(640).fill(1));
    await h.flush();
    assert.equal(rates()[3], 16000, "tone frames play at 16 kHz");
    ws._recvJson({ type: "playback_stopped", reason: "tone_complete", kind: "synthetic_tone" });
    ws._recvPcm(new Array(640).fill(1));
    await h.flush();
    assert.equal(rates()[4], 24000);
  },

  // U-3: mic error explanations.
  async mic_errors_are_explained() {
    {
      const h = await boot({ isSecureContext: false });
      await openSocket(h);
      await pressStart(h);
      assert.equal(h.media.calls.length, 0, "no getUserMedia on an insecure origin");
      assert.match(h.$("convoNotice").textContent, /HTTPS/);
    }
    {
      const h = await boot({ noMediaDevices: true });
      await openSocket(h);
      await pressStart(h);
      assert.match(h.$("convoNotice").textContent, /can't capture/);
    }
    const cases = [
      ["NotAllowedError", /blocked/],
      ["NotFoundError", /No microphone/],
      ["NotReadableError", /busy/],
    ];
    for (const [name, re] of cases) {
      const h = await boot({ gum: [{ error: name }] });
      await openSocket(h);
      await pressStart(h);
      assert.match(h.$("convoNotice").textContent, re, name);
      assert.equal(h.evalIn("micActive"), false);
      assert.equal(h.$("startBtn").textContent, "Start");
    }
  },

  // F-1: echoCancellation "all" with fallback.
  async echo_cancellation_all_with_fallback() {
    {
      const { h } = await ready();
      assert.deepEqual(JSON.parse(JSON.stringify(h.media.calls[0].audio.echoCancellation)), { ideal: "all" });
      assert.equal(h.evalIn("statValues.echoCancel"), "all");
    }
    {
      const h = await boot({ gum: [{ error: "OverconstrainedError" }, "ok"] });
      await openSocket(h);
      await pressStart(h);
      assert.equal(h.media.calls.length, 2);
      assert.equal(h.media.calls[1].audio.echoCancellation, true, "falls back to boolean echoCancellation");
      assert.equal(h.evalIn("micActive"), true);
    }
    {
      const h = await boot({ supportedConstraints: {} });
      await openSocket(h);
      await pressStart(h);
      assert.equal(h.media.calls[0].audio.echoCancellation, true);
    }
  },

  // F-1 / U-8: AudioWorklet capture with ScriptProcessor fallback.
  async capture_uses_worklet_with_fallback() {
    {
      const { h, ws } = await ready();
      assert.deepEqual(h.audio.addModuleCalls, ["mic-capture-worklet.js"]);
      const node = workletNode(h);
      assert.equal(node.name, "qantara-mic-capture");
      assert.equal(node.options.processorOptions.targetRate, 16000);
      assert.equal(node.options.processorOptions.packetSamples, 640);
      await feed(h, 0.01, 3);
      assert.equal(ws.pcmFrames().length, 3);
      assert.equal(ws.pcmFrames()[0].byteLength, 1 + 640 * 2);
    }
    for (const variant of [{ worklet: false }, { workletAddModuleFails: true }]) {
      const { h, ws } = await ready(variant);
      assert.equal(h.audio.processors.length, 1, "ScriptProcessor fallback");
      assert.equal(h.evalIn("captureKind"), "script-processor");
      const proc = h.audio.processors[0];
      for (let b = 0; b < 30; b++) {
        const a = new Float32Array(2048);
        for (let i = 0; i < 2048; i++) a[i] = 0.3 * Math.sin(2 * Math.PI * 300 * (b * 2048 + i) / 48000);
        proc.onaudioprocess({ inputBuffer: { getChannelData: () => a } });
      }
      const frames = ws.pcmFrames().length;
      // 30 * 2048 samples @48k = 1.28 s -> 20480 samples @16k -> 32 packets (minus filter latency)
      assert.ok(frames >= 31 && frames <= 32, `fallback produced ${frames} packets`);
    }
  },

  // U-8: anti-aliasing resampler frequency response.
  async resampler_frequency_response() {
    const ctx = {};
    vm.createContext(ctx);
    vm.runInContext(fs.readFileSync(WORKLET, "utf8"), ctx);
    const Q = ctx.QantaraCapture;
    function gainDb(inRate, f) {
      const r = new Q.Resampler(inRate, 16000);
      const out = [];
      for (let off = 0; off < inRate; off += 128) {
        const a = new Float32Array(128);
        for (let i = 0; i < 128; i++) a[i] = 0.5 * Math.sin(2 * Math.PI * f * (off + i) / inRate);
        for (const v of r.process(a)) out.push(v);
      }
      const tail = out.slice(2000);
      const rms = Math.sqrt(tail.reduce((s, x) => s + x * x, 0) / tail.length);
      return { db: 20 * Math.log10(rms / (0.5 / Math.SQRT2)), n: out.length };
    }
    for (const inRate of [48000, 44100]) {
      for (const f of [300, 1000, 3400, 6000]) {
        const { db } = gainDb(inRate, f);
        assert.ok(Math.abs(db) < 0.5, `${inRate} Hz: ${f} Hz passband ${db.toFixed(2)} dB`);
      }
      for (const f of [9000, 12000, 20000]) {
        const { db } = gainDb(inRate, f);
        assert.ok(db < -60, `${inRate} Hz: ${f} Hz must be rejected (got ${db.toFixed(1)} dB)`);
      }
      const { n } = gainDb(inRate, 1000);
      assert.ok(Math.abs(n - 16000) < 100, `output rate ~16 kHz (${n})`);
    }
    // Packetizer: 640-sample Int16 packets with RMS.
    const got = [];
    const pk = new Q.Packetizer(640, (pcm, rms) => got.push([pcm.length, rms]));
    pk.push(new Float32Array(1300).fill(0.5));
    assert.equal(got.length, 2);
    assert.equal(got[0][0], 640);
    assert.ok(Math.abs(got[0][1] - 0.5) < 1e-6);
  },

  // U-1 / U-3 / CL-13: event-driven conversation panel.
  async conversation_panel_is_event_driven() {
    const { h, ws } = await ready();
    const logEl = h.$("conversationLog");
    ws._recvJson({ type: "transcript_result", text: "what is the capital of france", engine: "fw" });
    ws._recvJson({ type: "turn_state", state: "active" });
    ws._recvJson({ type: "assistant_text_delta", text: "Paris is the capital." });
    ws._recvJson({ type: "assistant_text_delta", text: "It is in France." });
    await h.flush();
    let text = collectText(logEl);
    assert.ok(text.includes("what is the capital of france"));
    assert.ok(text.includes("Paris is the capital. It is in France."), "sentences separated");
    ws._recvJson({ type: "assistant_text_final", text: "Paris is the capital of France." });
    ws._recvJson({ type: "turn_state", state: "idle" });
    ws._recvJson({ type: "transcript_result", text: "and germany", engine: "fw" });
    ws._recvJson({ type: "turn_state", state: "active" });
    ws._recvJson({ type: "assistant_text_delta", text: "Berlin" });
    await h.flush();
    const turns = logEl.childNodes.filter((n) => n.className === "turn");
    assert.equal(turns.length, 2, "one list item per turn");
    const second = collectText(turns[1]);
    assert.ok(second.includes("Berlin") && !second.includes("Paris"), "streaming text does not run into the previous turn");
    assert.equal(h.$("assistantText").textContent, "Berlin");
    ws._recvJson({ type: "turn_failed", message: "backend timed out", failure_kind: "timeout", retriable: true });
    ws._recvJson({ type: "turn_state", state: "idle" });
    ws._recvJson({ type: "transcript_result", text: "", engine: "faster_whisper", error: "CUDA out of memory" });
    ws._recvJson({ type: "tts_status", engine: "piper", sample_rate: 22050, reason: "no_voice_for_language", language: "ar" });
    await h.flush();
    text = collectText(logEl);
    assert.ok(text.includes("backend timed out") && text.includes("timeout") && text.includes("try again"), "turn_failed shown");
    assert.ok(text.includes("CUDA out of memory"), "STT error shown");
    assert.ok(/No voice is installed/.test(text), "tts reason shown");
    // a11y
    assert.equal(logEl.getAttribute ? true : true, true);
    assert.ok(/id="conversationLog"[^>]*aria-live="polite"/.test(h.html));
    assert.ok(/id="stateCaption"[^>]*aria-live="polite"/.test(h.html));
    let dirAuto = 0;
    walk(logEl, (n) => { if (n.getAttribute && n.getAttribute("dir") === "auto") dirAuto++; });
    assert.ok(dirAuto >= 5, "every message text carries dir=auto");
    // Debug is collapsed by default and the dead overlay is gone.
    assert.ok(/<details class="panel" id="debugPanel">/.test(h.html), "debug panel collapsed by default");
    assert.ok(!/useVoiceMode|vcCaptions|voiceMode|setInterval/.test(h.html), "no dead overlay / polling code");
  },

  async barge_in_keeps_old_turn_text_separate() {
    const { h, ws } = await ready();
    ws._recvJson({ type: "transcript_result", text: "tell me a story", engine: "fw" });
    ws._recvJson({ type: "turn_state", state: "active" });
    ws._recvJson({ type: "assistant_text_delta", text: "Once upon a time" });
    ws._recvJson({ type: "partial_transcript_ready", text: "stop", stable_prefix_chars: 0 });
    ws._recvJson({ type: "turn_interrupted", partial_text: "Once upon a time", resumable: true });
    ws._recvJson({ type: "turn_state", state: "idle" });
    ws._recvJson({ type: "transcript_result", text: "stop please", engine: "fw" });
    await h.flush();
    const turns = h.$("conversationLog").childNodes.filter((n) => n.className === "turn");
    assert.equal(turns.length, 2);
    assert.ok(collectText(turns[0]).includes("(interrupted)"));
    assert.ok(collectText(turns[1]).includes("stop please"));
    assert.ok(!collectText(turns[1]).includes("Once upon"));
  },

  async state_caption_and_start_gesture() {
    const h = await boot();
    assert.match(h.$("stateCaption").textContent, /Connecting/);
    const ws = await openSocket(h);
    assert.match(h.$("stateCaption").textContent, /Press Start/);
    assert.equal(h.audio.contexts.length, 0, "no AudioContext before the user gesture");
    await pressStart(h);
    assert.equal(h.audio.contexts.length, 1, "Start creates/resumes one shared AudioContext");
    assert.match(h.$("stateCaption").textContent, /Listening/);
    ws._recvJson({ type: "turn_state", state: "active" });
    assert.match(h.$("stateCaption").textContent, /Thinking/);
  },

  // U-6: bounded log, no per-token logging.
  async debug_log_is_bounded() {
    const { h, ws } = await ready();
    const before = h.evalIn("logEntries.length");
    ws._recvJson({ type: "turn_state", state: "active" });
    for (let i = 0; i < 500; i++) ws._recvJson({ type: "assistant_text_delta", text: " tok" });
    assert.ok(h.evalIn("logEntries.length") - before <= 2, "deltas are not logged");
    for (let i = 0; i < 1000; i++) h.evalIn(`log("line ${i}")`);
    assert.equal(h.evalIn("logEntries.length"), 300);
    assert.equal(h.$("log").textContent, "", "log DOM untouched while Debug is closed");
    h.$("debugPanel").open = true;
    h.$("debugPanel").fire("toggle");
    const lines = h.$("log").textContent.split("\n");
    assert.equal(lines.length, 300);
    assert.ok(lines[0].endsWith("line 999"), "newest first");
  },

  // CL-13: session_init carries speech_rate only after the user changed it.
  async speech_rate_sent_only_when_user_set() {
    {
      const h = await boot();
      const ws = await openSocket(h);
      const init = ws.json().find((m) => m.type === "session_init");
      assert.ok(!("speech_rate" in init), "server default applies");
      ws._recvJson({ type: "session_ready", speech_rate: 1.1 });
      assert.equal(h.store.get("qantara_speech_speed"), undefined, "server echo is not persisted");
      h.$("speechSpeed").value = "1.20";
      h.$("speechSpeed").fire("input");
      const upd = ws.json().filter((m) => m.type === "session_update").pop();
      assert.equal(upd.speech_rate, 1.2);
    }
    {
      const h = await boot({ localStorage: { qantara_speech_speed: "1.15", qantara_speech_speed_user: "1" } });
      const ws = await openSocket(h);
      assert.equal(ws.json().find((m) => m.type === "session_init").speech_rate, 1.15);
    }
    {
      // Legacy value written by the old page from server echoes is ignored.
      const h = await boot({ localStorage: { qantara_speech_speed: "1.00" } });
      const ws = await openSocket(h);
      assert.ok(!("speech_rate" in ws.json().find((m) => m.type === "session_init")));
    }
  },

  // CL-13: avatar returns to idle/listening after a reply.
  async avatar_returns_to_rest() {
    const { h, ws } = await ready();
    await startReply(h, ws);
    for (let k = 0; k < 2; k++) ws._recvPcm(new Array(1920).fill(1000));
    ws._recvJson({ type: "playback_stopped", reason: "piper_tts_complete" });
    ws._recvJson({ type: "turn_state", state: "idle" });
    await h.advance(600);
    h.audio.sources.forEach((s) => s.onended && s.onended());
    await h.advance(1000);
    assert.equal(h.$("avatarBadge").textContent, "listening");
    assert.equal(h.$("avatarShell").className, "avatar-shell listening");
    assert.equal(h.evalIn("lastMouthLevel"), 0);
  },

  // Q-09 / CSP prep: no innerHTML with data, no inline handlers.
  async voice_page_has_no_innerhtml_or_inline_handlers() {
    const src = fs.readFileSync(PAGE, "utf8");
    assert.ok(!/\.innerHTML\s*=/.test(src), "no innerHTML assignments");
    assert.ok(!/\son[a-z]+="/i.test(src), "no inline on*= handlers");
    const { h, ws } = await ready();
    ws._recvJson({ type: "transcript_result", text: "<img src=x onerror=alert(1)>", engine: "fw" });
    ws._recvJson({ type: "assistant_activity", activity_type: "tool_call", summary: "<b>x</b>" });
    assert.equal(h.dom.innerHTMLWrites.length, 0);
  },
};

const name = process.argv[2];
if (!name || !checks[name]) {
  if (name === "--list") {
    console.log(Object.keys(checks).join("\n"));
    process.exit(0);
  }
  console.error(`unknown check ${name}; available:\n${Object.keys(checks).join("\n")}`);
  process.exit(2);
}
checks[name]().then(
  () => process.exit(0),
  (err) => { console.error(err && err.stack ? err.stack : err); process.exit(1); },
);
