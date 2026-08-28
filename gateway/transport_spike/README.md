# Gateway Runtime

This directory contains Qantara's primary aiohttp gateway and WebSocket transport. The `transport_spike` package name is historical; this is the shipped local gateway used by the browser client, Voice API, and Python SDK.

## Responsibilities

- serve setup, voice, translation, identity, status, control, and Voice API routes
- accept bounded WebSocket control messages and PCM16 mono 16 kHz frames
- coordinate VAD, endpointing, STT, adapter turns, TTS, playback, and barge-in
- maintain bounded active-session state and resumable snapshots
- enforce auth, Host/Origin policy, browser headers, URL safety, and request limits
- start optional mesh/Wyoming services and managed local backend bridges

## Recommended source run

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[speech]"
./.venv/bin/python cli.py --backend mock
```

Open `http://127.0.0.1:8765`. The historical `/spike` path remains available for compatibility.

For a local OpenAI-compatible server:

```bash
./.venv/bin/python cli.py \
  --backend http://127.0.0.1:11434 \
  --model qwen3.5:2b
```

See [`docs/CLI.md`](../../docs/CLI.md) for launcher behavior and [`docs/CONFIGURATION.md`](../../docs/CONFIGURATION.md) for all runtime settings.

## Speech providers

The default selections are faster-whisper STT and Piper TTS. They are real provider boundaries, not placeholder transcript/tone fallbacks:

- faster-whisper must be installed and able to load the configured model
- Piper requires the Python module/executable plus an available voice model/config pair
- Kokoro is installed by the `speech` extra and can be selected with `QANTARA_TTS_PROVIDER=kokoro`
- Chatterbox is an Experimental separate extra

Provider/model absence is reported as unavailable or an error; the mock backend only replaces downstream reasoning, not missing STT/TTS assets. The browser UI can still be inspected without proving a complete speech installation.

## LAN use

Loopback is the default. Browser microphone use from another device requires HTTPS/WSS, certificate trust, and a strong `QANTARA_AUTH_TOKEN`. Follow [`ops/README.md`](../../ops/README.md); do not expose the gateway directly to the public internet.

## Contracts

- Architecture: [`ARCHITECTURE.md`](../../ARCHITECTURE.md)
- Session model: [`gateway/SESSION_MODEL.md`](../SESSION_MODEL.md)
- Adapter contract: [`adapters/CONTRACT.md`](../../adapters/CONTRACT.md)
- Agent protocol: [`protocols/agent.md`](../../protocols/agent.md)
- Voice API: [`docs/VOICE_API.md`](../../docs/VOICE_API.md)
