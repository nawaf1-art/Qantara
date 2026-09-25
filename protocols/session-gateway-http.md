# Qantara Session Gateway HTTP Protocol

Status: documents the protocol implemented by
[`adapters/session_gateway_http.py`](../adapters/session_gateway_http.py)
(the client) and by the bundled backends in
[`gateway/fake_session_backend/`](../gateway/fake_session_backend/),
[`gateway/ollama_session_backend/`](../gateway/ollama_session_backend/) and
[`gateway/openclaw_session_backend/`](../gateway/openclaw_session_backend/).
Use it to connect Qantara to your own agent runtime without writing a
Python adapter.

The events a backend streams are the adapter stream events of
[Agent Protocol v1](agent.md). This document covers only the HTTP transport
around them. Audio never crosses this interface: Qantara sends finished
transcripts and receives text.

## Configuration (gateway side)

| Variable | Default | Meaning |
|---|---|---|
| `QANTARA_ADAPTER` | — | `session_gateway_http` selects this protocol |
| `QANTARA_BACKEND_BASE_URL` | — | Backend base URL, e.g. `http://127.0.0.1:19120` |
| `QANTARA_BACKEND_TOKEN` | unset | Sent as `Authorization: Bearer <token>` on every request |
| `QANTARA_BACKEND_TIMEOUT` | `30` | Total seconds for each JSON request (sessions, turns, cancel, health) |
| `QANTARA_BACKEND_CONNECT_TIMEOUT` | `10` | Seconds to open the TCP connection for the event stream |
| `QANTARA_BACKEND_IDLE_TIMEOUT` | `90` | Seconds the event stream may stay completely silent before the turn fails |

The client never follows redirects and ignores proxy environment variables.

## Routes

All request and response bodies are JSON objects (`Content-Type:
application/json`), except the event stream.

| Method and path | Request body | Success response |
|---|---|---|
| `GET /health` | — | `{"status": "ok" \| "degraded", "detail": "..."}` |
| `POST /sessions` | `{"client_context": {...}}` | `{"session_handle": "<opaque>"}` (may add `"resumed": bool`) |
| `POST /sessions/{session}/turns` | `{"transcript": "...", "turn_context": {...}}` | `{"turn_handle": "<opaque>"}` |
| `GET /sessions/{session}/turns/{turn}/events` | — | `200` stream of events (below) |
| `POST /sessions/{session}/turns/{turn}/cancel` | `{"cancel_context": {...}}` | `{"status": "acknowledged", "mode": "best_effort"}` |

Notes:

- Handles are opaque strings chosen by the backend. Qantara never parses them.
  They are not secret from the browser: the gateway reports the session handle
  in its `adapter_session_ready` event (`runtime_session_handle`).
- `client_context` may contain `client_name`, `session_id` (the gateway's
  connection id), `client_session_id` (a persistent per-browser id, useful for
  resuming a backend conversation after a page reload) and `voice_id`.
  Ignore unknown keys.
- `turn_context` is transient per-turn metadata: `source`, `modality`,
  `primary_language`, `input_language`, `output_language`, `translation_mode`,
  `translation_source`, `translation_target`, `translation_directive`,
  `voice_id`, `requested_voice_id`, `speech_rate`. It is not durable memory.
  [`gateway/session_backend_prompts.py`](../gateway/session_backend_prompts.py)
  shows how the bundled bridges turn it into model instructions.
- `/health` should be cheap. Report `"degraded"` (with HTTP 200) when the
  backend is up but cannot serve turns, for example when its model is missing.
- The bundled backends reject transcripts over 16 KiB with `413`.

## Errors

A failed JSON request returns an HTTP status of 400 or above with a JSON body
`{"error": "<human-readable message>"}`. The client raises an error carrying
the status and body.

`404` with an error mentioning `unknown session` (for example
`{"error": "unknown session handle"}`) has a defined meaning: the session
expired, was evicted, or the backend restarted. The client raises
`adapters.base.UnknownSessionError`, and callers may start a new session and
retry. Other errors must not be treated as a reason to discard the
conversation. Unknown turns use `{"error": "unknown turn handle"}`.

## Event stream

`GET .../events` responds `200` and streams one event per line.

### Framing

