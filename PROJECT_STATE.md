# Project State

Version: `0.1.0-alpha.1`

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
- a validated session-oriented adapter path through a local fake backend
- a validated endpoint-ready speech submission path

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
- session-oriented HTTP adapter: [`adapters/session_gateway_http.py`](/home/nawaf/Projects/Qantara/adapters/session_gateway_http.py)
- session gateway contract: [`SESSION_GATEWAY_CONTRACT.md`](/home/nawaf/Projects/Qantara/SESSION_GATEWAY_CONTRACT.md)
- local fake session backend: [`gateway/fake_session_backend/server.py`](/home/nawaf/Projects/Qantara/gateway/fake_session_backend/server.py)
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
- mark endpoint-ready after stable silence in the browser
- submit recent speech through the endpoint-ready flow
- select a downstream adapter by configuration
- submit text turns through the selected adapter
- stream assistant text back to the browser through the configured adapter
- optionally synthesize assistant text through Piper when configured
- fall back to a synthetic tone path when Piper is unavailable

## What The Current Spike Does Not Do Yet

The current spike does not yet provide:

- real downstream runtime integration
- ~~robust barge-in semantics across active generation~~ Done on `explore/hands-free-speed`
- production-ready playback buffering
- speaker-mode echo mitigation
- ~~persisted metrics or experiment notes from actual test runs~~ Done on `explore/hands-free-speed`

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
- end-to-end cancellation is working across browser, gateway, HTTP adapter, and fake backend
- endpoint-ready plus submit-recent-speech is working across browser, gateway, STT, HTTP adapter, and fake backend

Validated on `explore/hands-free-speed` branch:

- piper-onnx in-process ONNX inference: 66-153ms first-chunk (vs 1500ms baseline)
- barge-in: cancel active turn on speech detection during playback
- auto-submit: endpoint-ready triggers automatic speech submission
- VAD EMA smoothing: no false positives in simulation tests
- AudioWorklet mic capture with ScriptProcessor fallback
- 38 automated tests (33 unit + 5 integration) all passing
- end-to-end WebSocket turn submission through gateway to fake backend

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
- first-audio latency for Piper under repeated runs, currently around `1.5s` for the first spoken chunk after early chunking
- the absence of a real backend target beyond the fake validation backend
- occasional socket disconnects that still need characterization

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

1. ~~Auto-submit endpoint-ready speech instead of requiring the submit button.~~ Done on `explore/hands-free-speed`.
2. ~~Tune VAD threshold and endpoint timing from actual results.~~ Done on `explore/hands-free-speed`.
3. Replace the fake backend with the first real session-oriented backend target when it is chosen.
4. Keep backend playback-stop telemetry distinct from user-perceived audible stop timing.
5. ~~Validate streaming TTS latency improvement with real runs and record numbers.~~ Done: persistent subprocess drops first-chunk from ~1500ms to ~50-190ms.
6. ~~Evaluate whether Piper streaming latency is good enough or if an alternative TTS engine is needed.~~ At ~50-190ms first-chunk, Piper is fast enough. No alternative needed.

## Repository Interpretation

This repository is now in a healthy early state:

- not just planning
- not yet product implementation
- already structured enough to validate the architecture honestly

That is the correct state for Qantara right now.
