# Architecture

Qantara is a local-first voice gateway between browser audio clients and operator-selected model or agent backends. It owns the real-time voice channel; it does not own agent reasoning, tools, long-term memory, or business logic.

## System topology

```text
Browser client
  microphone, WebAudio, captions, playback
        |
        | bounded WebSocket control + PCM16 mono 16 kHz frames
        v
Qantara aiohttp gateway
  auth, VAD, endpointing, session state, interruption, STT, TTS
        |
        | RuntimeAdapter contract
        v
Backend runtime
  OpenAI-compatible server, Ollama bridge, MCP tool,
  optional OpenClaw bridge, custom session service, or mock
```

The browser client has no model or agent state. The gateway coordinates a turn and adapts audio/text. The backend decides what the assistant does and returns user-facing events.

## Ownership

| Component | Owns | Must not own |
|---|---|---|
| Browser client | Permission prompts, microphone capture, playback queues, visual state | Model credentials, agent memory, STT/TTS models |
| Gateway session | Audio buffer, VAD/endpointing, turn state, interruption, bounded timeline/transcript snapshots | Backend reasoning or durable user history |
| STT provider | PCM-to-text conversion and language metadata | Session/adapter decisions |
| Runtime adapter | Backend session mapping, turn submission, output normalization, cancellation | Browser audio transport |
| Backend runtime | Inference, tools, backend history, agent policy | Microphone permission or browser playback |
| TTS provider | Text-to-PCM synthesis and voice resolution | Turn acceptance/cancellation policy |
| Mesh/Wyoming integration | Optional LAN coordination and satellite framing | Core adapter semantics |

## Runtime contracts

Every backend adapter implements the explicit interface in `adapters/base.py`:

- `start_or_resume_session`
- `submit_user_turn`
- `stream_assistant_output`
- `cancel_turn`
- `check_health`

Public adapter events are specified in [protocols/agent.md](protocols/agent.md). Providers similarly implement `providers/stt/base.py` or `providers/tts/base.py`. New integrations adapt to these contracts rather than reaching into browser or session internals.

The client-visible session states are `idle`, `listening`, `thinking`, `speaking`, and `interrupted`. Current lifecycle behavior is intentionally explicit because turn acceptance, disconnects, late backend output, and barge-in can race. A future consolidation must follow the [turn lifecycle hardening plan](docs/architecture/TURN_LIFECYCLE_HARDENING_PLAN.md).

## Trust boundaries

### Browser to gateway

Browser input is untrusted even on a LAN. The gateway authenticates protected routes when configured, validates Host and Origin authorities, bounds JSON/control/audio inputs, rejects malformed PCM frames, and applies browser security headers. The browser auth session uses an HttpOnly, SameSite cookie; API clients can use a bearer token.

### Gateway to backend/provider

Backends and speech providers are operator-selected local code or services. Qantara applies time, line, output, session, and queue bounds where practical. Local HTTP clients do not inherit proxy environment variables or follow redirects. Managed bridges inherit the host environment needed for local integrations, but Qantara removes its gateway, admin, and mesh credentials before starting them.

An adapter can still send a transcript to the service it is configured to call. Local-first describes the default topology, not a guarantee about an operator-supplied endpoint.

### LAN and reverse proxy

Loopback is the default. LAN use requires a strong auth token and HTTPS/WSS for browser microphone access. The Host policy accepts loopback/private IP literals and conventional LAN names; custom internal DNS names require `QANTARA_ALLOWED_HOSTS`. Exact cross-origin exceptions require `QANTARA_ALLOWED_ORIGINS`.

Qantara is not designed for direct public-internet exposure. A reverse proxy does not replace authentication, network policy, updates, or certificate validation.

### Download and release boundary

Speech/model providers may contact their upstream artifact hosts on first use. Docker and Python dependency behavior is documented in [Supply chain](docs/SUPPLY_CHAIN.md). Qantara release artifacts are built from an existing tag and accompanied by checksums, an SBOM, validation evidence, and provenance when the release workflow succeeds.

## Data lifecycle

- PCM input is buffered in memory and truncated to configured limits.
- Session timelines and transcript snapshots are bounded in memory; Qantara does not provide a durable transcript database.
- The browser stores non-secret preferences and continuity identifiers locally.
- Default event logs preserve operational identifiers/counts while redacting free-form speech/model/tool content and credentials.
- Bridge stdout/stderr is drained but not logged unless `QANTARA_BRIDGE_LOG_OUTPUT=1` is explicitly enabled.
- External runtimes and the operating system may have their own retention behavior; Qantara cannot delete data owned by those systems.

See [Privacy](docs/PRIVACY.md) for operator-facing detail.

## Transport and API surfaces

- `/ws`: full-duplex browser PCM/control transport
- `/api/v1/speak`: one-shot text-to-audio
- `/api/v1/transcribe`: one-shot bounded audio-to-text
- `/api/v1/converse`: bounded text turn streamed as SSE
- `/api/*`: setup, status, auth, voice control, languages, mesh, and discovery
- `/setup`, `/spike`, `/translate`, `/identity`: packaged static assets

WebSocket remains the MVP transport. A future WebRTC or SIP transport should implement the same audio/control semantics in a separate transport package rather than replacing the adapter boundary.

## Source layout and compatibility debt

Qantara currently exposes both the `qantara` SDK package and historical top-level packages (`adapters`, `gateway`, `providers`, `discovery`). The wheel also ships browser, identity, protocol, and schema resources. Moving everything under `qantara.*` is intentionally deferred to a staged migration with compatibility shims; see the [namespace migration ADR](docs/architecture/NAMESPACE_MIGRATION_ADR.md).

## Architectural constraints

- External voice gateway, not an in-process agent plugin
- Browser-first, full-duplex, headset-first interaction
- WebSocket PCM transport for the current release line
- Async aiohttp gateway
- Explicit adapters and providers
- Vanilla JavaScript browser client
- Local functionality without a required cloud service

Changes to these constraints need an issue and an accepted architecture decision before implementation.
