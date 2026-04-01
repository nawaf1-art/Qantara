# Milestones

## M0: Technical Validation

- [ ] Define a runtime adapter boundary that does not depend on a specific local OpenClaw deployment
- [ ] Write down the custom gateway session model for a single browser client
- [ ] Prove browser mic capture to the gateway over WebSocket PCM
- [ ] Prove browser playback of streamed audio from the gateway
- [ ] Validate WebSocket PCM as the MVP transport under headset-first conditions
- [ ] Evaluate Pipecat as a reference path against the same MVP requirements
- [ ] Choose baseline local STT candidate
- [ ] Choose baseline local TTS candidate
- [ ] Define the initial TTS chunking rule to test
- [ ] Define voice event timeline schema
- [ ] Confirm the gateway can emit the minimum required timestamps
- [ ] Record the concrete migration triggers that would justify moving to WebRTC later

Exit criteria:

- Browser client can send audio and receive gateway-driven output on one LAN session
- The project can proceed on speech, transport, and state-machine work without binding to current local OpenClaw agents
- The custom gateway remains the chosen implementation path after the Pipecat comparison
- One STT candidate and one TTS candidate are selected for M1

## M1: Full-Duplex Foundation

- [ ] Implement browser WebSocket session bootstrap
- [ ] Implement always-on microphone streaming
- [ ] Implement gateway-side VAD and endpointing
- [ ] Implement partial transcript updates
- [ ] Implement final transcript submission path
- [ ] Implement browser captions and session state indicators
- [ ] Implement per-session event timeline logging
- [ ] Implement reconnect handling for a single browser client

Exit criteria:

- Voice input to assistant text output works reliably on a headset-based browser setup
- Latency measurements are available for every major event boundary

## M2: Spoken Response Path

- [ ] Integrate first local TTS backend
- [ ] Define assistant text chunking policy for TTS
- [ ] Stream or chunk TTS audio back to browser
- [ ] Add browser playback state indicators
- [ ] Stop playback immediately on user speech detect
- [ ] Record interruption metadata in session logs
- [ ] Add text fallback when TTS fails

Exit criteria:

- Assistant audio playback feels conversational on target hardware
- User interruption reliably stops playback without leaving ghost audio

## M3: Hard Barge-In And Recovery

- [ ] Add hard-cancel path if the chosen downstream runtime supports it
- [ ] Distinguish soft vs hard barge-in in logs and UI state
- [ ] Define interrupted-response history policy
- [ ] Improve STT/TTS retry and degraded-mode handling
- [ ] Validate repeated interruption across long responses

Exit criteria:

- Repeated interruption does not corrupt the session state machine
- Recovery behavior is predictable and visible to the user

## M4: Security And Operational Hardening

- [ ] Bind the gateway to safe default interfaces
- [ ] Add client auth or signed session tokens
- [ ] Add confirmation gates for high-risk tools
- [ ] Add local transcript and interruption audit logs
- [ ] Add session metrics dashboard or log summary
- [ ] Document safe LAN deployment defaults

Exit criteria:

- The system is safe enough for internal LAN testing with real tool permissions
- Operational traces are sufficient for debugging and policy review

## M5: Runtime Integration Validation

- [ ] Select the downstream runtime to integrate with
- [ ] Validate session create or resume path in the chosen runtime
- [ ] Validate assistant output streaming or equivalent event path
- [ ] Validate whether generation cancellation exists
- [ ] Record environment-specific host, auth, and routing assumptions only after validation

Exit criteria:

- Qantara can connect to the selected runtime using a documented and validated adapter contract
- Runtime-specific assumptions are isolated from the core voice gateway design
