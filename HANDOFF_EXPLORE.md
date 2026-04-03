# Exploration Branch Handoff

Branch: `explore/hands-free-speed`
Base: `v0.1.0-alpha.1`
Commits: 8

## Changes

### TTS Latency (66-153ms, was 1500ms)
- In-process ONNX inference via `piper-onnx` (preferred)
- Persistent subprocess fallback if piper-onnx unavailable
- Progressive text chunking (28 chars first, 60 chars later)

### Server Hardening
- `struct.pack`/`unpack` for PCM (replaces per-sample loops)
- Safe websocket sends (catch ConnectionResetError)
- Barge-in: cancel turn + clear playback on speech detection
- Session event logs (NDJSON per session, `QANTARA_SESSION_LOG_DIR`)
- Gateway `/health` endpoint
- Adapter retry with error classification (retryable/non_retryable)
- Graceful session cleanup (cancel speech tasks, close logs)

### Browser Client
- AudioWorklet mic capture (ScriptProcessor fallback)
- Auto-submit toggle on endpoint-ready
- `?auto=1` URL parameter (auto-connect, mic, auto-submit)
- Turn state indicator, barge-in playback clearing
- EMA-smoothed VAD, tuned thresholds
- Auto-reconnect with exponential backoff

### Tests
39 passing (33 unit + 6 integration)

### Makefile
- `make test`, `make spike-run-logged`, `make measure-tts`

## Research (not yet implemented)
- Silero VAD via `@ricky0123/vad-web` (high priority)
- Streaming STT (lower priority)

See `experiments/notes/research-findings.md`

## Recommendation
Merge this branch.
