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

One optional hook has a no-op default:

```python
async aclose() -> None  # release long-lived HTTP clients, MCP connections, subprocesses
```

Owners should call `aclose()` when an adapter is replaced or the gateway shuts down.

### Start or resume a session

Returns an opaque runtime session handle. The adapter may map Qantara's client context to an existing backend session.

The handle is not private to the gateway: it is reported to the browser in the `adapter_session_ready` event (`runtime_session_handle`) and in session snapshots. Handles must therefore be opaque and carry no credentials or other secrets. Other backend-specific details (tokens, URLs, internal ids) must not be put into events.

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

Event fields, ordering, terminal behavior, and browser forwarding rules are specified in [`protocols/agent.md`](../protocols/agent.md). Use `make_activity_event()` for activity events so type, length, progress, confidence, and tool metadata limits are applied consistently. Activity events use the type `assistant_activity`; there is no separate tool-activity event.

Two rules adapters most often get wrong:

- `assistant_text_final.text` must equal the concatenated `assistant_text_delta` texts. Do not reformat the final text.
- Hidden reasoning never goes into text events or stored history. Report it at most once per turn as a `thinking` activity.

`turn_failed` requires `message`. `failure_kind` and `retriable` are optional and informational; the gateway does not retry failed turns on its own.

Adapters for HTTP session backends should follow [`protocols/session-gateway-http.md`](../protocols/session-gateway-http.md) instead of inventing a new transport.

### Cancel a turn

Requests cancellation or truncation of the active backend turn. Cancellation can be best-effort, but the result must describe what the adapter acknowledged. A turn cancelled before it starts must not start. Cancelling an unknown or already finished turn must be a harmless no-op that leaves no per-turn state behind. The gateway independently stops playback and applies a bounded escalation path, so a non-cooperative backend cannot pin the voice session indefinitely.

### Check health

Returns `AdapterHealth(status, detail=None, degraded=False)`. Health checks should be lightweight and must not create expensive agent turns unless an integration explicitly opts into a deep diagnostic mode.

## Context ownership

`client_context`, `turn_context`, and `cancel_context` are extensible dictionaries. Adapters must tolerate unknown keys. Current turn context can include language, translation, voice, interruption, and client metadata; it is transient voice-layer context, not durable assistant memory.

## Error and resource rules

- Raise clear exceptions for malformed backend output or unavailable services. Unwrap exception groups into one readable message.
- Raise `adapters.base.UnknownSessionError` when a session handle is unknown (expired, evicted, backend restarted). Callers reset the session only for this error; any other failure keeps the conversation.
- Put per-turn state cleanup in `finally` so it also runs on `CancelledError` (the gateway force-cancels slow turns).
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
| Session HTTP | `session_gateway`, `session_gateway_http`, `http` | Qantara session-contract backend ([protocol](../protocols/session-gateway-http.md)) |
| OpenAI-compatible | `openai`, `openai_compatible`, `openai-compatible` | Local `/v1/chat/completions` servers |
| MCP client | `mcp`, `mcp_client`, `mcp-client` | MCP chat tool over stdio or streamable HTTP |

New adapters must be registered in the factory, include contract tests, document configuration and limitations, and update the feature matrix when they become a public surface.
