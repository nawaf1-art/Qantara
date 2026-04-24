# Architecture

Qantara is a local-first voice gateway. It sits between browser microphone/speaker clients and one or more AI backends. The gateway owns speech capture, speech recognition, turn-taking, interruption, text-to-speech, playback, and LAN transport. The selected backend owns model inference, tools, and agent behavior.

Qantara is not an agent framework. OpenAI-compatible local servers, Ollama bridge processes, custom session backends, and the advanced optional OpenClaw bridge all sit behind the same adapter boundary.

## High-Level Topology

```text
Browser client
  microphone + speaker
        |
        | WebSocket PCM/control events
        v
Qantara gateway
  VAD / endpointing / STT / session state / TTS / playback control
        |
        | RuntimeAdapter
        v
AI backend
  OpenAI-compatible server, Ollama bridge, custom session service,
  optional OpenClaw bridge, or mock adapter
```

## Runtime Boundaries

### Browser Client

The browser client is deliberately thin:

- requests microphone permission
- captures PCM audio frames
- sends frames and control events over WebSocket
- plays PCM audio returned by the gateway
- renders captions, session state, and debug information

It does not own model state, agent logic, STT, or TTS.

### Gateway

The gateway owns the real-time voice loop:

- live audio ingress and buffering
- voice activity detection and endpointing
- final and partial transcription paths
- per-session state machine
- barge-in and playback cancellation
- language/translation turn context
- TTS provider selection and voice routing
- adapter calls to the selected backend

The gateway is implemented as an async `aiohttp` service.

### Backend Adapter

Every backend implements the contract in `adapters/base.py`:

- `start_or_resume_session`
- `submit_user_turn`
- `stream_assistant_output`
- `cancel_turn`
- `check_health`

The adapter boundary is what keeps Qantara independent from a specific model runtime or agent framework.

## Session State

The active runtime state is represented by `gateway.transport_spike.runtime.Session`. The public client-facing states are:

- `idle`
- `listening`
- `thinking`
- `speaking`
- `interrupted`

State transitions are emitted as session events and mirrored to the browser. The state model is intentionally explicit because interruption and recovery are the hardest parts of a voice UX.

## Barge-In Semantics

When user speech is detected while assistant output is active, Qantara:

1. clears browser playback immediately
2. asks the adapter to cancel the active turn when possible
3. emits `turn_interrupted`
4. returns the session to a clean state for the next turn

Some backends can hard-cancel generation. Others can only ignore late output. The gateway handles both cases through the adapter contract.

## Speech Providers

Speech providers live under `providers/`:

- STT providers implement `providers/stt/base.py`
- TTS providers implement `providers/tts/base.py`
- provider selection is controlled with `QANTARA_STT_PROVIDER` and `QANTARA_TTS_PROVIDER`

The provider layer must adapt to the gateway contract. A provider should not force unrelated gateway behavior changes.

## Transports

The MVP transport is browser WebSocket with PCM audio frames. The gateway currently serves:

- `/setup` for first-run backend configuration
- `/spike` for the voice client
- `/translate` for the live translator page
- `/ws` for browser audio/control transport
- `/api/*` for status, configuration, mesh, languages, and TTS metadata

Future transports such as WebRTC or SIP should live behind the same audio/control contract instead of replacing the adapter layer.

## Local-First Security Boundary

Qantara is intended for loopback or trusted LAN deployments:

- default native bind is loopback
- Docker publishes on loopback by default
- public URLs are rejected by backend configuration probes
- auth tokens are optional for loopback and recommended for LAN
- TLS is required by browsers for microphone access from other LAN devices

See `SECURITY.md` and `docs/SUPPLY_CHAIN.md` for the public trust boundary.

## Extension Points

The safest extension points are:

- add an STT provider in `providers/stt/`
- add a TTS provider in `providers/tts/`
- add a backend adapter in `adapters/`
- add a transport under a future `transports/` package

Avoid changes that couple the gateway to one backend runtime. That would undermine Qantara's purpose as a standalone voice layer.
