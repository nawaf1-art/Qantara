# Session Gateway Contract

## Purpose

This document defines the first concrete backend contract shape Qantara should target behind the adapter framework.

It is intentionally generic. It does not assume:

- a specific OpenClaw installation
- a specific host or token layout
- a specific agent identifier

## Contract Style

The contract is `session-oriented` and `text-first`.

Qantara remains responsible for:

- browser transport
- mic capture and VAD
- STT
- TTS
- playback interruption at the client edge

The backend remains responsible for:

- session ownership
- turn submission
- assistant generation
- optional tool execution
- optional cancel or truncate support

## Minimum Endpoints

### 1. Health

```text
GET /health
```

Expected response:

```json
{
  "status": "ok" | "degraded" | "unavailable",
  "detail": "optional string"
}
```

### 2. Start Or Resume Session

```text
POST /sessions
```

Request:

```json
{
  "client_context": {
    "client_name": "browser-transport-spike",
    "session_id": "qantara-session-id"
  }
}
```

Response:

```json
{
  "session_handle": "opaque-backend-session-id"
}
```

### 3. Submit User Turn

```text
POST /sessions/{session_handle}/turns
```

Request:

```json
{
  "transcript": "finalized user text",
  "turn_context": {
    "source": "transport_spike"
  }
}
```

Response:

```json
{
  "turn_handle": "opaque-backend-turn-id"
}
```

### 4. Stream Assistant Output

```text
GET /sessions/{session_handle}/turns/{turn_handle}/events
```

The response should be one of:

- `text/event-stream`
- newline-delimited JSON

Qantara needs these event types at minimum:

- `assistant_text_delta`
- `assistant_text_final`
- `turn_completed`
- `turn_failed`
- `cancel_acknowledged`

Example NDJSON event:

```json
{"type":"assistant_text_delta","text":"Hello"}
```

### 5. Cancel Turn

```text
POST /sessions/{session_handle}/turns/{turn_handle}/cancel
```

Request:

```json
{
  "cancel_context": {
    "reason": "user_interruption"
  }
}
```

Response:

```json
{
  "status": "acknowledged" | "unsupported"
}
```

## Error Semantics

The backend should use status codes and bodies that let the adapter classify failures into:

- `retryable`
- `non_retryable`
- `degraded_but_usable`

Recommended examples:

- `503`: retryable or degraded
- `401` / `403`: non-retryable until configuration changes
- `404` on session or turn handles: non-retryable for the current operation
- `501` on cancel: degraded but usable

## Why This Shape First

This contract matches Qantara's current design because:

- it preserves backend session ownership
- it supports streaming text without pushing audio ownership into the backend
- it leaves room for cancellation later
- it can map to OpenClaw-compatible or other agent runtimes later

## Qantara Mapping

The current adapter interface maps directly:

```text
start_or_resume_session -> POST /sessions
submit_user_turn -> POST /sessions/{session_handle}/turns
stream_assistant_output -> GET /sessions/{session_handle}/turns/{turn_handle}/events
cancel_turn -> POST /sessions/{session_handle}/turns/{turn_handle}/cancel
check_health -> GET /health
```

## Non-Goals

This contract does not standardize:

- audio transport
- browser session auth UX
- tool event schemas beyond simple optional observability
- exact backend deployment topology
