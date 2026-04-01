# Project State

## Checkpoint

This document captures the current state of Qantara as of the latest planning and M0 transport-spike work.

This is a checkpoint document, not a long-term architecture spec.

## Current Stage

Qantara is in `M0: Technical Validation`.

The project has moved beyond planning-only status. It now includes:

- architecture and milestone documents
- a locked MVP transport decision
- a locked gateway direction
- a runnable browser-to-gateway transport spike
- a configurable adapter framework with mock and runtime-skeleton paths
- a validated first STT candidate path through faster-whisper
- a validated first TTS candidate path through Piper

## What Is Decided

These decisions are already locked in the repo:

- external voice gateway first
- browser-first client
- full-duplex conversation as the target UX
- headset-first MVP
- raw PCM over WebSocket for the MVP transport
- custom async gateway as the main implementation path
- Pipecat kept as an evaluation/reference path, not the default architecture

Source:

- [`DECISIONS.md`](/home/nawaf/Projects/Qantara/DECISIONS.md)

## What Exists Right Now

### Planning And Research

- [`PLAN.md`](/home/nawaf/Projects/Qantara/PLAN.md)
- [`ARCHITECTURE.md`](/home/nawaf/Projects/Qantara/ARCHITECTURE.md)
- [`MILESTONES.md`](/home/nawaf/Projects/Qantara/MILESTONES.md)
- [`RESEARCH.md`](/home/nawaf/Projects/Qantara/RESEARCH.md)
- [`M0_EXPERIMENTS.md`](/home/nawaf/Projects/Qantara/M0_EXPERIMENTS.md)

### Core M0 Architecture Artifacts

- gateway session model: [`gateway/SESSION_MODEL.md`](/home/nawaf/Projects/Qantara/gateway/SESSION_MODEL.md)
- runtime adapter contract: [`adapters/CONTRACT.md`](/home/nawaf/Projects/Qantara/adapters/CONTRACT.md)
- event timeline schema: [`schemas/EVENT_TIMELINE.md`](/home/nawaf/Projects/Qantara/schemas/EVENT_TIMELINE.md)

### Runnable M0 Spike

- spike spec: [`experiments/TRANSPORT_SPIKE.md`](/home/nawaf/Projects/Qantara/experiments/TRANSPORT_SPIKE.md)
- spike runbook: [`experiments/RUN_TRANSPORT_SPIKE.md`](/home/nawaf/Projects/Qantara/experiments/RUN_TRANSPORT_SPIKE.md)
- browser client: [`client/transport-spike/index.html`](/home/nawaf/Projects/Qantara/client/transport-spike/index.html)
- gateway server: [`gateway/transport_spike/server.py`](/home/nawaf/Projects/Qantara/gateway/transport_spike/server.py)
- adapter base types: [`adapters/base.py`](/home/nawaf/Projects/Qantara/adapters/base.py)
- adapter factory: [`adapters/factory.py`](/home/nawaf/Projects/Qantara/adapters/factory.py)
- mock adapter: [`adapters/mock_adapter.py`](/home/nawaf/Projects/Qantara/adapters/mock_adapter.py)
- runtime skeleton adapter: [`adapters/runtime_skeleton.py`](/home/nawaf/Projects/Qantara/adapters/runtime_skeleton.py)
- optional Piper path: [`gateway/transport_spike/tts_piper.py`](/home/nawaf/Projects/Qantara/gateway/transport_spike/tts_piper.py)
- validated first STT path: [`gateway/transport_spike/stt_faster_whisper.py`](/home/nawaf/Projects/Qantara/gateway/transport_spike/stt_faster_whisper.py)
- run notes template: [`experiments/notes/transport-spike.md`](/home/nawaf/Projects/Qantara/experiments/notes/transport-spike.md)

## What The Current Spike Can Do

The current runnable spike can:

