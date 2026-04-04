# M0 Experiments

## Purpose

This document turns M0 from a planning milestone into a concrete validation program.

M0 is not feature work. It is a short, decision-oriented set of experiments that should answer whether Qantara's current architecture is viable enough to move into implementation.

The experiments below are intentionally scoped to:

- a browser-first client
- raw PCM over WebSocket
- a custom async gateway as the primary architecture
- no binding to a specific local OpenClaw deployment yet

## Rules For M0

- Prefer thin experiments over polished implementation
- Measure actual latency and failure behavior, not just success cases
- Keep the runtime adapter mocked or abstract unless integration validation is explicitly started later
- Record findings in writing even when an experiment fails

## Experiment 1: Browser Audio Ingress

### Goal

Prove that a browser client can capture microphone audio and stream it to the gateway over WebSocket PCM with stable framing.

### Scope

- one browser client
- one gateway process
- PCM16 mono 16 kHz
- headset-first setup

### Tasks

- capture mic audio in the browser
- normalize or resample to the target format if needed
- stream frames over WebSocket to the gateway
- log frame cadence, byte counts, and disconnect behavior

### Success Criteria

- gateway receives audio frames continuously during speech
- frame timing is stable enough for downstream speech processing
- reconnect behavior is understood after socket interruption

### Artifacts

- short notes on frame size and cadence
- sample gateway log for a normal session
- list of browser-specific issues encountered

### Decision Unlocked

- confirms whether WebSocket PCM is good enough for M1 input transport

## Experiment 2: Browser Audio Egress

### Goal

Prove that the gateway can send streamed audio back to the browser and that browser playback can start and stop predictably.

### Scope

- gateway sends synthetic or pre-generated PCM audio
- browser plays it through a simple playback queue
- no TTS dependency required for the first pass

### Tasks

- implement gateway-to-browser audio frames
- implement browser playback queue
- test playback start, stop, and queue clear behavior
- record audible glitches, delays, or stale playback after stop

### Success Criteria

- playback begins reliably
- playback stops immediately when instructed
- queue behavior is predictable enough to support later barge-in work

### Artifacts

- notes on playback startup delay
- notes on stop/clear semantics
- list of browser playback edge cases

### Decision Unlocked

- confirms whether the browser playback path is adequate for M1 and M2

## Experiment 3: Custom Gateway Session Model

### Goal

Define the minimum session model the custom gateway must own before real speech or runtime integration is attempted.

### Scope

- single browser client
- single active session
- no downstream runtime binding required

### Tasks

- describe session lifecycle states
- define the minimum per-session fields
- define where cancellation tokens and playback state live
- define what events are emitted for UI and logging

### Success Criteria

- one written session model exists
- state transitions are explicit enough to guide implementation
- the design can support interruption without hand-wavy behavior

### Artifacts

- session state diagram or equivalent written state list
- per-session data structure outline
- event list for browser and gateway coordination

### Decision Unlocked

- confirms the custom gateway remains the right primary implementation path

## Experiment 4: Pipecat Reference Evaluation

### Goal

Evaluate whether Pipecat materially improves the path to a working prototype without forcing premature architectural coupling.

### Scope

- docs review plus at least one minimal implementation spike
- comparison against the same requirements used for the custom gateway

### Tasks

- map Qantara requirements onto Pipecat primitives
- identify what Pipecat handles well out of the box
- identify where Pipecat constrains Qantara's session or interruption model
- record whether Pipecat would be used as a prototype path only or deserves deeper adoption consideration

### Success Criteria

- Pipecat's value is stated concretely, not impressionistically
- comparison includes both benefits and lock-in risks
- a clear keep-or-bound decision is written down

### Artifacts

- short comparison table: custom gateway versus Pipecat
- list of capabilities Pipecat reduces implementation effort for
- list of Qantara concerns still better served by custom ownership

### Decision Unlocked

- confirms whether Pipecat stays as a reference path only

## Experiment 5: STT Candidate Selection

### Goal

Choose the first STT engine for M1 based on real implementation friction and latency, not just ecosystem reputation.

### Scope

- compare `faster-whisper` and `whisper.cpp`
- use the same short audio inputs where possible
- focus on local operation only

### Tasks

- document integration requirements for each candidate
- run a minimal transcription path for each candidate if possible
- record startup complexity, latency, and operational fit for a custom gateway

### Success Criteria

- one STT candidate is chosen for M1
- the fallback candidate is documented with a clear reason

### Artifacts

- comparison notes
- chosen baseline STT engine
- stated fallback option

### Decision Unlocked

- closes the first STT engine decision for M1

## Experiment 6: TTS Candidate Selection

### Goal

Choose the first TTS engine for M1 and M2 experimentation based on first-audio behavior and implementation fit.

### Scope

- compare `Piper` and `Kokoro`
- use short conversational outputs
- focus on local operation only

### Tasks

- document packaging and runtime requirements
- test first-audio delay where feasible
- record quality, simplicity, and likely interruption behavior

### Success Criteria

- one TTS candidate is chosen for first integration
- one alternate candidate is documented for follow-up comparison

### Artifacts

- comparison notes
- chosen baseline TTS engine
- alternate candidate with reason

### Decision Unlocked

- closes the first TTS engine decision for M1 and M2

## Experiment 7: First-Chunk TTS Rule

### Goal

Define the first buffering rule that Qantara will test before turning assistant text into speech.

### Scope

- no real downstream runtime needed
- use synthetic token or sentence streams

### Tasks

- compare at least two first-chunk rules
- estimate their effect on first-audio latency and coherence
- document which rule will be used first in M2

### Candidate Rules

- sentence-buffered first chunk
- punctuation-aware early chunking
- token-count fast path for first audio

### Success Criteria

- one initial chunking rule is chosen
- the downside of that rule is documented clearly

### Artifacts

- chosen first-chunk rule
- rejected alternatives and reasons

### Decision Unlocked

- closes the initial TTS chunking decision for implementation

## Experiment 8: Event Timeline Schema

### Goal

Define the minimum event timeline that every future implementation step must emit.

### Scope

- browser events
- gateway events
- speech pipeline events

### Required Events

- session start
- socket connected
- mic stream started
- speech start detected
- speech end detected
- final transcript ready
- downstream submit started
- first assistant output received
- first TTS chunk ready
- playback started
- interruption detected
- playback stopped
- session closed

### Success Criteria

- event names and timestamp fields are written down
- the custom gateway can emit placeholder versions of the minimum events
- the timeline is good enough to support M1 latency measurement

### Artifacts

- event schema
- one example session timeline

### Decision Unlocked

- confirms Qantara can measure progress rather than guessing

## M0 Output Package

M0 should produce a concrete output package, not just meeting notes.

Minimum expected outputs:

- one written session model
- one runtime adapter boundary draft
- one transport validation note
- one Pipecat comparison note
- one STT selection note
- one TTS selection note
- one initial TTS chunking decision
- one event timeline schema

## M0 Completion Gate

M0 is complete only when all of these are true:

- browser audio can move in both directions across the gateway
- WebSocket PCM remains acceptable for the headset-first MVP
- the custom gateway is still the preferred architecture
- one STT candidate and one TTS candidate are selected
- the initial TTS chunking rule is chosen
- the event timeline schema exists and is ready for implementation use
