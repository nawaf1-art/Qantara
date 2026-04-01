# Backend Adapter Targets

## Purpose

This document narrows the next Qantara decision from "some real backend later" to a small set of concrete adapter target shapes.

It does not bind Qantara to the user's current local OpenClaw agents.

## What Qantara Needs From A Backend

The first concrete backend target must support, or plausibly evolve toward:

- session start or resume
- finalized text turn submission
- assistant output streaming or chunked polling
- basic health signaling
- optional cancel or truncate later

Qantara does not need the backend to own:

- browser transport
- microphone state
- playback state
- TTS buffering policy
- local interruption semantics at the audio layer

## Candidate A: Stateless Chat Endpoint

Shape:

- submit a full message history or compact prompt
- receive streaming or final assistant text
- no durable backend session concept required

Examples:

- OpenAI-compatible `chat.completions`
- generic `responses` or chat endpoint
- a minimal local HTTP backend that only accepts text turns

Strengths:

- easiest first concrete integration
- narrowest implementation surface
- backend-agnostic
- easiest to test in isolation

Weaknesses:

- Qantara must own more conversation-state assembly
- cancellation support may be weak or backend-specific
- tool activity observability may be limited
- session continuity becomes Qantara's responsibility unless the backend adds its own session layer

Fit For Qantara:

- good as a first proof of a real adapter path
- not ideal if the long-term target is an agent runtime with richer state and tools

## Candidate B: Session-Oriented Agent Gateway

Shape:

- create or resume a backend session
- submit a user turn into that session
- stream assistant output events tied to the session or turn
- optional cancel or truncate on active turn

Examples:

- OpenClaw-compatible session/chat contract
- Live agent session APIs
- custom runtime gateway with explicit session handles

Strengths:

- best conceptual match for Qantara's architecture
- clean ownership boundary between voice gateway and agent runtime
- easiest path to interruption metadata, turn IDs, and later tool observability
- preserves backend ownership of agent/session state

Weaknesses:

- requires a more deliberate contract than a plain chat endpoint
- fewer generic backends expose this cleanly out of the box
- cancellation semantics still vary across implementations

Fit For Qantara:

- best long-term target
- best match for the current adapter contract
- recommended primary direction

## Candidate C: Realtime Duplex Model Session

Shape:

- backend itself is a realtime session
- text/audio and interruption events flow bidirectionally
- backend may produce audio directly

Examples:

- OpenAI Realtime-style session model
- media-centric agent session stacks

Strengths:

- best for low-latency native duplex interaction
- often includes stronger interruption semantics
- may reduce glue code in some stacks

Weaknesses:

- overlaps with Qantara's own responsibilities
- risks collapsing the gateway/backend boundary
- can make Qantara less backend-agnostic
- pulls transport and media concerns downward into the runtime choice

Fit For Qantara:

- not the right first concrete backend target
- worth studying later, but not for the current adapter path

## Recommendation

Qantara should target `Candidate B: Session-Oriented Agent Gateway` as the primary backend shape.

Reason:

- it matches the existing adapter contract directly
- it keeps Qantara as a voice channel layer instead of turning it into a generic chat-state manager
- it preserves the option to bind to an OpenClaw-compatible runtime later without rewriting the gateway boundary

## Implementation Strategy

Do this in two stages.

### Stage 1: Runtime Skeleton Adapter

Current state:

- already implemented
- exercises adapter selection, health reporting, and non-mock control flow
- still does not bind to a real backend

### Stage 2: Session-Oriented Backend Adapter

Implement the first concrete adapter behind this shape:

- `start_or_resume_session`
- `submit_user_turn`
- `stream_assistant_output`
- `check_health`
- `cancel_turn` as supported or explicitly degraded

The first concrete backend adapter should remain:

- config-driven
- replaceable
- independent of the user's current local agent topology

## What Not To Do Next

- do not bind directly to a specific local OpenClaw agent instance yet
- do not bypass the adapter framework with one-off gateway integration code
- do not switch Qantara into a backend-owned realtime media architecture yet

## Decision Update

This review resolves the practical direction of `D-007` enough to proceed:

- Qantara should implement its first concrete backend adapter as a `session-oriented agent gateway` shape
- the exact backend product or deployment remains open
