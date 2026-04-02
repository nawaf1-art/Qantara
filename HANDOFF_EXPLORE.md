# Exploration Branch Handoff: explore/hands-free-speed

Branch: `explore/hands-free-speed`
Base: `v0.1.0-alpha.1`
Date: 2026-04-02

## What Changed

This branch takes a different path from the main line, focused on two goals: hands-free operation and lower TTS latency.

### 1. Streaming Piper TTS

**File:** `gateway/transport_spike/tts_piper.py`

The baseline Piper TTS path called `proc.communicate()` which waits for the entire synthesis to complete before sending any audio to the browser. First-chunk latency was ~1.50s.

This branch adds `synthesize_stream()` which reads Piper's stdout in chunks as they arrive and yields sample buffers immediately. A new `send_pcm_stream()` function in `server.py` sends these frames to the browser as they arrive, overlapping synthesis with playback.

The legacy `synthesize()` method is preserved for compatibility but now delegates to the streaming path internally.

### 2. Progressive Text Chunking

**File:** `gateway/transport_spike/server.py`

The baseline chunked text at sentence boundaries or 48 characters. This branch uses progressive thresholds:

- First chunk: 28 characters or sentence-ending punctuation (`.!?;:`)
- Later chunks: 60 characters or sentence-ending punctuation

This gets the first TTS call started earlier while keeping later chunks large enough to reduce subprocess overhead.

The chunking also properly tracks `spoken_so_far` instead of a `spoken_prefix` string-match, which is more robust when text arrives incrementally.

### 3. Auto-Submit on Endpoint-Ready

**File:** `client/transport-spike/index.html`

Added an "Auto-Submit" toggle button. When enabled, the browser automatically transcribes and submits recent speech when the endpoint timer fires (stable silence detected). This removes the need to press "Submit Recent Speech" manually.

The toggle is off by default to preserve the manual testing workflow.

### 4. VAD Stability Improvements

**File:** `client/transport-spike/index.html`

- Added exponential moving average (EMA) smoothing on RMS values (`alpha=0.3`) to reduce VAD jitter from frame-to-frame noise spikes
- Raised speech-start threshold from 0.03 to 0.035 to reduce false positives
- Lowered speech-stop threshold from 0.015 to 0.012 for cleaner silence detection
- Increased stop-frame count from 5 to 7 to avoid cutting off during brief pauses
- Reduced endpoint silence timer from 700ms to 600ms for faster turn submission after real silence

### 5. WebSocket Auto-Reconnect

**File:** `client/transport-spike/index.html`

Added automatic reconnection with exponential backoff (500ms base, 8s max) when the WebSocket disconnects unexpectedly. Reconnect is enabled automatically when the user clicks Connect and disabled on intentional Disconnect. The UI shows reconnect state.

## What Worked

- **Streaming TTS architecture** is clean and fits naturally into the existing `send_pcm_samples` / `enqueue_speech` pattern.
- **Auto-submit** is simple and correct. The endpoint timer is already the right trigger point.
- **EMA smoothing on VAD** should reduce the false-positive transitions that were noted in the transport spike observations.
- **Reconnect with backoff** is straightforward and handles the observed socket disconnect weakness.

## What Did Not Work / Was Not Attempted

- **Piper model pre-warming** was not implemented. Piper spawns a new subprocess per synthesis call, so the ONNX model must be loaded every time. A persistent subprocess or in-process ONNX inference would help but is a larger change.
- **Alternative TTS engine evaluation** (e.g., Kokoro, Coqui) was not done. The streaming approach should be measured first since it may bring Piper into acceptable range.
- **No real-run latency measurements** were recorded since this is a code-only exploration. The streaming path needs to be validated with actual timing data.

## Risks

1. **Piper subprocess overhead**: Even with streaming, each TTS call spawns a new `python -m piper` subprocess. Model loading dominates the latency. If streaming doesn't bring first-chunk below ~0.8s, a persistent subprocess or in-process ONNX approach will be needed.
2. **VAD threshold tuning**: The new thresholds are based on reasoning about the baseline observations, not from new test runs. They may need further adjustment.
3. **Auto-submit race conditions**: If the user speaks again while a previous auto-submitted turn is still being processed, the system should handle the overlap. The current `turn_rejected` path covers this, but it may feel awkward to the user.
4. **Reconnect session state**: Reconnect creates a new WebSocket and a new server-side Session. Any in-progress turn or playback is lost. True session persistence would require server-side session storage keyed by a client identifier.

## Is This Path Better Than The Baseline?

**Likely yes, pending measurement.** The streaming TTS change is architecturally sound and addresses the known biggest bottleneck (waiting for full synthesis before sending any audio). Combined with earlier text chunking, this should measurably reduce time-to-first-audio.

The hands-free changes (auto-submit, VAD smoothing, reconnect) are all incremental improvements that don't conflict with the baseline architecture.

**Recommendation:** Merge the streaming TTS and auto-submit changes into the main line after validating latency improvements with real runs. The VAD thresholds should be validated separately since they may need hardware-specific tuning.
