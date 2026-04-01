# Decisions

## Accepted

### D-001: External Voice Gateway First

Status: accepted

Qantara will start as an external service beside OpenClaw instead of an in-process plugin.

Reason:

- lower iteration cost
- cleaner separation of concerns
- less coupling while the interaction protocol is still unstable

Revisit when:

- OpenClaw runtime hooks for streaming, cancellation, and session control are proven sufficient

### D-002: Browser-First Client

Status: accepted

The first client target is the browser.

Reason:

- easiest LAN distribution path
- fastest route to real user testing
- enough capability to validate mic capture, captions, audio playback, and reconnect behavior

Tradeoff:

- less direct control over audio hardware and background behavior than a native desktop client

Revisit when:

- the wire protocol stabilizes
- desktop-specific requirements appear

### D-003: Full-Duplex Interaction Is Mandatory

Status: accepted

The primary product mode is simultaneous listening and speaking with barge-in support. Push-to-talk is not the main UX.

Reason:

- this matches the intended conversational workflow
- it forces the architecture to solve interruption semantics correctly from the start

Tradeoff:

- echo control and cancellation behavior become first-class problems immediately

### D-004: Headset-First MVP

Status: accepted

Early milestones assume headset-first operation.

Reason:

- it reduces acoustic feedback risk
- it keeps the MVP focused on transport and orchestration instead of echo cancellation

Tradeoff:

- early demos may not reflect open-speaker production use

### D-005: WebSocket-First Transport

Status: accepted

Qantara will start with raw PCM over WebSocket for the browser-to-gateway transport.

Reason:

- fastest path to a controlled LAN MVP
- simplest transport to debug while the session model is still evolving
- sufficient for headset-first, single-session validation

Tradeoff:

- weaker media handling and echo resilience than a WebRTC-based path
- likely not the final transport if speaker-mode and broader client robustness become important

Revisit when:

- Qantara moves beyond headset-first usage
- speaker-mode full-duplex behavior becomes a primary target
- transport reliability problems are caused by media-layer limitations rather than gateway logic

### D-006: Custom Gateway With Pipecat Evaluation

Status: accepted

Qantara will use a custom async voice gateway as the primary architecture, while Pipecat will be evaluated as a reference and prototype path during early validation.

Reason:

- preserves control over session state, interruption semantics, and runtime adapter boundaries
- avoids locking the core architecture to a framework before the hard interaction problems are proven
- still allows rapid comparison against a framework that closely matches the problem space

Tradeoff:

- more implementation work in the core gateway
- requires discipline to keep the evaluation path from turning into accidental framework lock-in

Revisit when:

- Pipecat demonstrates a materially better path for Qantara's exact session and interruption model
- the custom gateway starts reimplementing framework behavior with no strategic benefit

## Open

### D-007: Downstream Runtime Binding

Status: open

Decision needed:

- when to bind Qantara to a specific OpenClaw deployment
- which runtime interface to target first
- how much of the integration contract should be mocked before environment validation

Why it matters:

- avoids prematurely coupling the project to a specific local agent topology
- defines the real adapter surface that the voice gateway must support

Current direction:

- the first concrete backend adapter should target a `session-oriented agent gateway` shape
- see [`BACKEND_ADAPTER_TARGETS.md`](/home/nawaf/Projects/Qantara/BACKEND_ADAPTER_TARGETS.md)

### D-008: Assistant Output To TTS Buffering Policy

Status: open

Decision needed:

- sentence-buffered
- punctuation-aware chunking
- immediate token-driven synthesis

Why it matters:

- affects latency, coherence, and interruption quality

### D-009: Interruption Cancel Semantics

Status: open

Decision needed:

- playback stop only
- playback stop plus model cancel
- playback stop plus truncation marker when model cancel is unavailable

Why it matters:

- affects history consistency and downstream race conditions

### D-010: First Local Speech Engines

Status: open

Decision needed:

- first STT engine
- first TTS engine
- model size targets for baseline hardware

Why it matters:

- affects boot time, latency, and deployment footprint

### D-011: Initial TTS Chunking Rule

Status: open

Decision needed:

- sentence-buffered first chunk
- punctuation-aware early chunking
- token-count fast path for first audio

Why it matters:

- directly affects first-audio latency and spoken coherence

### D-012: WebRTC Migration Trigger

Status: open

Decision needed:

- what concrete conditions should trigger migration from WebSocket to WebRTC
- whether migration should happen at the browser edge only or more broadly in the transport layer

Why it matters:

- keeps the MVP simple without losing the long-term media path
- avoids premature transport complexity while preserving a clear escalation rule
