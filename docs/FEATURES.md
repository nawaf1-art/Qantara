# Feature Matrix

Status labels:

- **Stable**: implemented, documented, and expected to work for typical local development.
- **Experimental**: implemented, but still needs broader real-world validation or may change before 1.0.
- **Advanced**: implemented for technical operators, but requires extra setup or careful security choices.
- **Planned**: not implemented yet.

| Feature | Status | Description | Notes |
|---|---|---|---|
| Browser microphone voice UI | Stable | Full-screen browser voice mode with microphone capture, playback, captions, and controls. | Vanilla JavaScript and WebAudio; no frontend build step. |
| Real-time WebSocket voice pipeline | Stable | Browser streams PCM audio to the aiohttp gateway and receives playback events. | PCM16 mono 16 kHz is the internal audio format. |
| STT support | Stable | Local speech-to-text through the provider system. | faster-whisper is the current primary provider path. |
| TTS support | Stable | Local text-to-speech through provider plugins. | Piper and Kokoro paths are available; Chatterbox is more experimental. |
| Barge-in / interruption | Stable | User speech can interrupt assistant playback. | Designed for headset-first full-duplex use. |
| Ollama backend support | Stable | Qantara can talk to Ollama through the OpenAI-compatible path. | The OpenAI-compatible route is the recommended path for Ollama. The session bridge is useful for contract testing. |
| OpenAI-compatible backend support | Stable | Works with local `/v1/chat/completions` servers. | Useful for llama.cpp, LM Studio, Jan, LiteLLM, vLLM, and Ollama. |
| MCP client adapter | Experimental | Qantara can call configured MCP chat tools over stdio or streamable HTTP. | Added in `0.2.8`; real desktop-client testing is still recommended. |
| MCP voice server | Experimental | `mcp_server.py` exposes Qantara voice-control tools to MCP clients. | Tools include status, speak, interrupt, and voice selection. |
| Local-first Docker setup | Stable | `docker compose up` starts the gateway and local runtime pieces. | First startup downloads and builds large speech/model dependencies. |
| LAN exposure option | Advanced | Qantara can bind beyond localhost with HTTPS/WSS and an auth token. | Do not expose directly to the public internet. |
| Auth token support | Stable | Optional token protects WebSocket, setup, control, warmup, and discovery endpoints. | Use a strong `QANTARA_AUTH_TOKEN` for LAN use. |
| Setup page / backend detection | Stable | Browser setup page detects and configures local backend options. | Public backend URLs are rejected by default for local-first safety. |
| OpenClaw local agent bridge | Advanced | Optional bridge for OpenClaw-style local agent systems. | Requires host-side OpenClaw setup; not available inside the default Docker container. |
| Multi-device mesh | Experimental | Multiple Qantara nodes can coordinate which device answers. | Validate carefully on your LAN before relying on it. |
| Home Assistant / Wyoming satellite | Experimental | Qantara can act as a Wyoming satellite for HA Assist workflows. | Treated as a lab path, not a polished HA appliance. |
| Arabic voice routing | Experimental | Arabic Piper voice routing and launch-language voice registry support. | Needs more device, dialect, and acoustic testing. |
| Translation modes | Experimental | Language-aware assistant and translation modes are available. | Smaller local models may struggle with non-Latin languages. |
| Screenshot + voice multimodal | Planned | Voice interaction over screenshots or visual context. | Not implemented in the current public release. |
| Speech-native model adapters | Planned | Direct audio-in/audio-out adapters for speech-native model APIs. | Planned for a later `0.3.x` line. |

## Search Terms Qantara Fits

Qantara is relevant for developers searching for a local voice assistant, Ollama voice assistant, local LLM voice gateway, self-hosted voice AI, real-time voice agent, browser voice AI, AI voice gateway, private AI assistant, MCP voice agent, WebSocket voice assistant, Home Assistant voice AI experiments, and OpenAI-compatible voice agent tooling.
