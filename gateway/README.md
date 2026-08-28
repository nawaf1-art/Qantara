# Gateway

This directory contains Qantara's custom async voice gateway, session backends, and optional LAN integrations.

## Responsibilities

The gateway owns:

- browser HTTP/WebSocket transport
- bounded PCM input and playback output
- VAD, endpointing, STT/TTS coordination, and language routing
- per-session voice state and bounded continuity snapshots
- backend binding, turn submission, streaming, interruption, and cancellation escalation
- setup/status/control/Voice API surfaces
- optional mesh and Wyoming lifecycle

It does not own backend reasoning, tools, durable assistant memory, business data, or model-serving policy.

## Layout

- `transport_spike/` — primary aiohttp gateway runtime; the directory name is historical
- `fake_session_backend/` — deterministic session-contract backend
- `ollama_session_backend/` — native Ollama streaming bridge
- `openclaw_session_backend/` — advanced optional OpenClaw CLI bridge
- `mesh/` — experimental multi-device and Wyoming integration
- `SESSION_MODEL.md` — current session ownership and lifecycle reference

The canonical system topology and trust boundaries are in [`ARCHITECTURE.md`](../ARCHITECTURE.md). The downstream contract is in [`adapters/CONTRACT.md`](../adapters/CONTRACT.md).
