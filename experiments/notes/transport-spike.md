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

- Piper available: no, not on the current machine
- first-audio feel: only the synthetic fallback path has been observed so far
- fallback tone used: yes
- current result: Piper not validated in this environment yet

### Follow-Ups

- install Piper and a usable voice model, or choose the replacement TTS candidate
- decide whether Piper remains the first TTS candidate after a real run
- continue tightening browser VAD and endpoint behavior from real observations
