# Plan

## Project Summary

Qantara provides a hands-free, low-latency, LAN-only voice interaction layer for OpenClaw-compatible agent runtimes. The target experience is simultaneous listening and speaking, with barge-in support and local speech processing.

## Primary Architecture Decision

Build Qantara first as an external voice gateway that runs beside the downstream agent runtime.

Rationale:

- faster iteration on transport, speech, and interruption behavior
- narrower integration surface with the downstream runtime
- easier experimentation with local STT/TTS engines
- simpler replacement of speech backends without changing runtime internals

Defer an in-process OpenClaw plugin until the protocol, state machine, and cancellation semantics are stable.

The primary implementation path is a custom async gateway. Pipecat should still be evaluated in M0 as a comparison path and reference implementation, but it is not the default architecture.

## Product Requirements

- Full-duplex interaction: the client can keep listening while assistant audio is playing
- Barge-in: user speech can immediately interrupt assistant playback
- LAN-first operation with no required cloud speech dependency
- Low-latency turn handling with partial transcript visibility
- Safe execution boundaries for voice-triggered actions

## Initial Client Target

The initial client should be browser-first.

Why browser-first:

- easiest distribution model on a private LAN
- fastest way to validate microphone permissions, playback, captions, and reconnect behavior
- avoids prematurely binding the UX to a desktop packaging choice
- still leaves room for a later desktop wrapper if hardware access or background execution becomes important

Browser-first implications:

- WebAudio capture and playback path
- WebSocket session to the voice gateway
- headset-first validation in the earliest milestones
- text captions and session indicators built into the browser UI

## Suggested Runtime Stack

- Transport: raw PCM over WebSocket for the MVP
- Audio input format: PCM16 mono 16 kHz
- VAD: Silero VAD or WebRTC VAD
- STT candidates: faster-whisper or whisper.cpp streaming path
- TTS candidates: Piper, Kokoro, or equivalent local engines
- Concurrency model: async event loop with per-session state

WebRTC remains a later transport path if Qantara outgrows the limitations of a WebSocket-based headset-first MVP.

## Integration Boundary With The Downstream Runtime

Qantara should depend on the smallest practical set of downstream runtime capabilities:

- session create or resume
- finalized turn submission
- assistant output stream or polling equivalent
- turn cancellation or truncation path if available

If true generation cancellation is unavailable, Qantara must still support playback cancellation and interruption-aware history handling.

The exact runtime contract remains undecided. Qantara should not assume a specific local OpenClaw gateway, agent identifier, model route, or deployment profile until integration validation is intentionally started.

## Critical Unknowns To Resolve Early

- What assistant streaming contract is available from the chosen downstream runtime
- Whether generation cancellation exists and how reliable it is
- How interrupted assistant output should be represented in session history
- Whether headset-first deployment is required for the MVP
- What confirmation gate is needed for high-risk tools
- Which OpenClaw integration path, if any, should be adopted later
- What exact conditions should trigger migration from WebSocket PCM to WebRTC
- What first-chunk TTS rule best balances latency and speech coherence

## Phase 0: Technical Validation

Run explicit M0 experiments before feature implementation:

1. Transport experiment
   - prove browser mic capture to the custom gateway over WebSocket PCM
   - prove browser playback of streamed audio from the gateway
   - record whether headset-first use exposes any immediate media-layer blockers

2. Gateway shape experiment
   - define the runtime adapter boundary without binding to a specific local OpenClaw deployment
   - sketch the custom async gateway session model
   - evaluate Pipecat as a reference path against the same requirements

3. Speech stack experiment
   - compare first local STT candidates for latency and implementation friction
   - compare first local TTS candidates for first-audio speed and usability
   - define the initial TTS chunking rule to test

4. Observability experiment
   - define the voice event timeline schema
   - confirm that the gateway can emit timestamps for each major stage
   - define minimum measurements required before M1 starts

Exit criteria:

- Mic audio reaches gateway reliably
- A mock or adapter boundary exists for finalized turn submission and assistant output streaming
- Browser audio permission and reconnect flow are understood
- No assumptions about the eventual local OpenClaw agent topology are required to continue core gateway design
- The WebSocket transport is good enough for the first implementation milestone
- The custom gateway remains the preferred implementation path after comparison with Pipecat
- One STT candidate and one TTS candidate are selected for M1 work

## Phase 1: Full-Duplex Foundation

- Always-on microphone stream
- VAD-based speech start and endpoint detection
- Partial and final transcript pipeline
- Browser UI for text captions, session state, and response rendering
- Structured event timeline for latency and interruption analysis
- Single-user, single-session model

Exit criteria:

- Stable end-to-end voice input to assistant text output
- Reproducible latency measurements for first partial transcript and final turn submission
- Reliable reconnect behavior for one client session

## Phase 2: Spoken Response Path

- Local TTS integration
- Sentence-aware or chunk-aware assistant text buffering for speech
- Immediate playback stop on detected user speech
- Interruption markers and truncated assistant response policy
- Browser playback pipeline with jitter buffering and audible-state indicators

Exit criteria:

- Assistant audio starts quickly enough to feel conversational
- User speech can consistently stop playback
- Session history remains coherent after interruptions

## Phase 3: True Barge-In Semantics

- Model generation cancel or truncation path
- Distinguish soft barge-in from hard barge-in
- Tune endpointing for fast turn-taking
- Improve recovery logic for STT/TTS failures

Exit criteria:

- Assistant can be interrupted mid-response without corrupting session flow
- Cancel behavior is observable and traceable in logs
- Fallback to text-only response is reliable

## Phase 4: Hardening And Policy

- Confirmation gates for sensitive actions
- Local transcript and interruption audit logs
- Session metrics: first partial, first token, first audio, interruption rate
- LAN binding, token-based auth, and deployment defaults

Exit criteria:

- Operational telemetry is available per session
- Voice-triggered risky actions have explicit safety controls
- Deployment defaults are safe for a private network

## MVP Constraints

- Prefer headset-first usage in early testing
- Limit to one active speaker per session
- Avoid speakerphone mode until echo behavior is characterized
- Optimize for low latency before high-fidelity voice quality
- Keep the first client browser-only until the wire protocol and interaction model stabilize

## Success Metrics

- First partial transcript in a few hundred milliseconds on target hardware
- First audible assistant response under one second on a healthy LAN where possible
- Consistent interruption handling without ghost playback or duplicate turns
- Stable session recovery after temporary audio or websocket failure

## Integration Policy For Now

Qantara planning should remain runtime-agnostic enough to avoid coupling the project to your current local OpenClaw agents. The repo can capture candidate integration approaches and validation tasks, but it should not encode environment-specific hosts, tokens, model names, or agent IDs until that decision is made deliberately.