- serve a browser client from the gateway process
- open a browser WebSocket session to the gateway
- capture microphone audio in the browser
- stream PCM16 audio frames from browser to gateway
- send PCM16 audio frames from gateway to browser
- play returned PCM audio in the browser
- emit basic browser-side VAD state changes using an RMS threshold
- request transcription of the recent audio buffer through a working faster-whisper path
- select a downstream adapter by configuration
- submit text turns through either the mock adapter or runtime skeleton adapter
- stream assistant text back to the browser through the configured adapter
- optionally synthesize assistant text through Piper when configured
- fall back to a synthetic tone path when Piper is unavailable

## What The Current Spike Does Not Do Yet

The current spike does not yet provide:

- validated real STT behavior from actual local runs
- a real adapter framework path that stays decoupled from the user's current local agents
- real endpointing logic beyond simple browser-side VAD hints
- real downstream runtime integration
- robust barge-in semantics across active generation
- production-ready playback buffering
- speaker-mode echo mitigation
- persisted metrics or experiment notes from actual test runs

## What Has Been Validated

Validated by implementation:

- the project can support a runtime-agnostic gateway shape
- the repo structure is now aligned with the planned architecture
- the Python gateway spike compiles successfully
- the transport spike is runnable from a single process

Validated by actual testing:

- browser mic capture works through the current HTTPS spike path
- WebSocket/WSS transport is working for the current M0 slice
- faster-whisper is functioning as the first real STT candidate in this environment
- the Piper runtime and first local voice model now synthesize successfully on this machine
- Piper playback through the browser spike is working on the current secure LAN path

Not yet validated by actual experiment results:

- whether the browser VAD threshold is tuned well enough for ongoing use

That distinction matters. The repo contains a runnable validation slice, but M0 is not complete until those runs are executed and recorded.

## How To Run The Current Spike

Primary reference:

- [`experiments/RUN_TRANSPORT_SPIKE.md`](/home/nawaf/Projects/Qantara/experiments/RUN_TRANSPORT_SPIKE.md)

Short version:

```bash
pip install -r gateway/transport_spike/requirements.txt
python3 gateway/transport_spike/server.py
```

Then open:

```text
http://127.0.0.1:8765/spike
```

Optional Piper setup:

```bash
export QANTARA_PIPER_MODEL=/absolute/path/to/voice.onnx
```

If you place the current test voice model at:

```text
models/piper/en_US-lessac-medium.onnx
```

the spike will auto-detect it without an environment variable.

Optional faster-whisper setup:

```bash
export QANTARA_WHISPER_MODEL=base.en
```

If the default port is already occupied, run the spike on another local port:

```bash
QANTARA_SPIKE_PORT=8899 ./.venv/bin/python gateway/transport_spike/server.py
```

To expose the spike to other devices on the LAN:

```bash
QANTARA_SPIKE_HOST=0.0.0.0 QANTARA_SPIKE_PORT=8899 ./.venv/bin/python gateway/transport_spike/server.py
```

## Current Risk Areas

The main unresolved technical risks are:

- VAD threshold quality and false positives
- first-audio latency for Piper under repeated runs, currently around `1.7s`
- missing real interruption and cancellation behavior

## Definition Of A Good M0 State

Qantara reaches a good M0 state when:

- the transport spike has been run and documented
- transport notes are recorded in the run notes file
- one STT candidate is selected
- one TTS candidate is selected
- the first-chunk TTS rule is chosen
- the custom gateway still looks better than adopting Pipecat as the primary architecture

## Immediate Next Steps

The highest-value next steps are:

1. Reduce Piper first-audio latency from the current ~`1.7s` baseline if possible.
2. Tune VAD threshold and transport framing from actual results.
3. Replace the runtime skeleton adapter with the first concrete backend adapter when the target runtime contract is chosen.
4. Keep backend playback-stop telemetry distinct from user-perceived audible stop timing.

## Repository Interpretation

This repository is now in a healthy early state:

- not just planning
- not yet product implementation
- already structured enough to validate the architecture honestly

That is the correct state for Qantara right now.
