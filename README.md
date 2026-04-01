# Qantara

Qantara is a LAN-first, real-time voice interface for OpenClaw-compatible agent runtimes.

The primary user experience is not push-to-talk. Qantara is designed for full-duplex conversation:

- continuous listening while the assistant is speaking
- barge-in interruption at any time
- local-first speech processing with no required external network path

## Goals

- Provide a low-latency voice channel around an OpenClaw-compatible agent and session model
- Preserve the downstream agent runtime as the source of truth for tools and conversation state
- Run safely on a private LAN with strong permission boundaries for voice-triggered actions

## Initial Product Direction

Qantara should start as an external LAN voice gateway beside the downstream agent runtime, not as a tightly coupled in-process plugin.

This keeps the first version easier to iterate on while the protocol, cancellation rules, and interruption handling are still being proven. A native OpenClaw plugin remains a later optimization if runtime hooks prove sufficient and the external protocol stabilizes.

The repository intentionally does not assume any specific local OpenClaw agent, model, gateway host, or deployment topology yet. Those integration details are deferred until a later validation phase.

The initial client target should be browser-first. A browser client keeps installation friction low on a private LAN, makes internal testing easier, and is sufficient to prove the audio transport, session model, and interruption behavior before investing in a dedicated desktop shell.

## V1 Scope

- Single user, single active session
- Browser-first LAN client using WebAudio and WebSocket
- Always-on microphone streaming
- Voice activity detection and endpointing
- Local streaming STT with partial and final transcripts
- Downstream runtime turn submission through a narrow integration boundary
- Text-first or near-streaming response playback path
- Local TTS with immediate playback cancel on user interruption
- Event timeline and latency instrumentation from day one

## Non-Goals For V1

- Telephony-first workflows
- Multi-user conferencing
- General internet-facing deployment
- Complex speaker-mode echo cancellation beyond a constrained headset-first setup

## Core Design Principle

Qantara should behave as a voice channel adapter around a downstream conversation API, not as a replacement for the runtime model behind it.

## Documents

- [`PLAN.md`](/home/nawaf/Projects/Qantara/PLAN.md): implementation phases, milestones, and key decisions
- [`ARCHITECTURE.md`](/home/nawaf/Projects/Qantara/ARCHITECTURE.md): runtime model, state machine, transport, and risk areas
- [`DECISIONS.md`](/home/nawaf/Projects/Qantara/DECISIONS.md): architectural decisions and deferred choices
- [`BACKEND_ADAPTER_TARGETS.md`](/home/nawaf/Projects/Qantara/BACKEND_ADAPTER_TARGETS.md): candidate backend shapes and the recommended first adapter target
- [`SESSION_GATEWAY_CONTRACT.md`](/home/nawaf/Projects/Qantara/SESSION_GATEWAY_CONTRACT.md): first concrete session-oriented backend contract shape
- [`MILESTONES.md`](/home/nawaf/Projects/Qantara/MILESTONES.md): delivery checklist and exit criteria tracking
- [`PROJECT_STATE.md`](/home/nawaf/Projects/Qantara/PROJECT_STATE.md): current checkpoint, implemented scope, and next steps
- [`M0_EXPERIMENTS.md`](/home/nawaf/Projects/Qantara/M0_EXPERIMENTS.md): explicit M0 validation program
- [`experiments/RUN_TRANSPORT_SPIKE.md`](/home/nawaf/Projects/Qantara/experiments/RUN_TRANSPORT_SPIKE.md): how to run the current spike and record results
- [`ops/README.md`](/home/nawaf/Projects/Qantara/ops/README.md): LAN HTTPS serving guidance for browser microphone access

## Current Status

Qantara is currently in `M0: Technical Validation`.

The repository now includes a runnable browser-to-gateway transport spike with:

- browser microphone capture and PCM streaming over WebSocket
- gateway-side transport event logging
- browser playback of gateway PCM audio
- validated faster-whisper transcription of recent captured audio
- configurable adapter selection with `mock` and `runtime_skeleton` modes
- locally validated Piper runtime path with synthetic fallback still available

This is a real validation slice, not just design documentation. The current M0 spike has now validated the first STT candidate path through faster-whisper and the first TTS candidate path through Piper. Later runtime binding and interruption hardening still remain open.

Current measured baseline:

- Piper first-audio is roughly `1.7s`
- local browser playback clear is effectively immediate
- backend playback-stop telemetry is still separate from user-perceived audible stop timing

Current adapter selection:

- `QANTARA_ADAPTER=mock`
- `QANTARA_ADAPTER=runtime_skeleton`
- `QANTARA_ADAPTER=session_gateway_http`

Local validation backend:

- [gateway/fake_session_backend/server.py](/home/nawaf/Projects/Qantara/gateway/fake_session_backend/server.py)

## Quick Start

Install the current spike dependency:

```bash
make spike-install
```

Run the current gateway-hosted spike:

```bash
make spike-run
```

Then open:

```text
http://127.0.0.1:8765/spike
```

If `8765` is already in use, choose another port:

```bash
QANTARA_SPIKE_PORT=8899 make spike-run-venv
```

Then open:

```text
http://127.0.0.1:8899/spike
```

To expose the spike on your LAN from this machine:

```bash
make spike-run-lan-venv
```

Then open from another device on the same network:

```text
http://<your-lan-ip>:8899/spike
```

Important:

- plain `http://<your-lan-ip>` is enough for transport testing
- it is usually not enough for microphone access from another device
- for LAN mic access, serve the spike over `HTTPS` and let the client use `WSS`
- see [`ops/README.md`](/home/nawaf/Projects/Qantara/ops/README.md)
- if Caddy is not installed, the repo also documents a direct self-signed TLS fallback
