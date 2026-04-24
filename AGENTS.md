# Qantara — Agent Guide

This file is for AI coding agents (Claude Code, Codex, Cursor, etc.) working on this repo. Read this before making any changes.

## What Qantara Is

Qantara is a local-first, real-time voice gateway that plugs into Ollama, local LLM runtimes, and local AI agent backends. It handles microphone capture, speech-to-text, turn-taking, barge-in, text-to-speech, and audio playback — all through the browser over a local network.

It is a voice *layer*, not an agent framework. Ollama, OpenClaw, LangChain, or another local runtime lives behind a clean adapter boundary.

## Project Structure

```
qantara/
├── adapters/                      # Backend adapter framework
│   ├── base.py                    # Abstract adapter interface — ALL adapters implement this
│   ├── factory.py                 # Adapter selection by QANTARA_ADAPTER env var
│   ├── mock_adapter.py            # Synthetic test adapter
│   ├── runtime_skeleton.py        # Exercises adapter path without real backend
│   ├── openai_compatible.py       # Direct OpenAI-compatible adapter
│   └── session_gateway_http.py    # HTTP session-contract adapter
│
├── client/transport-spike/        # Browser client
│   └── index.html                 # Full UI — vanilla JS, WebAudio, WebSocket, no build step
│
├── gateway/
│   ├── transport_spike/
│   │   ├── server.py              # Main gateway — aiohttp async server, session state machine
│   │   ├── stt_faster_whisper.py  # Backward-compatible import shim
│   │   └── tts_piper.py           # Backward-compatible import shim
│   ├── ollama_session_backend/    # Real Ollama-backed backend
│   └── openclaw_session_backend/  # OpenClaw bridge backend
│
├── providers/                     # STT/TTS provider plugin system
│   ├── factory.py                 # Provider selection by QANTARA_STT_PROVIDER / QANTARA_TTS_PROVIDER
│   ├── stt/
│   │   ├── base.py                # Abstract STT provider interface
│   │   └── faster_whisper.py      # Current STT provider
│   └── tts/
│       ├── base.py                # Abstract TTS provider interface
│       ├── chatterbox.py          # Expressive TTS provider
│       ├── kokoro.py              # Fast local TTS provider
│       └── piper.py               # Piper TTS provider
│
├── identity/                      # Avatar and voice systems
│   ├── avatar-descriptor.schema.json
│   ├── avatar-packs/              # Avatar preset definitions
│   ├── voice-registry/            # Voice configuration
│   └── voice-registry.schema.json
│
├── schemas/                       # Event timeline and data formats
├── ops/                           # LAN deployment (TLS certs, Caddy)
└── docs/                          # Public guides, audits, release checklist, handoff
```

## Key Patterns — Follow These

### Adding a New STT Provider

1. Copy `providers/stt/faster_whisper.py`
2. Subclass `providers/stt/base.py:STTProvider`
3. Implement the same interface: `transcribe(samples, sample_rate) -> STTResult`
4. Register it in `providers/factory.py` (pattern: `QANTARA_STT_PROVIDER`)
5. Add a test that validates transcription of a known audio sample

### Adding a New TTS Provider

1. Copy `providers/tts/piper.py`
2. Subclass `providers/tts/base.py:TTSProvider`
3. Implement the same interface: `synthesize(text, voice_id=None, speech_rate=None, expressiveness=None) -> PCM16 samples`
4. Support chunked/streaming output for low first-audio latency
5. Register it in `providers/factory.py` (pattern: `QANTARA_TTS_PROVIDER`)
6. Add a test that validates synthesis produces valid PCM audio

### Adding a New Backend Adapter

1. Copy `adapters/session_gateway_http.py`
2. Subclass `adapters/base.py`
3. Implement: `start_or_resume_session`, `submit_user_turn`, `stream_assistant_output`, `cancel_turn`, `check_health`
4. Register in `adapters/factory.py`
5. Add env var name in factory (pattern: `QANTARA_ADAPTER=your_adapter_name`)

### Adding a New Audio Transport

Currently WebSocket only. New transports (WebRTC, SIP) should:
1. Live in `transports/` (create if needed)
2. Implement the same audio I/O contract as the WebSocket handler in `server.py`
3. Be selectable via `QANTARA_TRANSPORT` env var

## Conventions

- **Language:** Python 3 (async/await with aiohttp)
- **Browser:** Vanilla JavaScript — no frameworks, no build tools
- **Config:** Environment variables prefixed with `QANTARA_`
- **Audio format:** PCM16 mono 16kHz everywhere
- **File size:** Keep files under 300 lines. Split if larger.
- **Types:** Use Python type hints on all function signatures
- **Tests:** Place in `tests/` mirroring the source structure
- **No magic:** No decorators that hide behavior, no dynamic imports, no metaprogramming. Explicit is better.

## Architecture Decisions (Locked)

These are decided. Do not change without discussion.

1. External voice gateway (not in-process plugin)
2. Browser-first client (vanilla JS, WebAudio)
3. Full-duplex conversation (always listening, barge-in)
4. Headset-first MVP (speaker mode is secondary)
5. WebSocket PCM transport for MVP
6. Custom async gateway (not Pipecat, not LiveKit)
7. Adapter boundary isolates gateway from backend runtime
8. Apache 2.0 license

## How to Run

```bash
# Basic (mock backend)
make spike-install && make spike-run
# Open http://127.0.0.1:8765/spike

# With Ollama backend
make real-backend-run-venv  # terminal 1
QANTARA_ADAPTER=session_gateway_http QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19120 make spike-run-venv  # terminal 2
```

## Current State

Version: `0.2.6` — first public release.

Working today:
- Browser mic capture → WebSocket → gateway → STT (faster-whisper) → adapter → backend → TTS → browser playback
- VAD, endpointing, auto-submit, barge-in, session management
- Direct OpenAI-compatible and Ollama bridge backends validated; OpenClaw bridge remains advanced/optional
- English and Arabic voice routing with local Piper/Kokoro/Chatterbox provider support
- Multilingual assistant and translation modes for the launch language set
- Multi-device mesh and Wyoming satellite support
- HTTPS/WSS for LAN access
- Avatar system with lipsync contract

See `ROADMAP.md` for what's next.

## What NOT to Do

- Do not add npm, webpack, or any JS build tooling to the browser client
- Do not add framework dependencies (Flask, FastAPI, Django) — we use aiohttp
- Do not hardcode model paths, API keys, or host addresses — use env vars
- Do not add features not in ROADMAP.md without opening an issue first
- Do not change the adapter interface without updating all existing adapters
- Do not add cloud-only dependencies — every feature must work locally
