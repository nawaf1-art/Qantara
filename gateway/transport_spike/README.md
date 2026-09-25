# Gateway Runtime

This directory contains Qantara's primary aiohttp gateway and WebSocket transport. The `transport_spike` package name is historical; this is the shipped local gateway used by the browser client, Voice API, and Python SDK.

## Responsibilities

- serve setup, voice, translation, identity, status, control, and Voice API routes
- accept bounded WebSocket control messages and PCM16 mono 16 kHz frames
- coordinate VAD, endpointing, STT, adapter turns, TTS, playback, and barge-in
- maintain bounded active-session state and resumable snapshots
- enforce auth, Host/Origin policy, browser headers, URL safety, and request limits
- start the optional mesh service and managed local backend bridges

## Recommended source run

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[speech]"
./.venv/bin/qantara --backend mock
```

Open `http://127.0.0.1:8765`. The historical `/spike` path remains available for compatibility.

For a local OpenAI-compatible server:

```bash
./.venv/bin/qantara \
  --backend http://127.0.0.1:11434 \
  --model qwen3.5:2b
```

See [`docs/CLI.md`](../../docs/CLI.md) for launcher behavior and [`docs/CONFIGURATION.md`](../../docs/CONFIGURATION.md) for all runtime settings.

## Speech providers

The default selections are faster-whisper STT and `QANTARA_TTS_PROVIDER=auto`. They are real provider boundaries, not placeholder transcript/tone fallbacks:

- faster-whisper must be installed and able to load the configured model; each utterance is captured whole (up to `QANTARA_MAX_UTTERANCE_MS`, 30 s by default, with 400 ms of pre-roll)
- `auto` routes by language when both Kokoro and a Piper voice are usable (Kokoro for en/es/fr, Piper for Arabic), otherwise uses Kokoro, otherwise Piper; `routed`, `kokoro`, and `piper` force a choice
- Piper requires the `piper-tts` package plus an available voice model/config pair; it runs in-process when importable
- Kokoro is installed by the `speech` extra on Python 3.11/3.12
- Chatterbox is an Experimental separate extra

When no installed voice matches a reply's language, the gateway reports `no_voice_for_language` and the browser shows a plain message instead of reading the text with a mismatched voice.

Provider/model absence is reported as unavailable or an error; the mock backend only replaces downstream reasoning, not missing STT/TTS assets. The browser UI can still be inspected without proving a complete speech installation.

## LAN use

Loopback is the default. Browser microphone use from another device requires HTTPS/WSS, certificate trust, and a strong `QANTARA_AUTH_TOKEN`. Follow [`ops/README.md`](../../ops/README.md); do not expose the gateway directly to the public internet.

## Contracts

- Architecture: [`ARCHITECTURE.md`](../../ARCHITECTURE.md)
- Session model: [`gateway/SESSION_MODEL.md`](../SESSION_MODEL.md)
- Adapter contract: [`adapters/CONTRACT.md`](../../adapters/CONTRACT.md)
- Agent protocol: [`protocols/agent.md`](../../protocols/agent.md)
- Voice API: [`docs/VOICE_API.md`](../../docs/VOICE_API.md)
