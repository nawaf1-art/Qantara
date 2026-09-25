# Adapter Contract

Qantara's downstream runtime boundary is the `RuntimeAdapter` interface in [`adapters/base.py`](base.py). This document explains the implemented contract; the browser-visible event vocabulary is defined by [`protocols/agent.md`](../protocols/agent.md).

Adapters isolate the voice gateway from a model server, agent runtime, MCP tool, or custom session service. They do not own microphone transport, STT/TTS, browser playback, or durable user history.

## Required interface

Every adapter implements five operations:

```python
async start_or_resume_session(client_context=None) -> str
async submit_user_turn(session_handle, transcript, turn_context=None) -> str
stream_assistant_output(session_handle, turn_handle) -> AsyncIterator[dict]
async cancel_turn(session_handle, turn_handle, cancel_context=None) -> dict
async check_health() -> AdapterHealth
```

### Start or resume a session

Returns an opaque runtime session handle. The adapter may map Qantara's client context to an existing backend session, but backend-specific identifiers must not leak into the browser protocol.

### Submit a finalized user turn

Accepts the final transcript and transient turn context, then returns an opaque turn handle. The gateway remains responsible for endpointing and deciding when a transcript is final.

### Stream assistant output

Yields agent-protocol events. Current adapters use events such as:

- `assistant_text_delta`
- `assistant_text_final`
- `assistant_activity`
- `turn_completed`
- `turn_failed`
- `cancel_acknowledged`

Event fields, ordering, terminal behavior, and browser forwarding rules are specified in [`protocols/agent.md`](../protocols/agent.md). Use `make_activity_event()` for activity events so type, length, progress, confidence, and tool metadata limits are applied consistently.

### Cancel a turn

Requests cancellation or truncation of the active backend turn. Cancellation can be best-effort, but the result must describe what the adapter acknowledged. The gateway independently stops playback and applies a bounded escalation path, so a non-cooperative backend cannot pin the voice session indefinitely.

### Check health

Returns `AdapterHealth(status, detail=None, degraded=False)`. Health checks should be lightweight and must not create expensive agent turns unless an integration explicitly opts into a deep diagnostic mode.

## Context ownership

`client_context`, `turn_context`, and `cancel_context` are extensible dictionaries. Adapters must tolerate unknown keys. Current turn context can include language, translation, voice, interruption, and client metadata; it is transient voice-layer context, not durable assistant memory.

## Error and resource rules

- Raise clear exceptions for malformed backend output or unavailable services.
- Bound sessions, history, input, output, queues, and stream lines where the adapter owns them.
- Do not follow redirects or inherit proxy variables for local HTTP backends unless a reviewed integration explicitly requires different behavior.
- Close HTTP clients, subprocesses, streams, and pending tasks on cancellation and shutdown.
- Do not log transcripts, assistant text, tool parameters, credentials, or backend-controlled output by default.
- Preserve split UTF-8 and fragmented/coalesced SSE or NDJSON records when decoding streams.

## Implementations

The factory in [`adapters/factory.py`](factory.py) currently selects:

| Adapter | Factory values | Intended use |
|---|---|---|
| Mock | `mock` | Deterministic development and tests |
| Runtime skeleton | `runtime`, `runtime_skeleton`, `real` | Adapter-path development without a concrete backend |
| Session HTTP | `session_gateway`, `session_gateway_http`, `http` | Qantara session-contract backend |
| OpenAI-compatible | `openai`, `openai_compatible`, `openai-compatible` | Local `/v1/chat/completions` servers |
| MCP client | `mcp`, `mcp_client`, `mcp-client` | MCP chat tool over stdio or streamable HTTP |

New adapters must be registered in the factory, include contract tests, document configuration and limitations, and update the feature matrix when they become a public surface.
