# Qantara 0.3.0

Qantara 0.3.0 establishes the canonical platform release line after the Python
SDK milestone. It consolidates the SDK, Voice-as-API, current Ollama
compatibility, stream-correctness fixes, July audit hardening, and refreshed
dependencies.

Apart from one mesh shutdown fix, this is a version and release-metadata
correction; the rest of the runtime is equivalent to Qantara 0.2.12.

## Highlights

- Installable Python SDK with `VoiceGateway` embedding and standalone serving.
- HTTP Voice-as-API endpoints for speech generation, transcription, and
  streamed conversations.
- Validated Ollama `0.32.3` support with `qwen3.5:2b` as the compact default.
- Correct handling of fragmented streams, multibyte Arabic text, cancellation,
  reasoning-only responses, and barge-in races.
- Refreshed, security-patched Python and ML dependency set.
- Mesh shutdown no longer hangs when a peer connects as the server is stopping.

## Version compatibility

The published `v0.2.10` and `v0.2.12` tags remain available and unchanged.
New installations and downstream references should use `v0.3.0`.

## Upgrade

```bash
git pull
python3 -m venv .venv
./.venv/bin/pip install -r gateway/transport_spike/requirements.txt
```

For Docker:

```bash
docker compose pull
docker compose up --build
```

See [Ollama compatibility](OLLAMA_COMPATIBILITY.md),
[Voice API](VOICE_API.md), and the full [changelog](../CHANGELOG.md).
