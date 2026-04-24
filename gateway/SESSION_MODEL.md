# Session Model

## Purpose

This document defines the minimum session model for the custom Qantara gateway during M0 and M1.

The model is intentionally limited to:

- one browser client
- one active voice session
- one active speaker at a time
- no binding to a specific downstream runtime implementation yet

## Session Ownership

The gateway owns:

- connection lifecycle
- transport state
- playback state
- interruption state
- speech pipeline coordination state
- event timeline emission

The downstream runtime does not own browser transport or playback behavior.

## Session Identity

Each session should have:

- `session_id`
- `client_id`
- `connection_id`
- `created_at`
- `last_activity_at`
- `status`

`connection_id` should change on reconnect. `session_id` should remain stable if the reconnect is treated as session continuation.

## Session States

### `idle`

The session exists but audio streaming has not started yet.

### `connecting`

The browser socket is established and the gateway is negotiating or validating the session.

### `ready`

The session is healthy and able to accept audio input or playback output.

### `listening`

The gateway is receiving microphone audio and waiting for speech or continuing to monitor speech.

### `user_speaking`

Speech is currently active according to the gateway's speech boundary logic.

### `endpoint_pending`

Speech appears to have ended and the gateway is waiting for the configured silence or endpoint condition to finalize the turn.

### `submitting`

The final user turn is being sent to the downstream runtime adapter.

### `awaiting_output`

The downstream runtime has accepted the turn and the gateway is waiting for assistant output.

### `speaking`

The gateway is sending assistant audio to the browser.

### `interrupted`

User speech or an explicit control event interrupted assistant playback or generation handling.

### `recovering`

The session hit a transport, playback, STT, TTS, or adapter error and is attempting controlled recovery.

### `closed`

The session is terminated and should not accept new input.

## State Transition Rules

- `idle -> connecting`
  Trigger: client begins session bootstrap

- `connecting -> ready`
  Trigger: session accepted and transport initialized

- `ready -> listening`
  Trigger: microphone stream starts

- `listening -> user_speaking`
  Trigger: speech start detected

- `user_speaking -> endpoint_pending`
  Trigger: speech drops below threshold and endpoint timer begins

- `endpoint_pending -> listening`
  Trigger: endpoint aborted because speech resumed or transcript is discarded

- `endpoint_pending -> submitting`
  Trigger: final transcript accepted for turn submission

- `submitting -> awaiting_output`
  Trigger: adapter accepts the turn

- `awaiting_output -> speaking`
  Trigger: first speakable assistant output is available

- `speaking -> interrupted`
  Trigger: user speech, explicit stop, or playback cancel event

- `interrupted -> user_speaking`
  Trigger: interruption is caused by fresh user speech

- `speaking -> listening`
  Trigger: assistant output and playback complete normally

- `any active state -> recovering`
  Trigger: recoverable transport or pipeline error

- `recovering -> ready`
  Trigger: cleanup succeeds

- `any state -> closed`
  Trigger: terminal shutdown or unrecoverable error

## Minimum Per-Session Data

### Identity

- `session_id`
- `client_id`
- `connection_id`

### Transport

- `socket_state`
- `input_audio_format`
- `output_audio_format`
- `last_input_frame_at`
- `last_output_frame_at`

### Speech Input

- `speech_state`
- `speech_started_at`
- `speech_ended_at`
- `endpoint_deadline_at`
- `partial_transcript`
- `final_transcript`

### Downstream Turn

- `current_turn_id`
- `turn_submit_started_at`
- `turn_submit_completed_at`
- `adapter_request_state`

### Assistant Output

- `assistant_text_buffer`
- `assistant_output_started_at`
- `assistant_output_completed_at`
- `tts_chunking_mode`

### Playback

- `playback_state`
- `playback_started_at`
- `playback_stopped_at`
- `playback_queue_depth`

### Interruption

- `interruption_state`
- `interruption_detected_at`
- `interruption_source`
- `cancel_requested`
- `cancel_acknowledged_at`

### Observability

- `event_sequence`
- `metrics_snapshot`
- `last_error`

## Cancellation Ownership

The gateway owns cancellation tokens for:

- playback stop
- pending TTS work
- downstream generation cancel requests

The session model should allow playback cancel to succeed even if downstream generation cancel is unavailable.

## Browser Coordination Events

At minimum, the browser should be able to observe:

- session accepted
- session ready
- listening
- user speaking
- thinking or awaiting output
- assistant speaking
- interrupted
- degraded or recovering
- closed

These are UI-facing states, not a replacement for the internal state machine.

## Runtime Readiness Target

This model is ready for local gateway use when:

- the states are sufficient for the browser voice transport
- interruption behavior has an explicit home in the model
- the adapter boundary can attach cleanly without leaking transport concerns
