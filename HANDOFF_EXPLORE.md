# Exploration Branch Handoff: explore/hands-free-speed

Branch: `explore/hands-free-speed`
Base: `v0.1.0-alpha.1`
Date: 2026-04-02

## What Changed

This branch takes a different path from the main line, focused on two goals: hands-free operation and lower TTS latency.

### 1. Persistent Piper Subprocess (biggest win)

**File:** `gateway/transport_spike/tts_piper.py`

The baseline Piper TTS path spawned a new subprocess per synthesis call. Each call paid the full cost of Python startup + ONNX model loading + inference, resulting in ~1.5s first-chunk latency.

This branch keeps a single persistent Piper subprocess alive across calls. The model loads once on startup (warm-up), and subsequent synthesis calls only pay the inference cost.

**Measured results:**

| Text length | Persistent first-chunk | One-shot (baseline) | Improvement |
|-------------|----------------------|--------------------|----|
| 32 chars | **75.6ms** | 1446.8ms | **94.8% faster** |
| 76 chars | **53.4ms** | 1515.8ms | **96.5% faster** |
| 90 chars | **191.0ms** | 1527.0ms | **87.5% faster** |

Warm-up takes ~6.4s (once, at gateway startup). After that, first-chunk latency drops from **~1.5s to ~50-190ms** depending on text length.

Estimated end-to-end (backend delay + TTS first chunk): **~337ms** vs ~1700ms baseline.

### 2. Streaming TTS Reads

**File:** `gateway/transport_spike/tts_piper.py`, `server.py`

`synthesize_stream()` reads Piper's stdout in chunks as they arrive and yields sample buffers immediately. `send_pcm_stream()` in server.py sends these frames to the browser as they arrive.

**Finding:** With a per-call subprocess, streaming reads provide zero benefit because Piper writes all output at once. However, with the persistent subprocess, the streaming approach works correctly and delivers chunks incrementally (15 reads for a typical synthesis).

### 3. Progressive Text Chunking

**File:** `gateway/transport_spike/server.py`

- First chunk: 28 characters or sentence-ending punctuation (`.!?;:`)
- Later chunks: 60 characters or sentence-ending punctuation

Gets TTS started earlier. Also fixed the chunk tracking to use `spoken_so_far` offset instead of prefix string matching.

### 4. Auto-Submit on Endpoint-Ready

**File:** `client/transport-spike/index.html`

Toggle button. When enabled, automatically transcribes and submits recent speech when the endpoint timer fires. Off by default.

### 5. VAD Stability

**File:** `client/transport-spike/index.html`

- EMA smoothing on RMS (alpha=0.3)
- Speech-start threshold: 0.035 (was 0.03)
- Speech-stop threshold: 0.012 (was 0.015)
- Stop-frame count: 7 (was 5)
- Endpoint silence: 600ms (was 700ms)

**Validated by simulation:**
- Simple utterance: 1 clean endpoint (pass)
- Two sentences with 500ms pause: no over-segmentation (pass)
- Brief noise spike: no false triggers (pass)
- Hesitant speech with RMS dips: no over-segmentation (pass)
- Endpoint timing: 640ms gap vs 600ms target (within tolerance)

### 6. WebSocket Auto-Reconnect

**File:** `client/transport-spike/index.html`

Exponential backoff (500ms-8s) on unexpected disconnect. Disabled on intentional disconnect.

## What Worked

- **Persistent subprocess** is the clear winner. ~95% reduction in first-chunk latency.
- **EMA-smoothed VAD** eliminates noise spike false positives without adding lag.
- **Auto-submit** is simple, correct, and doesn't interfere with manual testing.

## What Did Not Work

- **Streaming reads alone** (without persistent subprocess) provide zero benefit. Piper buffers internally and writes all output at once. The streaming architecture only pays off when combined with the persistent process.

## Risks

1. **Persistent process lifetime**: If the Piper process crashes mid-session, the next call will fail. The code handles this by detecting a dead process and restarting, but there will be one ~6s warm-up penalty.
2. **Concurrency**: The `asyncio.Lock` serializes TTS calls. If two speech chunks are queued, the second waits for the first to complete. This matches the existing sequential playback model but could be a bottleneck if the architecture changes.
3. **Silence timeout heuristic**: The 300ms silence timeout to detect end-of-synthesis is fragile. If Piper takes longer than 300ms between stdout writes for a single synthesis, we'll incorrectly split the output. In practice, Piper writes all output in a burst, so this hasn't been observed.
4. **VAD thresholds**: Validated by simulation only, not by real headset runs. May need tuning for different microphones.

## Is This Path Better Than The Baseline?

**Yes, definitively.** The persistent subprocess alone drops first-chunk TTS from ~1.5s to ~50-190ms. Combined with progressive chunking and 200ms backend delay, the estimated end-to-end time-to-first-audio is ~337ms vs ~1700ms on the mainline.

**Recommendation:** Merge the persistent subprocess TTS, auto-submit, and VAD changes into the main line. The streaming read architecture is correct but only matters because of the persistent process - without it, streaming reads are useless.

Piper should remain the default TTS path. At ~50-190ms first-chunk with a persistent process, there is no urgency to evaluate alternative engines.
