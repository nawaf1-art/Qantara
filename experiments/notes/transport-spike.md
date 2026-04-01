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

### Egress

- playback startup delay: not measured precisely yet, but request tone and mock turn playback both functioned
- queue behavior: basic playback path is working
- clear or stop behavior: not fully characterized from the current notes

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
- transcription latency feel: acceptable for the current M0 spike
- current result: first validated STT candidate

### TTS

- Piper runtime available: yes
- local voice model installed: `models/piper/en_US-lessac-medium.onnx`
- direct synthesis outside the browser spike: working
- first-audio feel through browser playback: not yet recorded
- fallback tone used: yes, during the earlier pre-Piper runs
- current result: Piper runtime validated locally, browser-path validation still pending

### Follow-Ups

- run a browser `Mock Turn` against the live secure spike and confirm Piper playback is used instead of synthetic fallback
- decide whether Piper remains the first TTS candidate after that browser-path run
- continue tightening browser VAD and endpoint behavior from real observations
