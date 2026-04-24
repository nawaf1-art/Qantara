# Qantara

**Local-first, real-time voice gateway for AI agents.**

Qantara lets you talk to AI agents by voice through your browser. It handles microphone capture, speech recognition, turn-taking, interruption, text-to-speech, and the live connection to the agent backend — all running on your local network with no cloud dependency for speech processing.

> Version `0.2.6-dev.1` — Pre-launch. Multi-device mesh + Wyoming + expressive voice + multilingual assistant + live translator all shipped; public launch at 0.2.6 once CI, benchmarks, and release prep land.


## Why Qantara

Most voice interfaces are push-to-talk wrappers. Qantara is built for **full-duplex conversation**:

- **Always listening** — continuous microphone input, even while the assistant is speaking
- **Barge-in** — interrupt the assistant mid-sentence, naturally
- **Local-first** — STT and TTS run on your machine, not in the cloud
- **Backend-agnostic** — works with Ollama, llama.cpp, vLLM, LM Studio, any OpenAI-compatible server, and an optional OpenClaw bridge

Qantara is a voice *channel*, not a replacement for the AI runtime behind it.

### Your voice stays on your machines

Qantara ships with **no telemetry, no analytics, and no outbound connections to Qantara-controlled servers**. Audio frames, transcripts, and conversation history never leave the machines you configure. The gateway connects only to the backends you select and to the HuggingFace / model-download endpoints the first time you use an STT or TTS model. There is no account, no key, no phone-home.

Defaults reflect this: no analytics SDKs in the browser client, no Google Fonts or other external CDNs, `/api/configure` and `/api/test-url` refuse non-private URLs, Docker-compose binds to `127.0.0.1` by default. See [SECURITY.md](SECURITY.md) and [docs/SUPPLY_CHAIN.md](docs/SUPPLY_CHAIN.md) for the full trust boundary.

### Where Qantara sits

Two other shapes of project exist in this space:

- **Speech-native models** (OpenAI Realtime, Gemini Live, MiniCPM-o, Moshi) — these *are* the model; audio in, audio out, no separate STT/TTS. They replace the brain, not the transport. Qantara can host them as a backend via their text or (in `0.3.x`) audio interfaces.
- **Heavy frameworks** (Pipecat, LiveKit Agents) — vendor-agnostic orchestration with dozens of provider integrations and WebRTC infrastructure. Powerful, but many days to wire up.

Qantara's niche is the middle: **a real full-duplex voice stack you can read, run, and ship in an afternoon**. One `docker compose up`, no cloud accounts, no build step.

### How Qantara compares

| | Qantara | Pipecat | LiveKit Agents | HA Voice | Ollama-voice scripts |
|---|:-:|:-:|:-:|:-:|:-:|
| Full-duplex + barge-in | ✅ | ✅ | ✅ | ❌ | ❌ |
| Browser client included | ✅ | Partial | Partial | ✅ | ❌ |
| Local-first default | ✅ | Optional | Cloud-first | ✅ | ✅ |
| No JS build tooling | ✅ | n/a | n/a | n/a | n/a |
| Swap LLM backend | ✅ | ✅ | ✅ | Limited | ❌ |
| Works without GPU | ✅ | ✅ | ✅ | ✅ | ✅ |
| Time to first conversation | Minutes | Hours–days | Hours–days | ~1 hour | Minutes |
| Repo size to read | ~3k LOC | ~50k | Large | Ecosystem | ~500 |

Comparisons reflect common configurations as of 2026-04; each of these projects is actively evolving.

## Performance Snapshot

Measured on 2026-04-24 with `scripts/bench_launch.py --arabic` on Linux 6.17 / Python 3.12. These are local gateway and TTS timings; LLM response time depends on the selected backend and model.

| Metric | Median | p95 | Notes |
|---|---:|---:|---|
| Gateway barge-in cancel path | 0.09 ms | 0.11 ms | Loopback adapter; budget is < 100 ms |
| Piper English TTS synthesis (`lessac`) | 1533 ms | 1541 ms | Short launch phrase, full synthesis |
| Piper Arabic TTS synthesis (`ar_JO-kareem-medium`) | 1801 ms | 1832 ms | Short Arabic launch phrase, full synthesis |

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for methodology and how to refresh these numbers.

## Quick Start

### Docker (one command)

```bash
docker compose up
```

Open **http://localhost:8765** — the setup page will guide you through backend selection.

If port 8765 is in use: `QANTARA_PORT=9765 docker compose up`

If you want Docker to expose Qantara to your LAN instead of loopback only:

```bash
QANTARA_DOCKER_BIND=0.0.0.0 docker compose up
```

> **First-run note.** The initial `docker compose up` downloads the Ollama image, a ~2 GB LLM (`qwen2.5:3b`), and builds the Qantara image (PyTorch CPU + faster-whisper + Kokoro ≈ 3 GB). Expect **5–10 minutes and ~5 GB of disk** on the first run. Subsequent runs start in seconds.
>
> **Docker supports Ollama and OpenAI-compatible backends out of the box.** OpenClaw is an advanced optional bridge that requires the `openclaw` CLI on your host, so it is not available inside the container. Use the Manual install path only if you already run OpenClaw agents.

### Manual

```bash
python3 -m venv .venv
./.venv/bin/pip install -r gateway/transport_spike/requirements.txt
make spike-run-venv
```

This installs the full local gateway runtime stack, including STT/TTS dependencies. Open **http://localhost:8765** — choose your backend and start talking.

For LAN microphone testing from another device, run Qantara with HTTPS/WSS and bind it explicitly:

