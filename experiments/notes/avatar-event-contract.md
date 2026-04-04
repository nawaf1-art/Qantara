# Avatar Event Contract

This note defines the smallest useful gateway-owned event surface for a future avatar or presentation layer.

It does not add avatar rendering to Qantara.

It only describes which existing gateway events should be treated as stable inputs for a future consumer.

## Goal

Keep Qantara as a voice gateway.

Let a later avatar layer subscribe to gateway events without forcing avatar-specific logic into the gateway.

## Event Groups

### Session Events

These define connection and session lifecycle:

- `session_created`
- `session_connected`
- `session_ready`
- `socket_disconnected`
- `session_closed`

Future avatar use:
- reset avatar state on connect or disconnect
- show offline, ready, and ended states

### User Speech Events

These define live user speech boundaries:

- `mic_stream_started`
- `mic_stream_stopped`
- `speech_start_detected`
- `speech_end_detected`
- `endpoint_timer_started`
- `transcription_requested`
- `final_transcript_ready`

Future avatar use:
- indicate user speaking
- show listening state
- display captions or transcript previews

### Agent Turn Events

These define assistant turn lifecycle:

- `turn_submit_started`
- `turn_submit_accepted`
- `turn_state` with `active` and `idle`
- `assistant_output_started`
- `assistant_output_completed`
- `turn_cancel_requested`
- `turn_cancel_acknowledged`

Future avatar use:
- show agent thinking, speaking, interrupted, and idle states

### Assistant Text Events

These define assistant text output:

- `assistant_text_delta`
- `assistant_text_final`

Future avatar use:
- live captions
- final subtitle text

### Playback Events

These define audio playback lifecycle:

- `tts_status`
- `playback_started`
- `playback_first_frame_sent`
- `playback_metrics`
- `playback_stopped`
- `playback_queue_cleared`
- `playback_cleared`

Future avatar use:
- start lip-sync when playback begins
- stop lip-sync when playback ends or is cleared
- align animation timing with first-audio and stop events

### Transport Audio Events

These define lower-level audio frame flow:

- `input_audio_frame_received`
- `output_audio_frame_sent`

Future avatar use:
- optional diagnostics only
- not required for the first avatar layer

## Stable Boundary

The first avatar layer should only depend on:

- session events
- user speech events
- agent turn events
- assistant text events
- playback events

It should not require raw frame events for its first implementation.

## What Stays Out Of Scope

This event contract does not include:

- emotion tags
- gesture tags
- semantic intent labels
- camera control
- avatar asset selection
- cloned voice asset management

Those belong to higher-level orchestration or presentation layers, not the gateway.

## Practical Implication

If Qantara keeps these event groups stable, a future avatar layer can be added as a subscriber without changing the core voice pipeline.
