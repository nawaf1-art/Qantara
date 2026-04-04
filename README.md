# Qantara

**Local-first, real-time voice gateway for AI agents.**

Qantara lets you talk to AI agents by voice through your browser. It handles microphone capture, speech recognition, turn-taking, interruption, text-to-speech, and the live connection to the agent backend — all running on your local network with no cloud dependency for speech processing.

> Version `0.1.0-alpha.2` — Early alpha. Core transport and speech pipeline validated. Active development.

## Why Qantara

Most voice interfaces are push-to-talk wrappers. Qantara is built for **full-duplex conversation**:

- **Always listening** — continuous microphone input, even while the assistant is speaking
- **Barge-in** — interrupt the assistant mid-sentence, naturally
- **Local-first** — STT and TTS run on your machine, not in the cloud
- **Backend-agnostic** — works with OpenClaw, Ollama, or any session-compatible backend

Qantara is a voice *channel*, not a replacement for the AI runtime behind it.

## What It Does Today

```
Browser (mic + speaker)
    │
    ├── WebSocket (PCM audio) ──▶  Qantara Gateway
    │                                  ├── Voice Activity Detection
    │                                  ├── STT (faster-whisper)
    │                                  ├── Session Management
    │                                  ├── TTS (Piper)
    │                                  └── Adapter Layer
    │                                          │
    │                              ┌────────────┼────────────┐
    │                              ▼            ▼            ▼
    │                           Ollama      OpenClaw      Custom
    │                                                    Backend
    │
    └── Playback + Captions + Avatar ◀── streaming response
```

### Validated Features

- **Speech pipeline** — faster-whisper STT + Piper TTS, ~1.5s to first spoken response
- **Hands-free operation** — VAD-based endpointing, auto-submit when you stop speaking
- **Interruption** — immediate playback cancel on barge-in
- **Session management** — create, resume, and cancel turns through a clean adapter contract
- **Multiple backends** — tested with Ollama (local models) and OpenClaw agents
- **Browser UI** — real-time captions, session state indicators, audio mode selector
- **Identity layer** — avatar system with lipsync contract, voice registry, preset selectors
- **LAN-ready** — HTTPS/WSS support for secure access from any device on your network
- **Observability** — event timeline with timestamps across every boundary

## Quick Start

**Requirements:** Docker, Docker Compose, a modern browser (Chrome recommended)

```bash
docker compose up
```

Then open **http://127.0.0.1:8765/spike** in your browser and start speaking.

Notes:

- the first run builds the Qantara image, starts Ollama, and pulls the default model `qwen2.5:3b`
- first startup can take several minutes on a fresh machine
- the default Docker stack uses:
  - `faster-whisper` for STT
  - `kokoro` for TTS
  - Ollama as the agent backend
- no extra environment variables are required for the default stack

If port `8765` is already in use on your machine:

```bash
QANTARA_PORT=9765 docker compose up
```

Then open **http://127.0.0.1:9765/spike**.

Helpful commands:

```bash
make docker-build
make docker-up
make docker-down
```

## Manual Local Start

**Requirements:** Linux, Python 3, `make`

```bash
make spike-install
make spike-run
```

Open **http://127.0.0.1:8765/spike** in your browser.

### Manual Local Backend Options

**Ollama:**
```bash
# Terminal 1 — backend
make real-backend-run-venv

# Terminal 2 — gateway
QANTARA_ADAPTER=session_gateway_http \
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19120 \
make spike-run-venv
```

**OpenClaw:**
```bash
# Terminal 1 — bridge
QANTARA_REAL_BACKEND_PORT=19120 \
QANTARA_OPENCLAW_AGENT_ID=spectra \
./.venv/bin/python gateway/openclaw_session_backend/server.py

# Terminal 2 — gateway
QANTARA_ADAPTER=session_gateway_http \
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19120 \
make spike-run-venv
```

### LAN Access (HTTPS)

For microphone access from other devices on your network:

```bash
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=9443 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
make spike-run-venv
```

See [ops/README.md](ops/README.md) for TLS setup details.

### Optional: Kokoro TTS

Kokoro is now available as an optional local TTS provider.