```bash
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=8899 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
make spike-run-venv
```

Open `https://<your-lan-ip>:8899/spike`. Browsers require HTTPS or `localhost` for microphone access.

## Setup Experience

When you open Qantara, the setup page auto-detects available backends:

- **OpenAI-Compatible** (recommended) — connects directly to any `/v1/chat/completions` server. Covers Ollama, llama.cpp, vLLM, LiteLLM, Jan, LM Studio. Fastest path.
- **Ollama (bridge)** — uses a session bridge process. Works but slower than the direct OpenAI path.
- **OpenClaw** (advanced, optional) — shown only when the host CLI and gateway are healthy. Use it when you already want Qantara to speak through existing OpenClaw agents.
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
- **TTS:** Kokoro 82M, Piper, and Chatterbox provider paths
- **Arabic TTS:** Piper `ar_JO-kareem-medium` with a faster 1.3x baseline for natural pacing
- Audio-driven animated SVG avatar with mouth morphing, eye blink, breathing

### Voice Interaction
- Full-duplex (listen while speaking)
- Barge-in with immediate playback cancel
- VAD-based endpointing with auto-submit
- Multilingual assistant mode with language-aware voice routing
- Speaking-state hold to prevent flickering
- Playback debounce for smooth state transitions

### Multi-device + Home Assistant
- **Multi-device mesh** — run Qantara on multiple devices; the closest-mic node answers. See [docs/MESH.md](docs/MESH.md).
- **Home Assistant** — Qantara is a Wyoming satellite, auto-discovered by HA's Assist pipeline. See [docs/HOMEASSISTANT.md](docs/HOMEASSISTANT.md).

### Backend Adapters
- **OpenAI-compatible** — direct `/v1/chat/completions`, voice-optimized system prompt, conversation history, SSE streaming
- **Session HTTP** — Qantara's own session contract (used by Ollama and optional OpenClaw bridges)
- **Mock** — synthetic responses for testing

### Language Voices
`scripts/fetch_piper_voices.sh` downloads the launch Piper voices for English, Arabic, Spanish, and French. The voice registry reports installed voices through `/api/tts`; the language catalog reports launch-language TTS availability through `/api/languages`.

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
    │                         OpenAI-compat  Optional     Custom
    │                         (Ollama,       OpenClaw     Backend
    │                          llama.cpp,    bridge
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
| STT | faster-whisper / CTranslate2 |
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
| 0.1.9-pre | ✅ Done | Contributor onboarding |
| 0.2.1 | ✅ Done | [Tier 1] Interaction polish + interruption-safe barge-in |
| 0.2.2 | ✅ Done | [Tier 1] Multi-device mesh + Wyoming (Home Assistant) + mobile UX pass |
| 0.2.4 | ✅ Done | Multilingual assistant + directional + live conversation translator (EN/AR/ES/FR/JA) |
| 0.2.5 | ✅ Done | Chatterbox TTS (expressive voice) |
| 0.2.6 | Planned | **Public launch** |
| 0.2.7 | Planned | MCP voice client + server |
| 0.3.2 | Planned | Speech-native adapter (OpenAI Realtime, Gemini Live, MiniCPM-o) |
| 0.3.4 | Planned | Identity-aware sessions (voice fingerprinting) |
| 0.3.5 | Planned | Screenshot + voice multimodal |
| 0.3.x | Planned | Ambient announcements, hybrid routing, multi-participant rooms |

See [ROADMAP.md](ROADMAP.md) for full details.

## Contributing

Qantara is in pre-launch. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to file issues, propose features, and submit patches. Early contributions are welcome.

Agents and automated tooling — see [AGENTS.md](AGENTS.md) for coding conventions and patterns.

## Troubleshooting

Common issues (ports, mic permissions, backend detection, TLS, slow first response) are covered in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Documentation

Start with the [documentation map](docs/README.md). The main public guides are:

- [Installation and first run](docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Architecture](ARCHITECTURE.md)
- [Developer onboarding](docs/DEVELOPER_ONBOARDING.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [Publishing readiness audit](docs/PUBLISHING_READINESS_AUDIT.md)

## Security

Qantara is designed to run on your local network, not the public internet.

- The browser setup page's URL probe (`/api/test-url`) and backend configuration endpoint (`/api/configure`) restrict outbound URLs to private/loopback IPs — public URLs are rejected.
- If you set `QANTARA_AUTH_TOKEN`, `/ws`, `/api/configure`, and `/api/translation_mode` require `Authorization: Bearer <token>`. Leave it unset for zero-config loopback deployments.
- If you set `QANTARA_ADMIN_TOKEN`, `/api/admin/runtime` requires `Authorization: Bearer <token>`. If you leave it unset, that endpoint is disabled and returns `404`.
- Selecting the Ollama bridge, or the advanced optional OpenClaw bridge, spawns a local bridge subprocess on a dynamically allocated port. The gateway trusts the bridge binary; run Qantara only on machines you control.
- Native runs bind to `127.0.0.1:8765` by default. To expose a native run to your LAN, set `QANTARA_SPIKE_HOST=0.0.0.0` explicitly and consider running behind TLS (`QANTARA_TLS_CERT` / `QANTARA_TLS_KEY`).
- Docker publishes `127.0.0.1:8765` on the host by default even though the container listens on `0.0.0.0`. To publish on all host interfaces, set `QANTARA_DOCKER_BIND=0.0.0.0`.

If you find a security issue, please use GitHub private vulnerability reporting rather than opening a public issue — see [SECURITY.md](SECURITY.md).

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
