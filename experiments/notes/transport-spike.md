# Transport Spike Notes

## Session

- Date: 2026-04-01
- Browser: LAN browser session over HTTPS
- Headset used: yes

## Update

- Date: 2026-04-04
- Browser: LAN browser session over HTTPS
- Headset used: no
- current active backend under test:
  - OpenClaw session bridge
  - target agent: `spectra`
  - agent model: `openai-codex/gpt-5.4-mini`
- audio mode under test:
  - `Speakers`
- current gateway focus:
  - OpenClaw-backed real-agent validation
  - speaker-mode stability
  - barge-in behavior
  - post-playback re-entry control
  - avatar and presence-layer experimentation

## Observations

### Ingress

- frame cadence: mic capture ran successfully and recent-audio buffer reached roughly 96000 samples during testing
- resampling issues: none explicitly observed from the browser logs yet
- disconnect behavior: connection established successfully after HTTPS, WSS, and port fixes
- endpointing behavior: browser-side endpoint-ready fired successfully after `700 ms` silence and now supports auto-submit of recent speech
- current limitation: fragmented follow-ups can still happen when STT breaks an utterance across pauses
- real backend path: validated against an Ollama-backed session backend using the same HTTP contract
- OpenClaw path: validated against a real OpenClaw agent through the same HTTP contract shape
- current status after recent tuning:
  - auto-submit overlap is improved by browser-side active-turn and playback gating
  - some weak or low-value speech fragments are now skipped before STT submission
  - browser-side barge-in now clears playback through the gateway
  - browser-side audio mode now distinguishes `Headset` and `Speakers`
  - `Speakers` mode adds stricter playback-time speech detection and a longer post-playback cooldown
  - browser-side avatar presets, voice presets, and speech-speed control do not break the transport loop
  - current open question is how much residual speaker leakage still survives the heuristic speaker-mode guard
- disconnect characterization:
  - recent browser disconnects are clean closes (`code=1000`), not transport crashes

### Egress

- playback startup delay: early chunking reduced first spoken chunk timing to roughly `1.50s` to `1.52s`, with later chunk playback around `1.65s` to `1.67s`
- queue behavior: basic playback path is working
- clear or stop behavior: local browser playback stop now feels immediate; measured local clear acknowledgement reached `1 ms` on the latest run
- end-to-end cancel path: validated through the session-oriented HTTP adapter and fake backend, with `cancel status: {"status":"acknowledged"}` and local playback stop measured at `27 ms`
- current speaker-mode result:
  - intentional interruption works
  - accidental immediate post-playback triggers appear reduced versus earlier runs
- current OpenClaw bridge result:
  - real agent conversation works end to end
  - cancellation noise is improved after process-group kill handling
  - shared-session cross-talk risk is reduced by resetting the shared OpenClaw session when switching HTTP sessions

### Transport Decision

- WebSocket remains acceptable for M1: yes, provisionally
- Reasons:
  browser session connected successfully over the current spike path
  microphone capture worked
  mock adapter text streaming worked
  playback path worked

### STT

- faster-whisper available: yes
- transcription result quality: working and returned repeated spoken text correctly during testing
- endpoint-driven transcription result: working; recent speech `"Hello, is it me you're looking for?"` transcribed successfully and submitted as a turn
- transcription latency feel: acceptable for the current M0 spike
- current result: first validated STT candidate

### TTS

- Piper runtime available: yes
- local voice model installed: `models/piper/en_US-lessac-medium.onnx`
- direct synthesis outside the browser spike: working
- browser-path TTS status: `piper`
- browser-path playback result: working on mock turn
- first-audio feel through browser playback: acceptable as an M0 baseline, but still too slow for the eventual target UX
- fallback tone used: yes, during the earlier pre-Piper runs
- current result: first validated TTS candidate
- real backend speaking result: working; multi-turn voice interaction now works through the Ollama-backed backend
- OpenClaw agent speaking result: working; multi-turn voice interaction now works through `spectra`
- recent local baseline:
  - first-audio commonly around `1.4s` to `1.6s`
  - occasional outliers still appear above `2.0s`

### Follow-Ups

- keep validating the current `Speakers` mode in real speaker-plus-mic runs
- keep validating the OpenClaw-backed `spectra` path under real voice interaction
- extend deterministic handling only for recurring real STT variants seen in logs
- keep validating whether the current weak-speech filter is rejecting too much soft speech
- keep backend playback-stop telemetry separate from user-perceived audible stop timing
- keep the gateway layer runtime-agnostic while using `spectra` as the current real-agent validation target
- Phase 1 identity follow-up:
  - replace hardcoded avatar presets with descriptor-driven presets
  - add true backend `voice_id` support once more Piper voices are available
