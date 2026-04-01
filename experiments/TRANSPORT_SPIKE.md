# Transport Spike

## Purpose

This spike is the first executable M0 experiment.

It should prove that a browser client and the custom gateway can exchange PCM audio over WebSocket in both directions with enough stability to justify M1 work.

This spike is not a production implementation. It is a tightly scoped validation slice.

## Scope

- one browser client
- one gateway process
- local LAN only
- headset-first setup
- raw PCM over WebSocket
- no real downstream runtime integration
- no STT or TTS dependency required for the first pass

## In Scope

- browser microphone capture
- WebSocket session bootstrap
- browser-to-gateway PCM streaming
- gateway-to-browser PCM streaming
- simple browser playback queue
- event timeline emission for transport events
- reconnect behavior notes

## Out Of Scope

- final STT pipeline
- final TTS pipeline
- runtime adapter implementation
- polished UI
- speaker-mode echo mitigation beyond basic notes

## Objective

Demonstrate four things:

1. browser mic audio can reach the gateway continuously
2. gateway audio can play in the browser predictably
3. stop and clear behavior is controllable enough for future barge-in work
4. the event timeline schema is usable in a real spike

## Proposed File Targets

Suggested first implementation targets:

- `client/transport-spike/`
- `gateway/transport_spike/`
- `experiments/notes/transport-spike.md`

Exact filenames can change, but the spike should stay isolated from future production code until the basic transport behavior is understood.

## Browser Requirements

- request microphone permission
- capture mono audio
- convert or resample to target PCM format if needed
- send small binary frames over WebSocket
- receive binary frames from the gateway
- play received PCM through a simple queue
- expose visible connection and playback state

## Gateway Requirements

- accept WebSocket connections
- assign session and connection identifiers
- log frame receipt and output events
- echo or stream synthetic audio back to the client
- emit placeholder timeline events using the shared schema
- support explicit playback clear or stop control messages

## Recommended First Pass

### Pass 1: One-Way Ingress

- browser captures mic audio
- gateway receives frames and logs them
- no playback yet

Success:

- stable inbound frame cadence is visible in logs

### Pass 2: One-Way Egress

- gateway sends synthetic PCM audio
- browser queues and plays it

Success:

- browser playback starts and ends predictably

### Pass 3: Two-Way Session

- browser sends mic frames
- gateway sends playback frames in the same session
- browser supports clear or stop control

Success:

- both directions work in one session without ambiguous state

## Suggested Transport Parameters

Initial defaults:

- input format: PCM16 mono 16 kHz
- output format: PCM16 mono 24 kHz or 16 kHz
- frame window target: 20 to 40 ms

These are starting points for the spike, not final locked values.

## Required Events

At minimum, the spike should emit:

- `session_created`
- `session_connected`
- `session_ready`
- `mic_stream_started`
- `input_audio_frame_received`
- `output_audio_frame_sent`
- `playback_started`
- `playback_stopped`
- `socket_disconnected`
- `session_closed`

## Questions To Answer

- Are browser audio APIs introducing immediate resampling or cadence issues?
- Is the chosen frame size practical for the custom gateway?
- Does browser playback queue behavior feel controllable enough for later interruption work?
- Does transport behavior already suggest WebRTC is needed sooner than expected?

## Exit Criteria

The transport spike succeeds if:

- browser-to-gateway audio works in a stable session
- gateway-to-browser audio works in a stable session
- the event timeline can be emitted without ambiguity
- no transport blocker is discovered that invalidates the WebSocket-first MVP decision

## Expected Output

The spike should end with:

- a short implementation note
- frame cadence observations
- playback observations
- reconnect observations
- a go or no-go statement for continuing with WebSocket into M1
