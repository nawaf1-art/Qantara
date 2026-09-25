# Feature Matrix

Qantara is pre-1.0. Current documentation uses these labels:

- **Beta:** implemented, tested, and suitable for evaluation or controlled local use; compatibility may still change before 1.0.
- **Experimental:** implemented but needs broader validation, may require advanced setup, or may change substantially.
- **Planned:** accepted direction but not implemented.
- **Deprecated:** still present for compatibility but scheduled for removal.

| Feature | Status | Scope and caveat |
|---|---|---|
| Browser microphone voice UI | Beta | Vanilla JavaScript/WebAudio capture, playback, captions, and controls. |
| WebSocket voice transport | Beta | Bounded control messages and PCM16 mono 16 kHz audio frames. |
| VAD, endpointing, and auto-submit | Beta | Primary headset-first turn path. |
| Barge-in and cancellation | Beta | Gateway stops playback and enforces a bounded escalation path when adapters do not cooperate. |
| `qantara` CLI launcher and doctor | Beta | Selects mock, direct OpenAI-compatible, managed Ollama, managed OpenClaw, YAML, and bind settings; flags override environment variables. Installed as console scripts from `0.4.0` (the published 0.3.1 wheel predates them). |
| faster-whisper STT | Beta | Local model dependency; first use may download model files. Captures the whole utterance (up to 30 s by default); optional `QANTARA_STT_LANGUAGES` restricts detection. |
| Piper TTS | Beta | `piper-tts` and voice files are operator-supplied outside the base wheel; `scripts/fetch_piper_voices.sh` fetches checksum-verified voices. Not in the Docker image. |
| Kokoro TTS | Beta | Local Python/ML dependency with first-use model downloads; Python 3.11/3.12 only. English, Spanish, and French voices. |
| OpenAI-compatible adapter | Beta | Local `/v1/chat/completions` servers; redirects are not followed. |
| Session-contract HTTP adapter | Beta | Custom local backend implementing Qantara's session/turn/stream/cancel contract. |
| Ollama session bridge | Beta | Native Ollama streaming path and session contract. |
| Mock and fake backends | Beta | Deterministic development, smoke, and contract-test paths. |
| Setup and backend detection UI | Beta | Browser configuration accepts private/loopback targets only. |
| Voice-as-API | Beta | Bounded speak, transcribe, and SSE converse endpoints. |
| Auth and browser sessions | Beta | Required for any non-loopback access (the gateway fails closed without a token); per-login server-side sessions and a failed-credential limiter. |
| HTTPS/WSS LAN deployment | Beta | Requires operator-managed certificate trust and a trusted LAN. |
| Python SDK (`VoiceGateway`) | Beta | Base package embeds the aiohttp application; no speech models included. |
| Language-routed TTS (`auto`) | Beta | Kokoro for en/es/fr and Piper for Arabic when both are installed; text with no matching voice is reported, not misread. Acoustic and dialect coverage varies. |
| Translation modes | Experimental | Model-dependent; validate the selected language/model combination. |
| MCP client adapter | Experimental | Stdio and streamable HTTP chat-tool paths. |
| MCP voice-control server | Experimental | Status, speak, interrupt, transcript, and voice controls. |
| OpenClaw bridge | Experimental | Optional host-side integration with subprocess isolation and cancellation. |
| Multi-device mesh | Experimental | HMAC token required for LAN binds; single-machine election fixed and unit-tested, not validated across physical devices; replay protection remains planned. |
| Chatterbox TTS | Experimental | Resource-heavy expressive-speech path. |
| Screenshot plus voice context | Planned | No current multimodal transport contract. |
| Speech-native model adapters | Planned | Requires an explicit audio-native adapter design. |
| Community provider registry | Planned | Requires compatibility, security, and maintenance policy first. |

**Removed in 0.4.0:** the Home Assistant/Wyoming satellite bridge (previously Experimental). It did not match Home Assistant's satellite model (Home Assistant could add the device but never trigger it) and exposed an unauthenticated port. A replacement is a roadmap candidate, not a planned feature; see [Home Assistant](HOMEASSISTANT.md).

The changelog is authoritative for shipped versions. The [roadmap](../ROADMAP.md) describes direction rather than availability, and [documentation governance](DOCUMENTATION_GOVERNANCE.md) defines how status claims are maintained.
