# Qantara Agent Protocol v1

Status: stable as of `0.2.9`. This document formalizes the event contract
between a backend adapter, the Qantara gateway, and the browser client. The
events themselves shipped across `0.2.1`–`0.2.8`; this spec freezes their
shapes so adapter authors and client integrators can build against them.

Audio never flows through this protocol — it stays on the WebSocket PCM
path. Everything below is control-plane JSON.

## Roles

```
Adapter ──(stream events)──▶ Gateway ──(session events)──▶ Browser / event sink
```

- **Adapter** (`adapters/base.py:RuntimeAdapter`): wraps a backend runtime
  (OpenAI-compatible server, MCP server, session-contract bridge). Yields
  *stream events* from `stream_assistant_output()`.
- **Gateway**: validates and forwards adapter events, owns the session state
  machine, and emits *session events* to the browser over `/ws` and to the
  configured event sink.

## Session state machine

The gateway holds one state per session:

```
idle → listening → thinking → speaking → idle
                      └──── interrupted ────┘
```

| State | Meaning |
|---|---|
| `idle` | No speech, no active turn |
| `listening` | VAD detected user speech |
| `thinking` | Turn submitted; waiting on the adapter |
| `speaking` | TTS playback streaming to the client |
| `interrupted` | A barge-in cancelled an in-flight turn (transient; settles to `idle`) |

## Stream events (adapter → gateway)

`stream_assistant_output(session_handle, turn_handle)` yields dicts with a
`type` field:

| Type | Required fields | Notes |
|---|---|---|
| `assistant_text_delta` | `text` | Incremental prose; the gateway chunks it into TTS at sentence breaks |
| `assistant_text_final` | `text` | Authoritative full reply; unsent remainder is spoken |
| `assistant_activity` | `activity_type`, `summary` | Non-spoken status; see below |
| `cancel_acknowledged` | — | Adapter confirms a `cancel_turn`; ends the stream |
| `turn_failed` | `message` | Terminal failure for this turn |
| `turn_completed` | — | Optional explicit completion marker |

If the stream ends without `assistant_text_final`, the gateway flushes the
buffered deltas as the final text.

### `assistant_activity` and tool-call metadata (v1)

Use `adapters.base.make_activity_event()` to construct these — it enforces
everything below.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `activity_type` | string | yes | One of `tool_call`, `reading_files`, `searching`, `thinking`, `other`. Unknown values are coerced to `other` |
| `summary` | string | yes | One human-readable sentence; the client renders it verbatim |
| `progress` | number | no | Clamped to `0..1` |
| `tool_name` | string | no | Name of the tool being invoked (`tool_call` activities) |
| `parameters` | object | no | Tool-call arguments. Must be a JSON object; dropped if its serialized form exceeds 2048 chars |
| `confidence` | number | no | Adapter's self-reported confidence, clamped to `0..1` |

The gateway re-validates activity events before forwarding: adapter events
cross a trust boundary into the browser, so malformed `tool_name` /
`parameters` / `confidence` values are silently dropped rather than rendered.
The browser shows `summary` in the activity strip and exposes `tool_name` +
`parameters` as an inline tooltip on hover.

## Session events (gateway → browser / event sink)

These arrive as JSON text frames on `/ws` (field `type`) and as records in
the event timeline (field `event_name`; see `schemas/EVENT_TIMELINE.md`).

### `session_state_changed`

| Field | Type | Notes |
|---|---|---|
| `previous_state` | string | One of the states above |
| `current_state` | string | |
| `reason` | string | Machine-readable transition cause |
| `ms_since_last_state` | number | Milliseconds spent in the previous state |

### `assistant_activity`

Same shape as the stream event after gateway validation (`activity_type`,
`summary`, optional `progress`, `tool_name`, `parameters`, `confidence`).

### `turn_interrupted`

Emitted on every real barge-in, even when the adapter buffered its entire
response and no partial text exists yet.

| Field | Type | Notes |
|---|---|---|
| `partial_text` | string | Whatever the adapter had streamed before the cancel; may be empty |
| `resumable` | bool | Whether the session can accept a follow-up turn |
| `interrupted_during_state` | string | The turn phase when the cancel landed (usually `thinking` or `speaking`) |

Cancellation is not cooperative-only: after asking the adapter to cancel,
the gateway force-cancels the turn task once `QANTARA_TURN_CANCEL_GRACE_MS`
(default 750 ms) expires, so a wedged adapter cannot pin the session.

## Versioning

This is protocol v1. Additive optional fields do not bump the version;
renaming or removing a field, or changing required-ness, does. Adapters
should ignore unknown fields they receive and never rely on field order.
