# Exploration Branch Handoff

Branch: explore/hands-free-speed
Base: v0.1.0-alpha.1
Date: 2026-04-02 (updated 2026-04-03)

## Changes

### 1. In-Process Piper ONNX
Replaced subprocess TTS with piper-onnx direct ONNX inference. 66-153ms vs 1500ms baseline.

### 2. Server Hardening
struct.pack PCM, safe websocket sends, barge-in on speech.

### 3. Hands-Free Client
Auto-submit, auto-start via ?auto=1, turn state, barge-in handling, VAD tuning, reconnect.

### 4. Tests
33 tests passing.

## Research (not yet implemented)
- Silero VAD via @ricky0123/vad-web
- AudioWorklet migration
- Streaming STT

See experiments/notes/research-findings.md

## Recommendation
Merge this branch.
