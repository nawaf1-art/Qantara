# Research

## Purpose

This document captures external systems and projects that are relevant to Qantara's design.

The goal is not to copy another system wholesale. The goal is to identify proven patterns for:

- full-duplex browser voice interaction
- barge-in and interruption handling
- local or self-hosted STT and TTS pipelines
- transport choices for low-latency LAN use
- clean separation between voice gateway and downstream agent runtime

Qantara remains intentionally decoupled from any specific local OpenClaw deployment at this stage.

## What Qantara Is Looking For

The most relevant external references are systems that help answer one or more of these questions:

1. Should the client-to-gateway transport start with WebSocket PCM or WebRTC?
2. Should the gateway be custom-built or use an orchestration framework?
3. What local STT and TTS engines are strong first candidates?
4. How should barge-in, cancellation, and interruption-aware history be modeled?
5. What browser-side patterns are effective for VAD, playback, and reconnect handling?

## Primary References

### Pipecat

Why it matters:

- closest match to Qantara's external voice gateway shape
- built specifically for real-time voice and multimodal conversational systems
- supports both WebSocket and WebRTC transport paths
- supports multiple STT and TTS providers and engines

What to study:

- how Pipecat models voice pipelines
- how transports differ between browser-facing and server-facing flows
- whether the framework helps enough to justify the dependency cost

What it can answer for Qantara:

- whether a framework can accelerate M0 and M1
- how to structure the gateway pipeline
- how interruption and streaming can be composed cleanly

Sources:

- https://docs.pipecat.ai/guides/learn/transports
- https://docs.pipecat.ai/server/services/transport/small-webrtc
- https://docs.pipecat.ai/server/services/transport/websocket-server
- https://github.com/pipecat-ai/pipecat
- https://github.com/pipecat-ai/pipecat-examples
- https://github.com/pipecat-ai/voice-ui-kit

### Home Assistant Assist And Wyoming

Why it matters:

- strongest example of a modular local voice architecture
- separates satellites, speech services, and orchestration cleanly
- demonstrates a mature event-driven voice pipeline in a self-hosted ecosystem

What to study:

- pipeline event boundaries
- remote voice endpoint patterns
- protocol separation between audio edge devices and central processing

What it can answer for Qantara:

- how to isolate transport from speech services
- how to think about remote clients and modular services
- how to shape a durable internal protocol even if the first version is simple

Sources:

- https://developers.home-assistant.io/docs/voice/pipelines/
- https://developers.home-assistant.io/docs/core/entity/assist-satellite/
- https://github.com/rhasspy/wyoming

### LiveKit Agents

Why it matters:

- strong reference for production-grade real-time media systems
- highly relevant if Qantara grows beyond a lightweight LAN gateway
- WebRTC-first thinking is useful even if Qantara starts with WebSocket

What to study:

- real-time media transport patterns
- agent/session orchestration around voice
- where a heavier media stack becomes worthwhile

What it can answer for Qantara:

- whether a lightweight custom LAN gateway will remain sufficient
- what observability and transport concerns emerge as complexity increases

Sources:

- https://docs.livekit.io/agents/
- https://github.com/livekit/agents

## Secondary References

### Vocode

Why it matters:

- useful for conversation mechanics, turn-taking, and streaming behavior
- less aligned with a local LAN-first architecture than Pipecat or Wyoming

What to study:

- endpointing and transcript flow
- handling conversational timing and agent responses

Sources:

- https://docs.vocode.dev/
- https://docs.vocode.dev/open-source/conversation-mechanics
- https://docs.vocode.dev/open-source/local-conversation

### LLMRTC

Why it matters:

- useful for conceptual guidance around provider-agnostic real-time communication
- relevant mainly for transport/session design thinking

What to study:

- connection lifecycle
- abstraction boundaries for real-time providers

Sources:

- https://www.llmrtc.org/web-client/connection-lifecycle
- https://www.llmrtc.org/concepts/providers

## Component References

### Browser-Side VAD

Primary candidate:

- `@ricky0123/vad`

Why it matters:

- browser-native VAD patterns are directly relevant to Qantara's browser-first client
- useful for understanding speech start and end semantics in the client

Source:

- https://github.com/ricky0123/vad

### STT Candidates

