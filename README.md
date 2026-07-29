# Qantara

[![Tests](https://github.com/nawaf1-art/Qantara/actions/workflows/test.yml/badge.svg)](https://github.com/nawaf1-art/Qantara/actions/workflows/test.yml)
[![Latest release](https://img.shields.io/github/v/release/nawaf1-art/Qantara?sort=semver)](https://github.com/nawaf1-art/Qantara/releases)
[![License](https://img.shields.io/github/license/nawaf1-art/Qantara)](LICENSE)
[![Security policy](https://img.shields.io/badge/security-policy-green)](SECURITY.md)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![Local-first](https://img.shields.io/badge/local--first-privacy--focused-brightgreen)

**Turn local LLMs and AI agents into real-time browser voice assistants.**

Qantara lets you talk by voice to Ollama, local LLM servers, and local AI agents through your browser. It handles microphone capture, speech recognition, turn-taking, interruption, text-to-speech, and the live connection to whichever local backend you choose — all running on your local network with no cloud dependency for speech processing.

> Version `0.3.0` — consolidated platform release covering the Python SDK, Voice-as-API, Ollama compatibility, stream correctness, and dependency hardening. `0.2.6` was the first public release.

> Demo media needed: the README is ready for a 30-second GIF showing Docker startup, browser setup, an Ollama conversation, and barge-in. See [docs/DEMO_PLAN.md](docs/DEMO_PLAN.md).

## Try It In 5 Minutes

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
docker compose up
```

Open **http://localhost:8765**. Use **Demo** to test the browser voice UI without a backend, or choose **OpenAI-Compatible** for Ollama, llama.cpp, LM Studio, Jan, vLLM, LiteLLM, and similar local `/v1/chat/completions` servers.

First Docker startup downloads and builds local speech dependencies, so expect roughly 5-10 minutes and 8-10 GB of disk on a fresh machine. Subsequent starts are much faster. For the full install path, see [docs/QUICKSTART.md](docs/QUICKSTART.md).

## Why Qantara

Most voice interfaces are push-to-talk wrappers. Qantara is built for **full-duplex conversation**:

- **Always listening** — continuous microphone input, even while the assistant is speaking
- **Barge-in** — interrupt the assistant mid-sentence, naturally
- **Local-first** — STT and TTS run on your machine, not in the cloud
- **Backend-agnostic** — works with Ollama, llama.cpp, vLLM, LM Studio, Jan, LiteLLM, any OpenAI-compatible local server, and optional local agent bridges such as OpenClaw

Qantara is a voice *channel*, not a replacement for the local LLM or agent runtime behind it.

## Feature Status At A Glance

| Area | Status | Notes |
|---|---|---|
| Browser microphone voice UI | Stable | Vanilla JS/WebAudio client, no build step |
| WebSocket PCM voice pipeline | Stable | PCM16 mono 16 kHz audio path |
| Local STT/TTS | Stable | faster-whisper STT; Piper/Kokoro provider paths |
| Barge-in / interruption | Stable | Playback cancel path and active-turn handling |
| OpenAI-compatible local backends | Stable | Recommended path for Ollama, llama.cpp, LM Studio, Jan, LiteLLM, vLLM |
| MCP client and MCP voice server | Experimental | New in `0.2.8`; automated smoke coverage exists, real desktop client testing is still recommended |
| OpenClaw bridge | Advanced | Optional local-agent bridge, host setup required |
| Home Assistant / Wyoming | Experimental | LAN satellite path; validate in your own HA environment |
| Screenshot + voice multimodal | Planned | Not implemented yet |

See the complete [feature matrix](docs/FEATURES.md) for status labels and limitations.

## Use Cases

Qantara is for developers building:

- A local AI voice assistant for Ollama.
- A private voice interface for local LLMs and OpenAI-compatible servers.
- A browser voice gateway for AI agents and MCP-backed workflows.
- A voice layer for OpenClaw-style local agent systems.
- A home or lab AI assistant that stays on the LAN.
- A developer testbed for real-time voice-agent behavior, including barge-in.

See [docs/USE_CASES.md](docs/USE_CASES.md) for practical workflows.

## Who Should Not Use This Yet?

Qantara is early and pre-1.0. It is not the right fit yet for production call centers, medical or emergency use, fully managed cloud hosting, non-technical users expecting a polished commercial app, or environments that require audited enterprise compliance.

### Your voice stays on your machines

Qantara ships with **no telemetry, no analytics, and no outbound connections to Qantara-controlled servers**. Audio frames, transcripts, and conversation history never leave the machines you configure. The gateway connects only to the backends you select and to the HuggingFace / model-download endpoints the first time you use an STT or TTS model. There is no account, no key, no phone-home.

Defaults reflect this: no analytics SDKs in the browser client, no Google Fonts or other external CDNs, `/api/configure` and `/api/test-url` refuse non-private URLs, Docker-compose binds to `127.0.0.1` by default. See [SECURITY.md](SECURITY.md) and [docs/SUPPLY_CHAIN.md](docs/SUPPLY_CHAIN.md) for the full trust boundary.

### Where Qantara sits

Two other shapes of project exist in this space:

- **Speech-native models** (OpenAI Realtime, Gemini Live, MiniCPM-o, Moshi) — these *are* the model; audio in, audio out, no separate STT/TTS. They replace the brain, not the transport. Qantara can use text interfaces today; direct speech-native audio adapters are planned for a later `0.3.x` line.
- **Heavy frameworks** (Pipecat, LiveKit Agents) — vendor-agnostic orchestration with dozens of provider integrations and WebRTC infrastructure. Powerful, but many days to wire up.

Qantara's niche is the middle: **a real full-duplex voice stack for local LLMs and agents that you can read, run, and ship in an afternoon**. One `docker compose up`, no cloud accounts, no build step.

### How Qantara compares

| | Qantara | Pipecat | LiveKit Agents | HA Voice | Ollama-voice scripts |
|---|:-:|:-:|:-:|:-:|:-:|
| Full-duplex + barge-in | ✅ | ✅ | ✅ | ❌ | ❌ |
| Browser client included | ✅ | Partial | Partial | ✅ | ❌ |
| Local-first default | ✅ | Optional | Cloud-first | ✅ | ✅ |
| No JS build tooling | ✅ | n/a | n/a | n/a | n/a |
| Swap LLM backend | ✅ | ✅ | ✅ | Limited | ❌ |
| Works without GPU | ✅ | ✅ | ✅ | ✅ | ✅ |
| First conversation | ~10 min on first Docker run; seconds after setup | Hours–days | Hours–days | ~1 hour | Minutes |
| Core code to read | ~4.5k Python LOC + vanilla JS client | ~50k | Large | Ecosystem | ~500 |

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

If you want Docker to expose Qantara to your LAN instead of loopback only, set a strong local token too:

```bash
QANTARA_AUTH_TOKEN="$(openssl rand -hex 24)" \
QANTARA_DOCKER_BIND=0.0.0.0 \
docker compose up
```

Then open `http://<your-lan-ip>:8765` and enter that token on the setup page.

> **First-run note.** The initial `docker compose up` downloads the Ollama image, the ~2.7 GB `qwen3.5:2b` model, and builds the Qantara image with Python/ML speech dependencies. Expect **5–10 minutes and roughly 8–10 GB of disk** on the first run, plus extra temporary Docker build cache. Subsequent runs start in seconds.
>
> **Docker supports Ollama and OpenAI-compatible backends out of the box.** OpenClaw is an advanced optional bridge that requires the `openclaw` CLI on your host, so it is not available inside the container. Use the Manual install path only if you already run OpenClaw agents.

### Python SDK

> **Not on PyPI yet.** `pip install qantara` does not work today — the name is
> reserved but nothing has been uploaded. Install from the tag instead:

```bash
pip install "git+https://github.com/nawaf1-art/Qantara.git@v0.3.0"
```

```python
from qantara import VoiceGateway

gateway = VoiceGateway(host="127.0.0.1", port=8765)
gateway.run()
```

Open **http://127.0.0.1:8765** and start talking. The base install ships the gateway and browser client with the demo backend. Extras work the same way from the tag — append `#egg=qantara[speech]` for local speech, `[mesh]` for multi-device mesh / Home Assistant, or `[mcp]` for MCP support. Backend selection and everything else is configured through the same `QANTARA_*` environment variables — see [docs/CONFIGURATION.md](docs/CONFIGURATION.md) and the [Ollama compatibility guide](docs/OLLAMA_COMPATIBILITY.md).

### Manual

```bash
python3 -m venv .venv
./.venv/bin/pip install -r gateway/transport_spike/requirements.txt
make spike-run-venv
```

This installs the full local gateway runtime stack, including STT/TTS dependencies. Open **http://localhost:8765** — choose your backend and start talking.

For LAN microphone testing from another device, run Qantara with HTTPS/WSS and bind it explicitly:

```bash
QANTARA_AUTH_TOKEN="$(openssl rand -hex 24)" \
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=8899 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
make spike-run-venv
```

Open `https://<your-lan-ip>:8899/spike` and enter the token on the setup page if prompted. Browsers require HTTPS or `localhost` for microphone access.

## Setup Experience

When you open Qantara, the setup page auto-detects available backends:

- **OpenAI-Compatible** (recommended) — connects directly to any `/v1/chat/completions` server. Covers Ollama, llama.cpp, vLLM, LiteLLM, Jan, LM Studio. Fastest path.
- **Ollama (bridge)** — uses a session bridge process. Works but slower than the direct OpenAI path.
- **OpenClaw** (advanced, optional) — shown only when the host CLI and gateway are healthy. Use it when you already want Qantara to speak through existing OpenClaw agents.
- **Any MCP server** (advanced) — calls a configured MCP chat tool over stdio or streamable HTTP.
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
- Audio-driven animated SVG avatar with amplitude-driven mouth motion, eye blink, and breathing

### Voice Interaction
- Full-duplex (listen while speaking)
- Barge-in with immediate playback cancel
- VAD-based endpointing with auto-submit
- Multilingual assistant mode with language-aware voice routing
- Speaking-state hold to prevent flickering
- Playback debounce for smooth state transitions

### Multi-device + Home Assistant
- **Multi-device mesh** — run Qantara on multiple devices; the closest-mic node answers. See [docs/MESH.md](docs/MESH.md).
- **Home Assistant** — experimental Wyoming satellite path for HA Assist workflows. See [docs/HOMEASSISTANT.md](docs/HOMEASSISTANT.md).

### Backend Adapters
- **OpenAI-compatible** — direct `/v1/chat/completions`, voice-optimized system prompt, conversation history, SSE streaming
- **MCP client** — agent-style chat tool adapter over stdio or streamable HTTP
- **Session HTTP** — Qantara's own session contract (used by Ollama and optional OpenClaw bridges)
- **Mock** — synthetic responses for testing

### MCP Server
`mcp_server.py` exposes Qantara browser voice control as MCP tools. A local MCP client can call `voice_get_status`, `voice_speak`, `voice_interrupt`, and `voice_set_voice`; Qantara still handles TTS and browser playback over its WebSocket path.

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
├── identity/                      # Avatar, voice, and mouth-motion schemas
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
| TTS | Kokoro 82M via the `kokoro` Python package, Piper, Chatterbox |
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
| 0.2.6 | ✅ Released | **Public launch** |
| 0.2.7 | ✅ Released | Post-launch hardening patch |
| 0.2.8 | ✅ Released | MCP voice client + server |
| 0.2.9 | ✅ Released | Agent protocol v1 + tool-call metadata |
| 0.2.10 | ✅ Released | Python SDK — installable package (not yet on PyPI) |
| 0.2.11 | ↪ Superseded | Voice-as-API work ships in 0.2.12; no 0.2.11 tag was published |
| 0.2.12 | ✅ Released | Ollama 0.32 compatibility, audit fixes, and dependency hardening |
| 0.3.0 | ✅ Released | Canonical consolidated platform release; adds the mesh shutdown fix |
| 0.3.2 | Planned | Speech-native adapter (OpenAI Realtime, Gemini Live, MiniCPM-o) |
| 0.3.4 | Planned | Identity-aware sessions (voice fingerprinting) |
| 0.3.5 | Planned | Screenshot + voice multimodal |
| 0.3.x | Planned | Ambient announcements, hybrid routing, multi-participant rooms |

See [ROADMAP.md](ROADMAP.md) for full details.

## Contributing

Qantara is a pre-1.0 public project. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to file issues, propose features, and submit patches. Early contributions are welcome.

Agents and automated tooling — see [AGENTS.md](AGENTS.md) for coding conventions and patterns.

## Troubleshooting

Common issues (ports, mic permissions, backend detection, TLS, slow first response) are covered in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Documentation

Start with the [documentation map](docs/README.md). The main public guides are:

- [Installation and first run](docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Architecture](ARCHITECTURE.md)
- [MCP bridge](docs/MCP.md)
- [Developer onboarding](docs/DEVELOPER_ONBOARDING.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [Publishing readiness audit](docs/PUBLISHING_READINESS_AUDIT.md)

## Security

Qantara is designed to run on your local network, not the public internet.

- The browser setup page's URL probe (`/api/test-url`) and backend configuration endpoint (`/api/configure`) restrict outbound URLs to private/loopback IPs — public URLs are rejected.
- If you set `QANTARA_AUTH_TOKEN`, it must be at least 24 characters. Browsers unlock Qantara through `/api/auth/login` and an HttpOnly local cookie; API clients may use `Authorization: Bearer <token>`.
- Token auth protects `/ws`, `/api/configure`, `/api/translation_mode`, `/api/warmup`, `/api/test-url`, `/api/discovery/scan`, backend discovery endpoints, and mesh status endpoints.
- If you set `QANTARA_ADMIN_TOKEN`, `/api/admin/runtime` requires `Authorization: Bearer <token>`. If you leave it unset, that endpoint is disabled and returns `404`.
- Selecting the Ollama bridge, or the advanced optional OpenClaw bridge, spawns a local bridge subprocess on a dynamically allocated port. The gateway trusts the bridge binary; run Qantara only on machines you control.
- Native runs bind to `127.0.0.1:8765` by default. To expose a native run to your LAN, set `QANTARA_SPIKE_HOST=0.0.0.0` explicitly and consider running behind TLS (`QANTARA_TLS_CERT` / `QANTARA_TLS_KEY`).
- Docker publishes `127.0.0.1:8765` on the host by default even though the container listens on `0.0.0.0`. To publish on all host interfaces, set `QANTARA_DOCKER_BIND=0.0.0.0`.
- Mesh and Wyoming bind to loopback by default. To make them reachable across your LAN, explicitly set `QANTARA_MESH_HOST=0.0.0.0` or `QANTARA_WYOMING_HOST=0.0.0.0` and use only on a trusted LAN.

If you find a security issue, please use GitHub private vulnerability reporting rather than opening a public issue — see [SECURITY.md](SECURITY.md).

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
