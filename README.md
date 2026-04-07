# Qantara

**Local-first, real-time voice gateway for AI agents.**

Qantara lets you talk to AI agents by voice through your browser. It handles microphone capture, speech recognition, turn-taking, interruption, text-to-speech, and the live connection to the agent backend — all running on your local network with no cloud dependency for speech processing.

> Version `0.1.9-pre` — Pre-launch. All core features built. Contributor onboarding and public launch next.

## Why Qantara

Most voice interfaces are push-to-talk wrappers. Qantara is built for **full-duplex conversation**:

- **Always listening** — continuous microphone input, even while the assistant is speaking
- **Barge-in** — interrupt the assistant mid-sentence, naturally
- **Local-first** — STT and TTS run on your machine, not in the cloud
- **Backend-agnostic** — works with Ollama, OpenClaw, llama.cpp, vLLM, LM Studio, or any OpenAI-compatible server

Qantara is a voice *channel*, not a replacement for the AI runtime behind it.

## Quick Start

### Docker (one command)

```bash
docker compose up
```

Open **http://localhost:8765** — the setup page will guide you through backend selection.

If port 8765 is in use: `QANTARA_PORT=9765 docker compose up`

### Manual

```bash
make spike-install
make spike-run
```

Open **http://localhost:8765** — choose your backend and start talking.

## Setup Experience

When you open Qantara, the setup page auto-detects available backends:

- **OpenAI-Compatible** (recommended) — connects directly to any `/v1/chat/completions` server. Covers Ollama, llama.cpp, vLLM, LiteLLM, Jan, LM Studio. Fastest path.
- **OpenClaw** — auto-discovers agents via CLI. Pick an agent, start talking.
- **Ollama (bridge)** — uses a session bridge process. Works but slower than the direct OpenAI path.
- **Custom URL** — point at any server implementing the Qantara session contract.
- **Demo** — no backend needed, test the voice interface.

## Voice Conversation UI

After selecting a backend, Qantara shows a full-screen dark voice mode:

- Central glowing orb that responds to audio amplitude
- Ephemeral captions showing the conversation
- Minimal controls: mic, end call, settings, debug toggle
- Stats bar with latency and backend info
- All debug tools accessible behind a toggle

## Features

### Speech Pipeline
- **STT:** faster-whisper (local, CPU)
- **TTS:** Kokoro 82M (local, 11 voices, ~600-800ms warm latency)
- **TTS fallback:** Piper
- Audio-driven animated SVG avatar with mouth morphing, eye blink, breathing

### Voice Interaction
- Full-duplex (listen while speaking)
- Barge-in with immediate playback cancel
- VAD-based endpointing with auto-submit
- Speaking-state hold to prevent flickering
- Playback debounce for smooth state transitions

### Backend Adapters
- **OpenAI-compatible** — direct `/v1/chat/completions`, voice-optimized system prompt, conversation history, SSE streaming
- **Session HTTP** — Qantara's own session contract (used by Ollama and OpenClaw bridges)
- **Mock** — synthetic responses for testing

### Provider Plugin System
- Abstract base classes for STT and TTS
- Add a new provider by implementing a single file
- Factory selects provider via `QANTARA_STT_PROVIDER` / `QANTARA_TTS_PROVIDER`

### Setup & Configuration
- Browser setup page with auto-detection
- CLI entry point: `python cli.py --backend ollama`
- Config file: `qantara.yml`
- Docker Compose with Ollama included

## Architecture

```
Browser (mic + speaker)
    │
    ├── WebSocket (PCM audio) ──▶  Qantara Gateway
    │                                  ├── Voice Activity Detection
    │                                  ├── STT (faster-whisper)
    │                                  ├── Session Management
    │                                  ├── TTS (Kokoro / Piper)
    │                                  └── Adapter Layer
    │                                          │
    │                              ┌────────────┼────────────┐
    │                              ▼            ▼            ▼
    │                         OpenAI-compat  OpenClaw     Custom
    │                         (Ollama,       (agents)     Backend
    │                          llama.cpp,
    │                          vLLM, etc.)
    │
    └── Dark Voice Mode ◀── streaming response + captions
```

## Project Structure

```
qantara/
├── adapters/                      # Backend adapter framework
│   ├── base.py                    # Abstract adapter interface
│   ├── factory.py                 # Adapter selection
│   ├── openai_compatible.py       # Direct OpenAI-compat adapter
│   ├── session_gateway_http.py    # Session contract adapter
│   └── mock_adapter.py            # Test adapter
├── client/
│   ├── setup/                     # Browser setup page
│   └── transport-spike/           # Voice conversation UI
├── gateway/
│   ├── transport_spike/           # Gateway server, STT, TTS
│   ├── ollama_session_backend/    # Ollama bridge
│   └── openclaw_session_backend/  # OpenClaw bridge
├── providers/                     # STT/TTS provider plugins
│   ├── stt/faster_whisper.py
│   ├── tts/kokoro.py
│   └── tts/piper.py
├── identity/                      # Avatar, voice, lipsync
├── cli.py                         # CLI launcher
├── config.py                      # Config file loader
├── Dockerfile                     # Docker image
├── docker-compose.yml             # Full stack
└── qantara.example.yml            # Example config
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Gateway | Python 3, aiohttp (async) |
| STT | faster-whisper (ONNX) |
| TTS | Kokoro 82M (ONNX), Piper (fallback) |
| Transport | WebSocket, PCM16 mono 16kHz/24kHz |
| Browser | Vanilla JS, WebAudio API, no frameworks |
| Docker | Python 3.12 slim + Ollama |

## Roadmap

| Version | Status | Description |
|---------|--------|-------------|
| 0.1.2 | ✅ Done | Provider plugin system |
| 0.1.3 | ✅ Done | Kokoro TTS (783ms warm) |
| 0.1.4 | ✅ Done | Backend setup experience |
| 0.1.5 | ✅ Done | Docker one-command setup |
| 0.1.6 | ✅ Done | OpenAI-compatible adapter |
| 0.1.7 | ✅ Done | Enhanced setup page |
| 0.1.8 | ✅ Done | Dark conversation view |
| 0.1.9 | Next | Contributor onboarding + demo video |
| 0.2.0 | Planned | **Public launch** |
| 0.2.1 | Planned | MCP voice server (control-plane) |
| 0.3.x | Planned | Home Assistant, Arabic voice, speech-native models |

See [ROADMAP.md](ROADMAP.md) for full details.

## Contributing

Qantara is in pre-launch. Contributions welcome after 0.2.0.

See [AGENTS.md](AGENTS.md) for coding conventions and patterns.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
