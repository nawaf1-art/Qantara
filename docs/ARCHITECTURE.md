# Qantara Architecture

Qantara is a local-first voice gateway. It connects a browser microphone and speaker to local speech providers and local AI backends.

```text
Browser voice UI
  mic input + speaker playback
          |
          | WebSocket PCM16 mono 16 kHz
          v
Qantara aiohttp gateway
  VAD, endpointing, session state, barge-in, auth, setup API
          |
          +--> STT provider
          |      faster-whisper today
          |
          +--> Backend adapter
          |      OpenAI-compatible local server
          |      Ollama session bridge
          |      MCP chat tool
          |      OpenClaw bridge
          |      mock/demo adapter
          |
          +--> TTS provider
                 Piper, Kokoro, Chatterbox paths
          |
          v
Browser playback
```

## Main Pieces

| Piece | Responsibility |
|---|---|
| Browser client | Captures microphone audio, plays assistant audio, shows setup and voice UI. |
| Gateway | Owns the real-time session state machine, WebSocket transport, HTTP setup APIs, auth checks, endpointing, and barge-in. |
| STT providers | Convert user audio to text. |
| Backend adapters | Send user turns to a local LLM, MCP tool, local agent, or mock backend. |
| TTS providers | Convert assistant text into PCM audio for browser playback. |
| Identity and voice registry | Describe available voices, language routing, and avatar metadata. |

## Local-First Security Model

Qantara is designed to run on your machine or LAN:

- No telemetry or analytics are included in the browser client.
- Qantara does not depend on Qantara-controlled cloud services.
- Backend setup rejects public URLs by default in the browser configuration flow.
- Docker binds to `127.0.0.1` by default.
- LAN exposure should use HTTPS/WSS and a strong `QANTARA_AUTH_TOKEN`.
- Model downloads may contact upstream model hosts on first use.

See [../SECURITY.md](../SECURITY.md) and [SUPPLY_CHAIN.md](SUPPLY_CHAIN.md) for the full trust boundary.

## Why A Gateway Instead Of A Full Assistant?

Qantara deliberately does not replace Ollama, OpenClaw, LangChain, Home Assistant, or another agent runtime. Those systems own reasoning, tools, memory, and business logic. Qantara owns the real-time voice channel.

This separation makes it easier to swap local models and agent runtimes without rebuilding the voice stack.
