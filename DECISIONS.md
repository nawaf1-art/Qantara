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

## Open

### D-005: Downstream Runtime Binding

Status: open

Decision needed:

- when to bind Qantara to a specific OpenClaw deployment
- which runtime interface to target first
- how much of the integration contract should be mocked before environment validation

Why it matters:

- avoids prematurely coupling the project to a specific local agent topology
- defines the real adapter surface that the voice gateway must support

### D-006: Assistant Output To TTS Buffering Policy

Status: open

Decision needed:

- sentence-buffered
- punctuation-aware chunking
- immediate token-driven synthesis

Why it matters:

- affects latency, coherence, and interruption quality

### D-007: Interruption Cancel Semantics

Status: open

Decision needed:

- playback stop only
- playback stop plus model cancel
- playback stop plus truncation marker when model cancel is unavailable

Why it matters:

- affects history consistency and downstream race conditions

### D-008: First Local Speech Engines

Status: open

Decision needed:

- first STT engine
- first TTS engine
- model size targets for baseline hardware

Why it matters:

- affects boot time, latency, and deployment footprint

### D-009: Gateway Implementation Path

Status: open

Decision needed:

- custom async gateway
- Pipecat-based prototype
- hybrid approach where Pipecat is used only for evaluation

Why it matters:

- affects dependency weight, control over the state machine, and speed of implementation

### D-010: Transport Strategy

Status: open

Decision needed:

- raw PCM over WebSocket
- WebRTC transport
- staged approach that starts with WebSocket and evaluates WebRTC later

Why it matters:

- affects echo handling, browser complexity, and end-to-end latency characteristics
