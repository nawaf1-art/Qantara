# Voice-as-API

Qantara's voice pipeline as plain HTTP — for shell scripts, editor plugins,
Home Assistant automations, or any local app. The browser client is not
involved; these endpoints talk to the gateway's STT/TTS providers and the
configured backend adapter directly.

All endpoints honor `QANTARA_AUTH_TOKEN` (send `Authorization: Bearer <token>`
when configured) and write one audit line per request to the
`qantara.voice_api` logger.

## POST /api/v1/speak

Synthesize text to audio.

Request body (JSON):

| Field | Required | Notes |
|---|---|---|
| `text` | yes | The text to speak (maximum 16,384 characters) |
| `voice_id` | no | Defaults to the gateway's configured voice |
| `speech_rate` | no | Clamped to the voice's allowed range |

Response: `audio/wav` (mono PCM16). Add `?format=pcm` for headerless
`audio/L16` frames; the rate is in the `X-Sample-Rate` header either way.

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/speak \
  -H 'Content-Type: application/json' \
  -d '{"text": "hello from the voice API"}' > hello.wav && aplay hello.wav
```

## POST /api/v1/transcribe

Transcribe one audio clip.

- Body `audio/wav` (mono PCM16) — sample rate read from the WAV header, or
- Body `application/octet-stream` of raw little-endian PCM16 with
  `?sample_rate=16000`.

Bodies are capped at 32 MB — this is a one-shot convenience call, not a
streaming ingest path.

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/transcribe \
  -H 'Content-Type: audio/wav' --data-binary @question.wav
# {"text": "...", "language": "en", "language_probability": 0.98, ...}
```

## POST /api/v1/converse

Run a full text turn through the configured backend adapter, streaming the
agent-protocol events back as Server-Sent Events (see `protocols/agent.md`
for the event shapes).

Request body (JSON):

| Field | Required | Notes |
|---|---|---|
| `text` | yes | The user turn (maximum 16,384 characters) |
| `session_id` | no | Reuse the same value (maximum 256 characters) to keep conversation history across calls (bounded store, LRU-evicted) |

The stream ends with a `turn_completed` (or `turn_failed`) event. Turns are
bounded by `QANTARA_VOICE_API_TURN_TIMEOUT` (default 120 s).

```bash
curl -N -X POST http://127.0.0.1:8765/api/v1/converse \
  -H 'Content-Type: application/json' \
  -d '{"text": "tell me a one-line joke", "session_id": "my-shell"}'
```

Python (the whole client):

```python
import json, requests

with requests.post("http://127.0.0.1:8765/api/v1/converse",
                   json={"text": "hello"}, stream=True) as resp:
    for line in resp.iter_lines():
        if line.startswith(b"data: "):
            event = json.loads(line[6:])
            if event["type"] == "assistant_text_final":
                print(event["text"])
```

To *hear* the reply, pipe the final text into `/api/v1/speak`. More runnable
clients live in [docs/examples/clients/](examples/clients/).

## Scope notes

- Audio in/out here is one-shot per request. The long-lived bidirectional
  audio path remains the `/ws` WebSocket transport. A dedicated Voice API
  streaming transport is not implemented.
- Transcription bodies are limited to 32 MiB. Ordinary control JSON uses a
  smaller application-wide limit, and generated assistant text is bounded.
- Default audit lines record route, character/sample counts, provider, and
  timings rather than request or transcript content.
- `route` targeting of a specific mesh peer is not implemented yet; requests
  run on the node you call.
