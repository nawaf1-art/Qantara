# Event Timeline

## Purpose

This document defines the minimum event timeline schema Qantara must emit from the beginning of implementation.

The goal is to make latency and failure analysis possible from the first gateway spike.

## Event Rules

- every event must include `session_id`
- every event must include a monotonic timestamp field
- event names should be stable and explicit
- payloads should be additive over time rather than frequently renamed

## Minimum Event Shape

```text
{
  event_name: string,
  session_id: string,
  connection_id: string | null,
  turn_id: string | null,
  ts_monotonic_ms: number,
  ts_wall_time: string,
  source: "browser" | "gateway" | "adapter" | "speech" | "playback",
  payload: object
}
```

## Required Events

### Session Lifecycle

- `session_created`
- `session_connected`
- `session_ready`
- `session_state_changed`
- `session_closed`

### Mesh (0.2.2)

- `mesh_peer_discovered`
- `mesh_peer_lost`
- `mesh_election_started`
- `mesh_election_resolved`
- `turn_deferred_to_peer`

### Browser Transport

- `mic_stream_started`
- `mic_stream_stopped`
- `input_audio_frame_received`
- `output_audio_frame_sent`
- `socket_disconnected`
- `socket_reconnected`

### Speech Boundary

- `speech_start_detected`
- `speech_end_detected`
- `endpoint_timer_started`
- `endpoint_aborted`
- `partial_transcript_ready`
- `final_transcript_ready`

### Downstream Turn

- `turn_submit_started`
- `turn_submit_accepted`
- `assistant_output_started`
- `assistant_output_delta`
- `assistant_activity`
- `assistant_output_completed`
- `turn_cancel_requested`
- `turn_cancel_acknowledged`
- `turn_interrupted`

### Playback

- `tts_chunk_ready`
- `playback_started`
- `playback_first_frame_sent`
- `playback_stopped`
- `playback_queue_cleared`

### Interruption

- `interruption_detected`
- `interruption_promoted_to_cancel`

### Errors And Recovery

- `recoverable_error`
- `recovery_started`
- `recovery_completed`
- `terminal_error`

## Required Derived Measurements

The system should be able to derive at least:

- session setup time
- speech duration
- endpointing delay
- transcript finalization delay
- submit-to-first-output delay
- first-output-to-first-audio delay
- interruption-to-playback-stop delay

## Minimum Payload Guidance

### `input_audio_frame_received`

Recommended payload:

- `frame_bytes`
- `sample_rate`
- `channels`

### `final_transcript_ready`

Recommended payload:

- `char_count`
- `token_estimate`
- `had_partial_transcript`

### `assistant_output_delta`

Recommended payload:

- `delta_chars`
- `buffered_chars`

### `tts_chunk_ready`

Recommended payload:

- `chunk_index`
- `chunk_ms`
- `chunk_bytes`
- `synthesis_ms`

### `playback_first_frame_sent`

Recommended payload:

- `kind`
- `tts_to_first_audio_ms`
- `synthesis_ms`

### `interruption_detected`

Recommended payload:

- `source`
- `during_state`
- `playback_active`

### `partial_transcript_ready`

Recommended payload:

- `text`
- `ms_since_speech_start`
- `stable_prefix_chars` (characters that have not changed across the last N ticks; the UI may render these in a different weight)
- `provider_kind`

Partials are additive but the full `text` is always sent; the client replaces rather than appends. Cleared on `final_transcript_ready`.

### `session_state_changed`

Recommended payload:

- `previous_state`
- `current_state` (`idle` | `listening` | `thinking` | `speaking` | `interrupted`)
- `ms_in_previous_state`
- `reason` (optional — e.g. `speech_start_detected`, `turn_submit_accepted`, `playback_first_frame_sent`, `interruption_detected`)

Source is always `"session"`. Emitted exactly once per transition; clients should treat as authoritative UI state.

### `assistant_activity`

Non-spoken activity indication from the adapter — e.g. "reading 3 files", "searching the web", "thinking". Distinct from `assistant_output_delta` (spoken prose). Adapters that don't know activity can simply never emit this event.

Recommended payload:

- `activity_type` (`tool_call` | `reading_files` | `searching` | `thinking` | `other`)
- `summary` (one-sentence human-readable string; the client may display it verbatim)
- `progress` (optional float 0..1)

### `turn_interrupted`

Emitted when a user barge-in cancels an in-flight turn. Distinct from `turn_cancel_requested` (which describes the client/gateway intent) — `turn_interrupted` describes the *outcome*: the turn is stopped, partial state has been captured, and the client can render gracefully without having to reconstruct context.

Recommended payload:

- `partial_text` (what had been spoken/streamed so far)
- `resumable` (bool — whether the backend kept state that could resume)
- `interrupted_during_state` (`thinking` | `speaking` — the state the session was in)

### `mesh_peer_discovered`

Recommended payload:

- `node_id`
- `role` (`full` / `mic-only` / `speaker-only`)
- `host`
- `port`

### `mesh_peer_lost`

Recommended payload:

- `node_id`

### `mesh_election_started`

Recommended payload:

- `session_id`
- `local_rms`
- `peer_count`

### `mesh_election_resolved`

Recommended payload:

- `session_id`
- `winner_node_id`
- `should_claim` (bool — whether this node won)
- `window_ms`
- `local_rms`
- `peer_count`

### `turn_deferred_to_peer`

Emitted when the local node lost a mesh election and another peer is taking the turn. Client-side cue to suppress the pending turn-submit UI.

Recommended payload:

- `reason` (`mesh_election_lost`)
- `winner_node_id`

### `recoverable_error`

Recommended payload:

- `component`
- `error_code`
- `message`

## Example Timeline

```text
session_created
session_connected
session_ready
mic_stream_started
speech_start_detected
speech_end_detected
endpoint_timer_started
final_transcript_ready
turn_submit_started
turn_submit_accepted
assistant_output_started
tts_chunk_ready
playback_started
interruption_detected
playback_stopped
turn_cancel_requested
turn_cancel_acknowledged
session_closed
```

## M0 Decision Target

This schema is good enough for M0 if:

- a transport spike can emit placeholder versions of the required events
- the event list is sufficient to compute the first latency metrics
- future STT, TTS, and runtime work can add payload detail without renaming core events
