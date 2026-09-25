/*
 * Qantara microphone capture: anti-aliased resampler, 16 kHz packetizer and
 * the AudioWorklet processor that runs them off the main thread.
 *
 * This one static file is loaded two ways (no build step):
 *   1. audioContext.audioWorklet.addModule("mic-capture-worklet.js")
 *      -> registers the "qantara-mic-capture" AudioWorkletProcessor.
 *   2. <script src="mic-capture-worklet.js"> on the voice page
 *      -> exposes window.QantaraCapture, used by the ScriptProcessor
 *         fallback for browsers without AudioWorklet.
 *
 * The resampler is a windowed-sinc (Blackman) low-pass evaluated at the
 * output instants, so content above ~7.8 kHz is removed *before* it can fold
 * back into the 0-8 kHz band of the 16 kHz stream. The previous per-chunk
 * averaging downsampler only attenuated 9 kHz by ~4.6 dB (audit U-8).
 */
(function (scope) {
  "use strict";

  var DEFAULT_TARGET_RATE = 16000;
  var DEFAULT_PACKET_SAMPLES = 640; // 40 ms at 16 kHz, the gateway's frame size
  var DEFAULT_CUTOFF_HZ = 7000;
  var DEFAULT_TRANSITION_HZ = 1600;
  var PHASES = 512;

  function blackman(n, N) {
    // n in [0, N]
    var a = (2 * Math.PI * n) / N;
    return 0.42 - 0.5 * Math.cos(a) + 0.08 * Math.cos(2 * a);
  }

  function sinc(x) {
    if (x === 0) return 1;
    var px = Math.PI * x;
    return Math.sin(px) / px;
  }

  /**
   * Streaming arbitrary-ratio resampler with an anti-aliasing low-pass.
   * process(Float32Array) -> Float32Array of output samples (may be empty).
   */
  function QantaraResampler(inRate, outRate, options) {
    options = options || {};
    this.inRate = inRate;
    this.outRate = outRate;
    this.step = inRate / outRate;
    this.passthrough = inRate === outRate;
    if (this.passthrough) return;

    var nyquistLimit = 0.4375 * Math.min(inRate, outRate); // 7 kHz for 16 kHz
    var cutoffHz = Math.min(options.cutoffHz || DEFAULT_CUTOFF_HZ, nyquistLimit);
    var transitionHz = options.transitionHz || DEFAULT_TRANSITION_HZ;
    // Blackman: transition width ~= 5.5 / taps (in units of the input rate).
    var halfWidth = Math.max(4, Math.ceil((2.75 * inRate) / transitionHz));
    var taps = 2 * halfWidth;
    var fc = cutoffHz / inRate; // cycles per input sample
    var table = new Array(PHASES);
    for (var p = 0; p < PHASES; p += 1) {
      var frac = p / PHASES;
      var row = new Float32Array(taps);
      var sum = 0;
      for (var k = 0; k < taps; k += 1) {
        // Tap k multiplies input sample (i - halfWidth + 1 + k); the output
        // instant sits at i + frac, so the tap's distance is x below.
        var x = (k - halfWidth + 1) - frac;
        var w = blackman(x + halfWidth, taps);
        var h = 2 * fc * sinc(2 * fc * x) * (w > 0 ? w : 0);
        row[k] = h;
        sum += h;
      }
      if (sum !== 0) {
        for (var j = 0; j < taps; j += 1) row[j] /= sum; // unity DC gain per phase
      }
      table[p] = row;
    }
    this.cutoffHz = cutoffHz;
    this.halfWidth = halfWidth;
    this.taps = taps;
    this.table = table;
    this.buf = new Float32Array(Math.max(4096, taps * 4));
    this.len = halfWidth - 1; // history of zeros so the first output is causal
    this.t = halfWidth - 1;
  }

  QantaraResampler.prototype.process = function (input) {
    if (this.passthrough) {
      return new Float32Array(input);
    }
    var needed = this.len + input.length;
    if (needed > this.buf.length) {
      var grown = new Float32Array(Math.max(needed, this.buf.length * 2));
      grown.set(this.buf.subarray(0, this.len));
      this.buf = grown;
    }
    this.buf.set(input, this.len);
    this.len += input.length;

    var W = this.halfWidth;
    var taps = this.taps;
    var buf = this.buf;
    var out = new Float32Array(Math.ceil(input.length / this.step) + 2);
    var count = 0;
    for (;;) {
      var i = Math.floor(this.t);
      var p = Math.round((this.t - i) * PHASES);
      if (p === PHASES) { i += 1; p = 0; }
      if (i + W >= this.len) break;
      var row = this.table[p];
      var base = i - W + 1;
      var acc = 0;
      for (var k = 0; k < taps; k += 1) acc += buf[base + k] * row[k];
      if (count >= out.length) {
        var bigger = new Float32Array(out.length * 2);
        bigger.set(out);
        out = bigger;
      }
      out[count] = acc;
      count += 1;
      this.t += this.step;
    }
    var drop = Math.floor(this.t) - W;
    if (drop > 0) {
      buf.copyWithin(0, drop, this.len);
      this.len -= drop;
      this.t -= drop;
    }
    return out.subarray(0, count);
  };

  function floatToInt16(floatArray) {
    var pcm = new Int16Array(floatArray.length);
    for (var i = 0; i < floatArray.length; i += 1) {
      var s = Math.max(-1, Math.min(1, floatArray[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return pcm;
  }

  /** Collects 16 kHz float samples into fixed-size Int16 packets + RMS. */
  function QantaraPacketizer(packetSamples, onPacket) {
    this.packetSamples = packetSamples || DEFAULT_PACKET_SAMPLES;
    this.onPacket = onPacket;
    this.pending = new Float32Array(this.packetSamples);
    this.fill = 0;
  }

  QantaraPacketizer.prototype.push = function (samples) {
    var n = this.packetSamples;
    for (var i = 0; i < samples.length; i += 1) {
      this.pending[this.fill] = samples[i];
      this.fill += 1;
      if (this.fill === n) {
        var sumSq = 0;
        for (var k = 0; k < n; k += 1) sumSq += this.pending[k] * this.pending[k];
        var rms = Math.sqrt(sumSq / n);
        this.onPacket(floatToInt16(this.pending), rms);
        this.fill = 0;
      }
    }
  };

  /** Device-rate float input -> 16 kHz Int16 packets with their RMS. */
  function QantaraCapturePipeline(inRate, options, onPacket) {
    options = options || {};
    this.resampler = new QantaraResampler(inRate, options.targetRate || DEFAULT_TARGET_RATE, options);
    this.packetizer = new QantaraPacketizer(options.packetSamples || DEFAULT_PACKET_SAMPLES, onPacket);
  }

  QantaraCapturePipeline.prototype.process = function (input) {
    this.packetizer.push(this.resampler.process(input));
  };

  var api = {
    Resampler: QantaraResampler,
    Packetizer: QantaraPacketizer,
    Pipeline: QantaraCapturePipeline,
    floatToInt16: floatToInt16,
    DEFAULT_TARGET_RATE: DEFAULT_TARGET_RATE,
    DEFAULT_PACKET_SAMPLES: DEFAULT_PACKET_SAMPLES,
  };
  scope.QantaraCapture = api;

  if (typeof registerProcessor === "function" && typeof AudioWorkletProcessor === "function") {
    class QantaraMicCaptureProcessor extends AudioWorkletProcessor {
      constructor(options) {
        super();
        var settings = (options && options.processorOptions) || {};
        var port = this.port;
        // `sampleRate` is a global of AudioWorkletGlobalScope.
        this.pipeline = new QantaraCapturePipeline(sampleRate, settings, function (pcm, rms) {
          port.postMessage({ pcm: pcm, rms: rms }, [pcm.buffer]);
        });
        this.stopped = false;
        var self = this;
        port.onmessage = function (event) {
          if (event.data && event.data.type === "stop") self.stopped = true;
        };
      }

      process(inputs) {
        if (this.stopped) return false;
        var channel = inputs[0] && inputs[0][0];
        if (channel && channel.length) this.pipeline.process(channel);
        return true;
      }
    }
    registerProcessor("qantara-mic-capture", QantaraMicCaptureProcessor);
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
