# Turn Lifecycle Hardening Plan

- Status: Design plan
- Scope: future work; no wholesale lifecycle rewrite in `0.3.1`

## Problem

A voice turn crosses browser playback, gateway session state, STT, adapter submission, backend streaming, TTS queues, and cancellation. Today the behavior is tested, but ownership is distributed across session, speech, WebSocket, and adapter code. That increases the chance of late output, double completion, orphaned tasks, or stale state during disconnect/reconfiguration races.

## Desired invariants

- Exactly one active assistant turn owns output for a session.
- Every accepted turn reaches one terminal outcome: completed, failed, cancelled, or disconnected.
- Cancellation is idempotent and prevents later text/audio from reaching the client.
- Browser playback generation and backend turn generation cannot be confused.
- Session state returns to `idle` only after owned speech/output work is finished or cancelled.
- Disconnect and backend reconfiguration release tasks, streams, response objects, and provider work within bounded time.
- Terminal events are emitted once and in a documented order.

## Proposed model

Introduce an explicit `TurnCoordinator` owned by one `Session`. It would hold the turn generation, adapter handle, task group, cancellation reason, terminal outcome, and output gate. Existing functions would migrate behind it incrementally; adapter contracts would not change in the first stage.

## Delivery sequence

1. Capture the current state/event ordering as table-driven contract tests.
2. Add race tests for cancellation during submit, first token, TTS synthesis, queued playback, disconnect, and backend switch.
3. Introduce a coordinator in shadow mode that observes current transitions without owning them.
4. Move terminal-event and output-gating ownership into the coordinator.
5. Move task/process cleanup behind one idempotent close path.
6. Remove duplicated flags only after parity tests pass on WebSocket and Voice API paths.

## Required validation

- deterministic unit tests with controlled scheduling points
- property/state-machine tests for event ordering and terminal uniqueness
- real Ollama interruption and disconnect checks
- browser playback/barge-in end-to-end checks
- no regression in latency instrumentation or adapter compatibility

## Non-goals

- replacing aiohttp
- changing PCM framing or browser transport
- merging Qantara into an agent framework
- requiring hard-cancel support from every backend
