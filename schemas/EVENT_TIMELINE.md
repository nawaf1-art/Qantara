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
- `session_closed`

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
- `final_transcript_ready`

### Downstream Turn

- `turn_submit_started`
- `turn_submit_accepted`
- `assistant_output_started`
- `assistant_output_delta`
- `assistant_output_completed`
- `turn_cancel_requested`
- `turn_cancel_acknowledged`

### Playback

- `tts_chunk_ready`
- `playback_started`
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

### `interruption_detected`

Recommended payload:

- `source`
- `during_state`
- `playback_active`

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