Primary candidates:

- `faster-whisper`
- `whisper.cpp`

Why they matter:

- both are credible local STT paths
- they differ in deployment profile, ecosystem maturity, and control surface

Sources:

- https://github.com/SYSTRAN/faster-whisper
- https://github.com/ggml-org/whisper.cpp

### TTS Candidates

Primary candidates:

- `Piper`
- `Kokoro`

Why they matter:

- both are frequently mentioned as practical local TTS options
- they represent different tradeoffs between speed, quality, and packaging complexity

Important note:

- candidate status only; do not lock either into the architecture until validated in Qantara's target conditions

## What To Ignore Or Treat Carefully

- full assistant platforms that solve a different problem, especially home automation-first systems used as direct product templates
- archived or deprecated repos as core dependencies
- telephony-first architectures when Qantara is focused on browser and LAN interaction
- demos that show voice UX but hide the difficult parts of interruption, cancellation, or session state

## Current Qantara Conclusions

At this stage, the research supports these conclusions:

- Qantara should remain an external voice gateway
- browser-first remains a good first client strategy
- the biggest unresolved architecture choice is still `WebSocket first` versus `WebRTC first`
- `Pipecat` is worth evaluating seriously, but not adopting by assumption
- `Home Assistant Assist` and `Wyoming` are valuable more for protocol and modularity lessons than direct implementation reuse
- `LiveKit Agents` is strategically relevant if the project expands beyond a lightweight LAN gateway

## Focused Comparisons

### 1. WebSocket PCM Versus WebRTC

#### WebSocket PCM

Strengths:

- easiest transport to prototype and debug
- fits a browser-first LAN MVP with a thin custom client
- keeps signaling and server logic simple
- works well on controlled local networks

Weaknesses:

- no built-in media-layer echo cancellation
- less robust handling for real-time media edge cases
- fewer built-in transport diagnostics than WebRTC
- likely to need more custom logic for jitter, timing, and media behavior

When it fits Qantara:

- M0 and M1
- headset-first usage
- one client, one session, controlled LAN conditions

#### WebRTC

Strengths:

- purpose-built for real-time bidirectional media
- browser ecosystem already supports media-oriented features and stats
- much better fit for full-duplex audio and echo-sensitive interaction
- stronger long-term path if Qantara becomes a serious realtime voice product

Weaknesses:

- more moving parts
- signaling and session setup are more complex
- can be unnecessary overhead for the earliest local prototype

When it fits Qantara:

- once speaker-mode or non-headset use becomes important
- if barge-in reliability becomes limited by media behavior rather than gateway logic
- if Qantara starts needing more robust client-facing real-time media handling

Recommendation:

- start with `WebSocket PCM` for the headset-first LAN MVP
- treat `WebRTC` as the planned upgrade path, not as a rejected option
- keep the gateway transport abstraction clean enough to swap later

Why:

- Pipecat explicitly positions WebSocket transports as suitable for prototyping and controlled environments, while recommending WebRTC-based transports for production client/server applications
- LiveKit treats WebRTC as the core transport for real-time media and agent frontends
- MDN confirms browser-level echo cancellation support, but Qantara should not assume that alone solves full-duplex speaker-mode voice UX

### 2. Pipecat Versus Custom Gateway

#### Pipecat

Strengths:

- closest framework match to Qantara's intended pipeline
- already models transports, STT, TTS, frames, and client SDKs
- likely the fastest path to a serious prototype
- reduces integration glue for supported components

Weaknesses:

- introduces framework coupling
- may constrain how Qantara wants to model interruptions and runtime boundaries
- can hide complexity at first and then force adaptation later

Best use for Qantara:

- evaluation prototype
- reference implementation
- fast exploration of transport and audio orchestration choices

#### Custom Gateway

Strengths:

- full control over session model, cancellation semantics, and runtime adapter contract
- smallest dependency surface
- easier to keep architecture aligned with Qantara's exact needs

Weaknesses:

- more engineering work up front
- more transport and media details must be implemented directly
- slower route to the first working end-to-end demo

Best use for Qantara:

- long-term core architecture if Qantara needs strict control and a narrow runtime boundary

Recommendation:

