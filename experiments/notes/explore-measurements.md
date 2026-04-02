# Exploration Branch Measurements

Branch: `explore/hands-free-speed`
Date: 2026-04-02

## TTS First-Chunk Latency

### Persistent Subprocess vs One-Shot (Baseline)

Environment: same machine, same Piper model (`en_US-lessac-medium.onnx`), 3 runs per text.
Warm-up: one dummy synthesis call before measurements.

| Text | Chars | Persistent first-chunk (avg) | One-shot first-chunk (avg) | Improvement |
|------|-------|------------------------------|---------------------------|-------------|
| "Hello, how can I help you today?" | 32 | 75.6ms | 1446.8ms | 94.8% |
| "I received your turn..." | 76 | 53.4ms | 1515.8ms | 96.5% |
| "The weather in Kuwait City..." | 90 | 191.0ms | 1527.0ms | 87.5% |

Warm-up cost (model loading): ~6385ms (once at startup).

### Streaming Reads Without Persistent Process

Finding: provides zero benefit. Piper writes all output at once after synthesis completes.
First read arrives at 1362ms out of 1402ms total - essentially the same as full-buffer.

### End-to-End Estimate

Backend delay (fake backend): ~200ms
TTS first chunk (persistent, typical): ~137ms
Estimated total: ~337ms vs ~1700ms baseline

## VAD Simulation Results

Parameters tested: start=0.035, stop=0.012, EMA alpha=0.3, stop_frames=7, endpoint=600ms.

| Test | Result |
|------|--------|
| Simple utterance (2s speech + silence) | 1 speech start, 1 endpoint (pass) |
| Two sentences with 500ms pause | 1 endpoint, no over-segmentation (pass) |
| Brief noise spike in silence | 0 false triggers (pass) |
| Hesitant speech with RMS dips | 1 endpoint, no over-segmentation (pass) |
| Endpoint timing accuracy | 640ms gap vs 600ms target (within 1 frame, pass) |

## Conclusions

1. Persistent subprocess is the dominant improvement. ~95% reduction in first-chunk latency.
2. Piper should remain the default TTS. No need to evaluate alternatives at these latencies.
3. VAD tuning is sound but needs real headset validation.
