# Transport Spike Notes

## Session

- Date: 2026-04-01
- Browser: LAN browser session over HTTPS
- Headset used: yes

## Observations

### Ingress

- frame cadence: mic capture ran successfully and recent-audio buffer reached roughly 96000 samples during testing
- resampling issues: none explicitly observed from the browser logs yet
- disconnect behavior: connection established successfully after HTTPS, WSS, and port fixes
- endpointing behavior: browser-side endpoint-ready fired successfully after `700 ms` silence and now supports auto-submit of recent speech

### Egress

- playback startup delay: early chunking reduced first spoken chunk timing to roughly `1.50s` to `1.52s`, with later chunk playback around `1.65s` to `1.67s`
- queue behavior: basic playback path is working
- clear or stop behavior: local browser playback stop now feels immediate; measured local clear acknowledgement reached `1 ms` on the latest run
- end-to-end cancel path: validated through the session-oriented HTTP adapter and fake backend, with `cancel status: {"status":"acknowledged"}` and local playback stop measured at `27 ms`

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

### Follow-Ups

- continue tightening browser VAD and endpoint behavior from real observations
- keep backend playback-stop telemetry separate from user-perceived audible stop timing
- move beyond the fake backend once a real session-oriented backend target is chosen
