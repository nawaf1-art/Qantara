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
| Source-checkout CLI launcher | Beta | Selects mock, direct OpenAI-compatible, managed Ollama, managed OpenClaw, YAML, and bind settings; not installed as a console script by the 0.3.1 wheel. |
| faster-whisper STT | Beta | Local model dependency; first use may download model files. |
| Piper TTS | Beta | Local module/executable and voice files are operator-supplied outside the base wheel. |
| Kokoro TTS | Beta | Local Python/ML dependency with first-use model downloads. |
| OpenAI-compatible adapter | Beta | Local `/v1/chat/completions` servers; redirects are not followed. |
| Session-contract HTTP adapter | Beta | Custom local backend implementing Qantara's session/turn/stream/cancel contract. |
| Ollama session bridge | Beta | Native Ollama streaming path and session contract. |
| Mock and fake backends | Beta | Deterministic development, smoke, and contract-test paths. |
| Setup and backend detection UI | Beta | Browser configuration accepts private/loopback targets only. |
| Voice-as-API | Beta | Bounded speak, transcribe, and SSE converse endpoints. |
| Auth and browser session cookie | Beta | Strong token recommended for every LAN deployment. |
| HTTPS/WSS LAN deployment | Beta | Requires operator-managed certificate trust and a trusted LAN. |
| Python SDK (`VoiceGateway`) | Beta | Base package embeds the aiohttp application; no speech models included. |
| English/Arabic voice routing | Beta | Registry-based provider routing; acoustic and dialect coverage varies. |
| Translation modes | Experimental | Model-dependent; validate the selected language/model combination. |
| MCP client adapter | Experimental | Stdio and streamable HTTP chat-tool paths. |
| MCP voice-control server | Experimental | Status, speak, interrupt, transcript, and voice controls. |
| OpenClaw bridge | Experimental | Optional host-side integration with subprocess isolation and cancellation. |
| Multi-device mesh | Experimental | Optional HMAC authentication; replay hardening remains planned. |
| Home Assistant/Wyoming satellite | Experimental | Lab integration, not a turnkey appliance. |
| Chatterbox TTS | Experimental | Resource-heavy expressive-speech path. |
| Screenshot plus voice context | Planned | No current multimodal transport contract. |
| Speech-native model adapters | Planned | Requires an explicit audio-native adapter design. |
| Community provider registry | Planned | Requires compatibility, security, and maintenance policy first. |

The changelog is authoritative for shipped versions. The [roadmap](../ROADMAP.md) describes direction rather than availability, and [documentation governance](DOCUMENTATION_GOVERNANCE.md) defines how status claims are maintained.