- do not commit the production architecture to Pipecat yet
- evaluate Pipecat in M0 as a comparison path
- keep the core project architecture based on a `custom gateway with optional framework-assisted prototype`

Why:

- Pipecat is highly relevant, but Qantara's biggest hard problems are not just pipeline wiring. They are interruption semantics, adapter boundaries, and long-term control of the session model.

### 3. Piper Versus Kokoro Versus Other Local TTS

#### Piper

Strengths:

- lightweight local deployment
- fast and practical for low-latency self-hosted use
- simple fit for an MVP

Weaknesses:

- official `rhasspy/piper` repo is archived
- voice quality is good enough for many cases but not likely the ceiling
- ecosystem direction should be treated cautiously because of repo movement

Best use for Qantara:

- latency-first baseline
- dependable first offline TTS benchmark

#### Kokoro

Strengths:

- unusually strong quality-to-size profile
- open-weight model with Apache-licensed weights
- attractive candidate when user experience quality matters early

Weaknesses:

- packaging and runtime path may be less minimal than Piper
- real operational latency must be validated in Qantara's target setup
- the ecosystem is moving quickly, so implementation choices may shift

Best use for Qantara:

- quality-first candidate for the first serious conversational demo

#### Other Local TTS

Notable alternative:

- `Coqui XTTS`

Why it matters:

- supports streaming inference and voice cloning
- stronger feature set in some scenarios than the simpler local engines

Why it is not the first default for Qantara:

- heavier than Qantara needs for the first headset-first LAN MVP
- voice cloning is not part of the current project goal

Recommendation:

- benchmark `Piper` and `Kokoro` first under identical local conditions
- keep `XTTS` as a secondary option if voice quality or feature needs exceed what those two provide

Provisional conclusion:

- `Piper` is the safer first latency baseline
- `Kokoro` is the stronger first quality candidate
- Qantara should not lock either choice until first-audio timing and interruption behavior are measured locally

### 4. faster-whisper Versus whisper.cpp

#### faster-whisper

Strengths:

- strong performance on modern GPU and CPU paths
- mature Python integration surface
- practical default choice for a Python-based gateway
- supports VAD filtering and batched inference

Weaknesses:

- more Python-centric than whisper.cpp
- deployment details depend more on Python packaging and CUDA library alignment

Best use for Qantara:

- leading STT candidate for a Python gateway
- fast M0 and M1 development

#### whisper.cpp

Strengths:

- lightweight C/C++ implementation
- broad portability across CPU-first and edge-like environments
- strong option for systems that want low dependency overhead
- includes real-time microphone example and many platform targets

Weaknesses:

- lower-level integration path than faster-whisper in a Python-heavy stack
- Qantara would likely need more glue around streaming and orchestration

Best use for Qantara:

- fallback or alternative if Python packaging, CUDA setup, or deployment constraints become painful
- future option if Qantara wants a leaner runtime core

Recommendation:

- start with `faster-whisper`
- keep `whisper.cpp` as the fallback and control-first alternative

Why:

- Qantara is already architecturally closer to a Python async gateway than a low-level native audio application
- faster-whisper appears to offer the best path to a fast prototype without giving up local deployment

## Working Recommendations

If Qantara started implementation tomorrow, the research currently points to this stack:

- transport: `WebSocket PCM` first, designed to allow later WebRTC migration
- gateway: `custom async gateway`, with `Pipecat` evaluated in parallel as a reference path
- browser VAD: `@ricky0123/vad`
- STT first candidate: `faster-whisper`
- STT fallback: `whisper.cpp`
- TTS first benchmark pair: `Piper` and `Kokoro`

This is not yet a final architecture lock. It is the most defensible starting point based on current research.

## Recommended Reading Order

1. Pipecat transport guidance and examples
2. Home Assistant voice pipeline and Wyoming protocol
3. Browser VAD reference
4. STT engine comparison between faster-whisper and whisper.cpp
5. LiveKit Agents only if Qantara starts leaning toward a heavier real-time media architecture

## Research Tasks To Add Later

- Compare WebSocket PCM versus WebRTC specifically for Qantara's headset-first MVP
- Compare custom gateway versus Pipecat-backed prototype
- Compare first local TTS candidates under identical latency and quality tests
- Define the minimum downstream runtime adapter contract before runtime-specific integration begins
