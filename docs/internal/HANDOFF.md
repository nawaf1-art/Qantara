# Handoff — Qantara v0.1.9-pre

**Date:** 2026-04-07
**Author:** Claude Opus 4.6 + Nawaf
**Status:** Pre-launch. All core features built. One release from public.

## What Is Qantara

A local-first, real-time voice gateway for AI agents. Users talk to AI by voice through a browser. Qantara handles STT, TTS, turn-taking, barge-in, and backend routing. No audio leaves the local network.

## What's Built (v0.1.8 tagged + post-tag fixes)

### Core Voice Pipeline
- Browser mic → WebSocket PCM → faster-whisper STT → backend adapter → Kokoro TTS → browser playback
- Full-duplex: always listening, barge-in, auto-submit on silence
- 600-800ms typical first-audio latency with Kokoro warm

### Backend Adapters
- **OpenAI-compatible** (`adapters/openai_compatible.py`) — RECOMMENDED. Talks directly to `/v1/chat/completions`. Works with Ollama, llama.cpp, vLLM, LiteLLM, Jan, LM Studio. Voice-optimized system prompt. Conversation history with truncation. SSE streaming parser handles all server quirks.
- **Session HTTP** (`adapters/session_gateway_http.py`) — Qantara's own session contract. Used by Ollama and OpenClaw bridge processes.
- **Mock** — synthetic responses for testing.

### Provider Plugins
- STT: faster-whisper (deferred import, no crash if not installed)
- TTS: Kokoro (default, 11 voices, 24kHz, asyncio.to_thread for non-blocking), Piper (fallback)
- Plugin system: add a new provider by copying a template file

### Browser UI
- **Setup page** (`client/setup/index.html`) — auto-detects backends, shows agent/model selectors, Test button (server-side proxy for CORS), Getting Started panel when nothing detected, background polling
- **Voice mode** (`client/transport-spike/index.html`) — dark full-screen overlay with glowing orb, ephemeral captions, mic/end/settings/debug controls. Debug spike UI preserved behind toggle.
- **Avatar** — inline SVG with vanilla JS bezier mouth morph, eye blink, breathing animation

### Infrastructure
- Docker: `docker compose up` starts Ollama + model pull + backend + gateway
- CLI: `python cli.py --backend ollama` or `--backend http://...`
- Config: `qantara.yml` with backend/voice/server sections

## Known Issues and Gotchas

1. **Port 19120 conflict** — old OpenClaw bridge processes can linger on port 19120. Kill before starting Qantara. The managed bridge won't start if port is occupied.
2. **Thinking models** — qwen3, gemma-4 output chain-of-thought reasoning that gets spoken aloud. System prompt was simplified to reduce this but some models still do it. Users should pick non-thinking models for voice.
3. **TLS cert paths** — gateway needs absolute paths to TLS certs when started from a different working directory.
4. **server.py is 1,270+ lines** — exceeds the 300-line convention. Should be split into modules (api_handlers.py, bridge.py, audio.py). Not blocking.
5. **index.html is 2,250+ lines** — same. JS could be extracted to separate file. Not blocking.
6. **ScriptProcessorNode** — Chrome deprecation warning. Still works. Future: migrate to AudioWorkletNode.
7. **OpenClaw probe takes 10-15s** — because `openclaw health --json` probes all channels. Timeout set to 15s.
8. **OpenAI model selector** — styling needs improvement, select dropdown can be hard to interact with.
9. **llama.cpp on Windows** — must start with `--host 0.0.0.0` for LAN access. Default is localhost only.

## What's Next

### 0.1.9 — Contributor Onboarding (NEXT)
- Add GitHub topics: `voice-ai`, `voice-agent`, `local-first`, `tts`, `stt`, `ollama`
- Create `CONTRIBUTING.md`
- Add issue templates (bug, feature, provider)
- Create 10 "good first issue" tickets
- Add `make test` target
- Record 30-second demo video
- Demo GIF/video linked at top of README

### 0.2.0 — Public Launch
- Make repo public
- Show HN post
- r/LocalLLaMA + r/selfhosted posts
- X/Twitter thread with demo video

### Post-Launch
- 0.2.1: MCP voice server (control-plane tools, not audio transport)
- 0.2.2+: Vosk STT, Chatterbox TTS, agent protocol, pip SDK
- 0.3.x: Home Assistant, Arabic voice, speech-native models

## Code Review Process

- Claude Code does primary review
- Codex (`codex review --base main`) does second opinion on every PR
- Both reviews addressed before merge
- 9 PRs merged total (#1-#9)

## Key Files

| File | Purpose |
|------|---------|
| `AGENTS.md` | Coding conventions for AI agents |
| `ROADMAP.md` | Full task-level roadmap |
| `adapters/openai_compatible.py` | The recommended backend adapter |
| `gateway/transport_spike/server.py` | Main gateway (routes, API, WebSocket, bridge management) |
| `client/transport-spike/index.html` | Voice UI (dark mode + debug spike) |
| `client/setup/index.html` | Setup/onboarding page |
| `providers/tts/kokoro.py` | Kokoro TTS provider |
| `cli.py` | CLI launcher |
| `config.py` | Config file loader |

## How to Run (Dev)

```bash
# Gateway on LAN with Kokoro TTS, no pre-configured backend:
QANTARA_TTS_PROVIDER=kokoro \
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=9443 \
QANTARA_TLS_CERT=/home/nawaf/Projects/Qantara/ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=/home/nawaf/Projects/Qantara/ops/certs/qantara-key.pem \
./.venv/bin/python gateway/transport_spike/server.py
```

Open `https://192.168.68.59:9443/` — setup page auto-detects backends.

## Decisions Made

- **MCP:** Post-launch (0.2.1). Control-plane only. Audio stays on WebSocket.
- **Arabic:** Separate project. STT quality too low for Gulf dialect currently.
- **Avatars:** Vanilla JS SVG (GSAP removed for licensing, DiceBear for no animation, Rive for trigger-only inputs).
- **OpenAI adapter is the recommended path** — faster than Ollama bridge, better responses with system prompt.
- **License:** Apache 2.0.
- **Revenue model:** Deferred. Local analytics module planned post-launch.
