# Architecture

## System Overview

Qantara is a voice gateway that sits between a browser client on the LAN and OpenClaw.

It is responsible for:

- receiving live microphone audio from the client
- detecting speech activity and turn boundaries
- producing partial and final transcripts
- forwarding finalized turns to OpenClaw
- receiving assistant output
- converting assistant output into local speech playback
- handling interruption and recovery

OpenClaw remains responsible for:

- agent runtime and tool execution
- session and conversation state
- model orchestration
- permission model inside the agent environment

## Initial Topology

1. Browser client on the LAN captures mic audio with WebAudio and sends small PCM frames over WebSocket.
2. Qantara voice gateway maintains per-session audio, transcript, and playback state.
3. Qantara sends finalized user utterances into OpenClaw.
4. OpenClaw returns assistant output through a stream or equivalent event channel.
5. Qantara buffers assistant text into speakable units and emits TTS audio chunks back to the client.
6. If user speech is detected during assistant playback, Qantara triggers barge-in handling immediately.

## Browser-First Client Responsibilities

The initial browser client should be deliberately thin.

Responsibilities:

- request microphone permission
- capture audio frames with predictable timing
- send frames and control events over WebSocket
- render partial and final captions
- play assistant audio as soon as chunks are available
- show session status, listening state, and speaking state
- recover cleanly from socket interruption or device change

The browser client should not own speech recognition, TTS, or agent state. Those belong in the voice gateway and OpenClaw.

## Why External First

An external gateway is the safer first architecture because the hardest problems are transport, concurrency, endpointing, barge-in, and cancellation semantics. Those can be solved without tightly binding the first version to OpenClaw internals.

Later, if OpenClaw exposes stable runtime hooks for streaming, cancellation, and session control, some or all of Qantara may be migrated into a plugin.

## Session Model

Each voice session should maintain:

- session identifier
- client connection state
- audio ingress buffer
- VAD state
- transcript state: partial, final, pending
- OpenClaw turn state
- assistant output buffer
- TTS playback queue
- cancellation token set
- metrics and event log handles

Assume one active speaker per session for the MVP.

For the browser-first milestone, also track:

- browser client identifier
- websocket connection generation
- selected audio input device metadata when available
- client playback state

## State Machine

### 1. LISTENING

The gateway accepts microphone frames continuously.

Responsibilities:

- maintain rolling audio buffer
- run VAD
- produce partial transcript updates
- detect speech start and speech end

Transitions:

- to `USER_SPEAKING` when speech is detected
- stays in `LISTENING` during silence while assistant is idle

### 2. USER_SPEAKING

The user is actively speaking and the gateway is accumulating transcript context.

Responsibilities:

- continue partial transcription
- watch for silence threshold
- trigger playback stop if assistant audio is currently active

Transitions:

- to `ENDPOINTED` when silence threshold is reached
- back to `LISTENING` if speech is abandoned and no usable transcript exists

### 3. ENDPOINTED

The gateway has decided the utterance is complete enough to submit.

Responsibilities:

- freeze the final transcript
- attach interruption metadata if the user spoke over assistant audio
- submit the finalized turn to OpenClaw

Transitions:

- to `THINKING` after successful submission
- to `RECOVERY` on submission failure

### 4. THINKING

OpenClaw is processing the user turn and assistant output is pending.

Responsibilities:

- wait for first assistant output event
- keep listening for new user speech
- prepare cancellation path if user interrupts before playback starts

Transitions:

- to `SPEAKING` when enough assistant text exists to synthesize audio
- to `USER_SPEAKING` if interruption occurs before playback starts
- to `RECOVERY` on timeout or downstream failure

### 5. SPEAKING

Assistant audio is being streamed or played to the client while the gateway continues listening.

Responsibilities:

- convert assistant text into speakable chunks
- manage a jitter buffer for outbound audio
- continue monitoring mic input for barge-in

Transitions:

- to `LISTENING` after assistant output completes
- to `USER_SPEAKING` on barge-in
- to `RECOVERY` on TTS or transport failure

### 6. RECOVERY

The session encountered an STT, TTS, transport, or OpenClaw error.

Responsibilities:

- preserve enough state for debug
- notify the client of degraded mode
- fall back to text output where possible
- clear stale playback and cancellation tokens

Transitions:

- to `LISTENING` after cleanup
- terminal close if the session is unrecoverable

## Barge-In Semantics

Qantara should explicitly support two interruption levels.

### Soft Barge-In

- stop assistant audio playback immediately
- continue listening to the user
- do not assume model generation was cancelled

Use this when OpenClaw cannot reliably cancel an in-flight generation.

### Hard Barge-In

- stop assistant audio playback immediately
- request generation cancellation or truncation from OpenClaw
- mark the interrupted assistant turn in session metadata

Use this when the downstream runtime offers a real cancellation primitive.

## Assistant Output Buffering

Do not feed raw token deltas directly into TTS unless the voice engine can tolerate unstable text.

Preferred strategy:

- buffer to sentence boundaries when possible
- allow early chunk synthesis for low-latency starts
- maintain rollback-safe boundaries so interrupted or revised text does not produce incoherent speech

This policy needs to be chosen early because it affects latency, voice quality, and interruption handling.

## Echo And Acoustic Constraints

Simultaneous listening and speaking means acoustic feedback is a primary risk.

For the MVP:

- prefer headset-first testing
- treat open-speaker mode as experimental
- keep echo cancellation out of the critical path unless a suitable local solution is selected early

Without this constraint, playback may re-enter STT and create false interruptions or self-triggered loops.

For the browser-first path, this is especially important because browser audio routing is less controllable than a native desktop client.

## Security Model

Qantara should default to private-network deployment:

- bind to LAN or loopback interfaces only
- require signed session tokens or equivalent authenticated client sessions
- separate voice-triggered actions from unrestricted agent permissions where possible
- enforce confirmation gates for high-risk tools

Recommended high-risk categories:

- shell execution
- external messaging
- destructive file operations
- privileged network actions

## Observability

Instrumentation is required from the first implementation phase.

Per session, capture at minimum:

- speech start time
- endpoint detect time
- final transcript emit time
- OpenClaw submit time
- first assistant output time
- first TTS chunk time
- playback start time
- interruption time
- cancel acknowledge time if supported

These timestamps are needed to debug latency and race conditions.

## Open Questions

- What exact assistant output streaming interface does OpenClaw provide?
- Can OpenClaw cancel active generation, or only ignore late output?
- How should interrupted assistant responses be stored in history?
- What minimum hardware profile should be supported for local STT and TTS?
- When should the browser-first client be wrapped or replaced by a desktop shell, if at all?
