# Adapter Contract

## Purpose

This document defines the minimum downstream runtime adapter boundary for Qantara.

The adapter contract is intentionally runtime-agnostic. It must support M0 and M1 without embedding assumptions about a specific OpenClaw deployment.

## Design Rules

- the adapter must not own browser transport
- the adapter must not own playback state
- the adapter must not assume a specific agent identifier, host, or auth model
- the gateway should remain testable with a mock adapter

## Minimum Capabilities

### 1. Session Start Or Resume

The gateway needs a way to create or resume a conversational session.

Expected outcome:

- returns a runtime session handle or equivalent opaque identifier
- does not expose runtime-specific details to the browser

### 2. Submit Finalized User Turn

The gateway needs to submit a finalized user utterance after endpointing.

Input:

- session handle
- finalized transcript text
- optional interruption metadata
- optional client/session metadata

Expected outcome:

- returns an adapter turn handle or equivalent tracking identifier

### 3. Receive Assistant Output

The gateway needs a stream or event source for assistant output.

Minimum acceptable forms:

- streaming text output
- chunked output polling
- final output only as a fallback

Preferred form:

- incremental assistant text events suitable for TTS buffering

### 4. Cancel Or Truncate Current Turn

The gateway needs a way to request cancellation or truncation of the current turn if the user interrupts.

Important:

- this capability is optional at the runtime level
- the gateway still needs to function if the adapter can only stop playback locally

### 5. Health Or Availability Signal

The gateway needs a lightweight way to determine whether the adapter is healthy enough to accept work.

This can be:

- explicit health check
- connection state
- request failure semantics documented by the adapter

## Suggested Interface Shape

The contract can be represented conceptually as:

```text
start_or_resume_session(client_context) -> session_handle
submit_user_turn(session_handle, transcript, turn_context) -> turn_handle
stream_assistant_output(session_handle, turn_handle) -> output_events
cancel_turn(session_handle, turn_handle, cancel_context) -> cancel_result
check_health() -> health_state
```

The exact programming language and types remain open.

## Output Event Types

The gateway should be prepared for these adapter output events:

- `assistant_text_delta`
- `assistant_text_final`
- `tool_activity`
- `turn_completed`
- `turn_failed`
- `cancel_acknowledged`

Only the text and lifecycle events are required for M1. Tool activity is optional for later observability.

## Error Model

The adapter should classify failures into:

- `retryable`
- `non_retryable`
- `degraded_but_usable`

The gateway needs this distinction to decide whether to recover, retry, or fall back to text-only behavior.

## Mock Adapter Requirement

Before real runtime integration begins, Qantara should support a mock adapter that:

- accepts finalized text turns
- emits synthetic assistant text output
- optionally simulates delayed output
- optionally simulates missing cancel support

This mock adapter is required so M0 and M1 can proceed without binding to a real runtime.

## M0 Decision Target

This contract is good enough for M0 if:

- a mock adapter can implement it cleanly
- the custom gateway can call it without runtime-specific branches
- interruption semantics can be represented without transport leakage