```bash
./.venv/bin/pip install "kokoro>=0.9.4" soundfile
QANTARA_TTS_PROVIDER=kokoro make spike-run-venv
```

For best English fallback pronunciation, install `espeak-ng` on the host.

Observed local timings on this development machine:

- Piper synthesize time for a short sentence: about `1.52s`
- Kokoro first synthesize time after assets are cached: about `3.32s`
- Kokoro warm synthesize time in the same process: about `0.63s`

Important:

- the very first Kokoro run downloads model and language assets locally, so cold-start can be much slower
- Kokoro outputs `24 kHz` audio, which Qantara now respects through the provider path

## Architecture

Qantara is designed as an **external voice gateway** that sits beside your AI runtime, not inside it.

| Component | Role |
|-----------|------|
| **Browser Client** | Mic capture, playback, captions, avatar rendering |
| **Gateway** | Async Python server — VAD, STT, TTS, session state machine, adapter routing |
| **Adapters** | Pluggable backend interface — mock, Ollama, OpenClaw, or custom HTTP |
| **Identity** | Avatar descriptors, voice registry, lipsync contract |

The adapter contract is intentionally narrow: `start_session`, `submit_turn`, `stream_output`, `cancel_turn`. Any backend that implements this contract works with Qantara.

## Roadmap

| Version | Milestone | Status |
|---------|-----------|--------|
| `0.1.0-alpha.2` | **R0: Alpha Checkpoint** — transport validated, STT/TTS working, adapter pipeline proven | Done |
| | **R1: Hands-Free Baseline** — stable VAD, natural turn-taking without manual submit | Next |
| | **R2: Lower-Latency Response** — sub-1.5s first spoken chunk, TTS evaluation | Planned |
| | **R3: Real Backend Integration** — production-stable OpenClaw/Ollama path | In Progress |
| | **R4: Hard Barge-In** — backend cancel, interruption-aware history, overlapping turn handling | Planned |
| | **R5: Security & Ops** — auth tokens, audit logs, safe deployment defaults, confirmation gates | Planned |

## Project Structure

```
qantara/
├── client/transport-spike/    # Browser client (vanilla JS, no build step)
├── gateway/
│   ├── transport_spike/       # Gateway server, STT, TTS
│   ├── fake_session_backend/  # Test backend
│   ├── ollama_session_backend/# Ollama integration
│   └── openclaw_session_backend/ # OpenClaw bridge
├── providers/                 # STT/TTS provider plugin system
├── adapters/                  # Backend adapter framework
├── docs/internal/             # Internal checkpoints, experiments, handoff notes
├── identity/                  # Avatar, voice, and lipsync systems
├── schemas/                   # Event timeline and data formats
├── ops/                       # LAN deployment (TLS, Caddy)
└── experiments/               # Validation notes and spike runners
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Gateway | Python 3, aiohttp (async) |
| STT | faster-whisper |
| TTS | Kokoro, Piper |
| Transport | WebSocket, PCM16 mono 16kHz |
| Browser | Vanilla JS, WebAudio API |
| TLS | Caddy or self-signed certs |

## Contributing

Qantara is in early alpha. Contributions, feedback, and testing are welcome.

If you're interested in:
- **Testing** — try the spike on your hardware, report what works and what doesn't
- **Backend adapters** — add support for your preferred AI runtime
- **Voice/TTS** — experiment with alternative TTS engines or voice models
- **Frontend** — improve the browser client, avatar rendering, or UX

Open an issue to discuss before starting large changes.

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Runtime model, state machine, transport design |
| [PLAN.md](PLAN.md) | Implementation phases and milestones |
| [ROADMAP.md](ROADMAP.md) | Versioned milestone targets |
| [DECISIONS.md](DECISIONS.md) | Locked architectural decisions |
| [SESSION_GATEWAY_CONTRACT.md](SESSION_GATEWAY_CONTRACT.md) | Backend adapter HTTP contract |
| [identity/](identity/) | Avatar system, voice registry, lipsync contract |
| [docs/internal/](docs/internal/) | Internal checkpoints, experiments, and handoff notes |

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
