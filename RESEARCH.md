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
