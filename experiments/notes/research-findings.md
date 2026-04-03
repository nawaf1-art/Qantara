# Research Findings

Date: 2026-04-02

## 1. Piper TTS: In-Process ONNX via piper-onnx

**Finding:** The `piper-onnx` package wraps Piper's ONNX models directly via onnxruntime. No subprocess overhead at all.

**API:** `Piper(model_path, config_path)` then `p.create(text)` returns `(np.ndarray, sample_rate)`.

**Measured latency (on this machine):**

| Text | piper-onnx (in-process) | Persistent subprocess | One-shot subprocess |
|------|------------------------|----------------------|---------------------|
| 32 chars | 66ms | 75.6ms | 1446ms |
| 76 chars | 141ms | 53.4ms | 1515ms |
| 90 chars | 153ms | 191.0ms | 1527ms |

Model load: ~1.2s (vs 6.4s subprocess warm-up).

**Implemented:** PiperTTS now prefers piper-onnx when available, falls back to persistent subprocess automatically.

**Source:** `pip install piper-onnx`. Also `piper1-gpl` (OHF-Voice fork) has similar API.

## 2. AudioWorklet Should Replace ScriptProcessor

**Finding:** ScriptProcessor is deprecated. AudioWorklet runs on a dedicated audio thread.

**Pattern:**
- AudioWorkletProcessor (separate .js file) receives 128-sample buffers
- Posts Int16Array back to main thread via `port.postMessage`
- Main thread sends over WebSocket

**Gotcha:** Buffer is always 128 samples (not configurable). Must accumulate frames for larger packets.

**Status:** Not implemented yet. Current ScriptProcessor works but should be migrated for production.

## 3. Silero VAD Dramatically Better Than RMS

**Finding:** Research shows Silero >> WebRTC >> RMS for VAD accuracy. RMS "underperforms random guessing for most of its range."

**Browser implementation:** `@ricky0123/vad-web` (1.9k stars) runs Silero VAD via ONNX Runtime Web entirely client-side.

**API:**
```javascript
const vad = await MicVAD.new({
  onSpeechStart: () => { /* barge-in */ },
  onSpeechEnd: (audio) => { /* submit to STT */ }
});
```

**Status:** Not implemented yet. Current EMA-smoothed RMS works but Silero would be a major accuracy upgrade.

## 4. Barge-In Pattern Confirmed

**Finding:** LiveKit, Pipecat all follow the same pattern:
1. VAD detects speech during playback
2. Cancel server-side generation
3. Clear client-side audio buffers
4. Restart STT

**Implemented:** Barge-in on VAD speech detection during active turn.

## 5. Streaming STT

**Finding:** faster-whisper doesn't natively support streaming. Projects like `whisper_streaming` and `RealtimeSTT` implement sliding-window approaches on top of it.

**Status:** Current endpoint-then-transcribe approach is acceptable for now. Real streaming STT is a separate milestone.

## Priority for Next Steps

1. **Done:** piper-onnx in-process inference
2. **High value, not yet done:** Silero VAD via @ricky0123/vad-web
3. **Medium value, not yet done:** AudioWorklet migration
4. **Lower priority:** Streaming STT
