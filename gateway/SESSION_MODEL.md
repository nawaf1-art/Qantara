# Session Model

This document describes the current gateway session model. The implementation is in [`gateway/transport_spike/runtime.py`](transport_spike/runtime.py); browser and adapter event semantics are defined in [`protocols/agent.md`](../protocols/agent.md).

## Ownership

The gateway owns connection lifecycle, audio buffers, endpointing, playback, interruption, adapter turn coordination, bounded timelines/transcripts, and continuity snapshots. A backend adapter owns its opaque runtime session and turn handles. The browser owns permissions, capture, playback queues, and presentation.

Qantara does not provide a durable conversation database. Continuity state is bounded in memory and expires.

## Identity

An active connection has a gateway `session_id`. The browser can also provide a stable `client_session_id` so selected voice/translation preferences and a compatible backend session handle can be resumed after reconnect.

A reconnect creates a new active gateway session. A stored backend handle is reused only when the snapshot belongs to the same backend binding; changing the configured backend invalidates that mapping.

## Client-visible states

The implemented public state vocabulary is:

| State | Meaning |
|---|---|
| `idle` | Session exists without an active voice turn |
| `listening` | Microphone input is accepted and the gateway is waiting for or collecting speech |
| `thinking` | A finalized user turn is being accepted or processed by the backend |
| `speaking` | Assistant output is being synthesized, queued, or played |
| `interrupted` | Playback/generation handling was interrupted before returning to listening |

Internal tasks and event details are richer than this five-state UI vocabulary. New UI states must not be invented by adapters.

## Turn lifecycle

A normal voice turn is:

```text
listening
  -> speech detected and buffered
  -> endpoint accepted
  -> STT final transcript
  -> thinking
  -> adapter session start/resume
  -> user turn submission
  -> assistant event stream
  -> TTS/playback
  -> speaking
  -> listening
```

Audio for one utterance is buffered from speech onset (plus 400 ms of pre-roll) until the turn is submitted, capped at `QANTARA_MAX_UTTERANCE_MS` (30 s by default), and the whole utterance goes to STT. A pause shorter than about 2 s continues the same utterance.

Each turn owns its cancellation. The first cancel request claims the turn synchronously, stops its output (queued speech is cancelled), and schedules the teardown: the `interrupted` state, one `turn_interrupted`, the adapter cancel and at most one `cancel_status`, then a force-cancel of the in-flight task after the configured grace period if the adapter does not cooperate. Further cancel requests for the same turn are no-ops. After a cancel the gateway sends and records no more assistant text for that turn; the transcript keeps only text already queued for speech, marked `interrupted`. A barge-in that lands while the backend session is still starting prevents the turn from being submitted. Late output from a cancelled or superseded turn must not become a second terminal result.

Adapter failures are visible: an exception while starting the session, submitting, or streaming produces a `recoverable_error` timeline event and a `turn_failed` message to the client (with `failure_kind` and `retriable`). A session-start or submit failure first drops the stored backend session handle and retries once. When a turn ends while the user is already speaking again, the session reports `listening`.

Playback audio is paced against an absolute schedule, at most 250 ms ahead of real time, and the next sentence is synthesized while the current one plays.

## Backend bindings

Each active session references a backend binding containing the public backend type, adapter configuration, adapter instance, sanitized endpoint metadata, health, and optional managed-bridge process.

Runtime reconfiguration creates a new default binding. Existing references are retained only while active sessions or resumable snapshots need them; unreferenced bindings and managed bridges are cleaned up.

## Bounded state

Current defaults include:

- at most 64 simultaneous WebSocket connections
- at most 256 resumable session snapshots
- at most 200 timeline items per session
- at most 80 transcript items per session

The configuration reference lists the environment variables that change supported ceilings. Bounds are deployment controls, not a durable retention promise.

## Snapshot contents

A resumable snapshot can retain:

- client session id and backend binding id
- compatible runtime session handle
- selected/requested voice and speech rate
- pitch, tone, and expressiveness preferences
- primary language and translation settings
- client label and last-update time

Per-turn input language is not restored because it is detected or selected for each new turn.

## Observability and privacy

Session control payloads expose operational state and counters. Transcript and timeline control endpoints are authenticated when auth is configured and remain bounded in memory. Default logs redact free-form speech/model/tool content and credentials.

The planned lifecycle consolidation work is documented separately in [`docs/architecture/TURN_LIFECYCLE_HARDENING_PLAN.md`](../docs/architecture/TURN_LIFECYCLE_HARDENING_PLAN.md); that plan does not redefine current shipped behavior.