The client accepts either framing, line by line, as UTF-8:

- **NDJSON** (used by all bundled backends): `Content-Type:
  application/x-ndjson`, one JSON object per line.
- **SSE-style**: lines of the form `data: {json}`. `event:` lines and comment
  lines starting with `:` are ignored.

Rules:

- Each JSON object is one [agent-protocol stream event](agent.md#stream-events-adapter--gateway)
  with a `type` field. Extra fields such as `turn_handle` are allowed.
- A single line may be at most 1 MiB (1,048,576 characters). Longer lines fail
  the turn. Write JSON with `ensure_ascii=False` so non-Latin text (Arabic,
  for example) is not inflated by `\uXXXX` escapes.
- Blank lines and lines that are not valid JSON objects are ignored.
- Chunk boundaries do not matter: lines and UTF-8 characters may be split
  across TCP reads.

### Event order

```
(assistant_activity | assistant_text_delta)*  assistant_text_final?  terminal
terminal = turn_completed | turn_failed | cancel_acknowledged
```

- `assistant_text_final.text` must equal the concatenation of every
  `assistant_text_delta.text` sent for the turn. The gateway speaks the part
  it has not spoken yet by offset, so a final that is reformatted (for
  example with markdown stripped) garbles speech. Send the final text raw.
- End every stream with exactly one terminal event, then close the response.
  If the stream ends without one, the gateway treats the buffered deltas as
  the final text.
- `turn_failed` carries `message`. The OpenClaw bridge also sends
  `failure_kind` (`timeout` or `agent_error`) and `retriable` (bool). These
  fields are informational: the gateway does not retry on its own.

### Failures inside the stream

After the `200` headers are sent, report a failure as an event, not as an HTTP
status. The client also treats these as `turn_failed`:

- an object with an `error` field and no `type`, e.g. `{"error": "model not loaded"}`;
- an SSE `error:` line, e.g. `error: {"message": "agent crashed"}`.

### Keep-alives and timeouts

The event stream has no total time limit: an agent turn may take minutes.
Instead the client fails the turn when the stream is **silent** for
`QANTARA_BACKEND_IDLE_TIMEOUT` seconds (default 90). A backend that works for
a long time without producing text must send something at least that often.
The bundled bridges send an activity event at least every
`QANTARA_BACKEND_KEEPALIVE_SECONDS` (default 10) while silent:

```json
{"type": "assistant_activity", "activity_type": "thinking", "summary": "Still working"}
```

The browser shows it in the activity strip. An empty line also resets the
idle timer without showing anything.

When the idle timeout fires, the client sends a best-effort
`POST .../cancel` with `{"cancel_context": {"reason": "idle_timeout"}}` and
fails the turn with a message naming `QANTARA_BACKEND_IDLE_TIMEOUT`.

## Cancellation

`POST .../cancel` is best-effort and must return quickly. After it:

- a turn that has not started yet must never start (it could have side
  effects);
- a running turn should stop as soon as possible, and its event stream should
  end with `cancel_acknowledged`;
- cancelling an unknown turn returns `404`; cancelling a finished turn is
  harmless.

The gateway stops playback on its own, and force-cancels its read of the
stream after `QANTARA_TURN_CANCEL_GRACE_MS` (default 750 ms), so a slow
cancel never blocks the voice session.

## Concurrency

The client may open the next turn's stream while an earlier turn is still
finishing. A backend that must serialize turns per session (as the OpenClaw
bridge does) should queue them, and should still honour a cancel for a
queued turn right away.

## Minimal example

```text
POST /sessions                      {"client_context": {"client_session_id": "b-42"}}
<- {"session_handle": "s1"}
POST /sessions/s1/turns             {"transcript": "hello", "turn_context": {"output_language": "en"}}
<- {"turn_handle": "t1"}
GET  /sessions/s1/turns/t1/events
<- {"type": "assistant_text_delta", "text": "Hi, "}
<- {"type": "assistant_text_delta", "text": "how can I help?"}
<- {"type": "assistant_text_final", "text": "Hi, how can I help?"}
<- {"type": "turn_completed"}
```

The fake backend (`gateway/fake_session_backend/server.py`) is a complete,
dependency-free reference implementation of these routes.
