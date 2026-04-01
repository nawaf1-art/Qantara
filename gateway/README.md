# Gateway

This directory is for the custom async Qantara voice gateway.

Initial responsibilities:

- own per-session state
- receive browser audio
- emit browser playback audio
- coordinate VAD, STT, TTS, and interruption state
- expose a narrow adapter boundary to the downstream runtime
- emit event timeline data for observability

Non-goals:

- embedding a specific local OpenClaw deployment at this stage
- hiding the state machine behind framework-specific abstractions
