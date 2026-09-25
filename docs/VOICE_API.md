# Voice-as-API

Qantara's voice pipeline as plain HTTP — for shell scripts, editor plugins,
Home Assistant automations, or any local app. The browser client is not
involved; these endpoints talk to the gateway's STT/TTS providers and the
configured backend adapter directly.

All endpoints honor `QANTARA_AUTH_TOKEN` (send `Authorization: Bearer <token>`
when configured) and write one audit line per request to the
`qantara.voice_api` logger. Without a token the gateway answers only loopback
`Host` names (see [Configuration](CONFIGURATION.md#safe-defaults)), so call
it as `http://127.0.0.1:8765` or set a token for LAN clients.

Speech work is bounded: at most `QANTARA_VOICE_API_CONCURRENCY` (default 2)
speak/transcribe jobs run at once; further requests wait their turn.

## POST /api/v1/speak

Synthesize text to audio.

Request body (JSON):

| Field | Required | Notes |
|---|---|---|
| `text` | yes | The text to speak (maximum `QANTARA_VOICE_API_MAX_SPEAK_CHARS`, default 4,000 characters; longer text gets `413`) |
| `voice_id` | no | Defaults to the gateway's configured voice |
| `speech_rate` | no | Clamped to the voice's allowed range |

Response: `audio/wav` (mono PCM16). Add `?format=pcm` for the same samples as
headerless little-endian PCM16 with the content type
`audio/pcm;rate=<N>;channels=1;encoding=signed-int;bits=16;endian=little`
(not `audio/L16`, which RFC 3551 defines as big-endian).

Response headers:

| Header | Notes |
|---|---|
| `X-Sample-Rate` | Plain integer sample rate, e.g. `24000` |
| `X-Voice-Id` | The voice actually used; present only when it is a plain identifier (`[A-Za-z0-9._:-]`, up to 128 characters) |
| `X-Voice-Fallback-Reason` | Present when a fallback voice was used: `requested_voice_unavailable` or `fallback` |

Errors: `400` for invalid fields, `413` for text over the limit, `503` when no
TTS provider is available, and `502` when synthesis fails — including
`no_voice_for_language` when no installed voice can speak the text's language
or script.

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/speak \
  -H 'Content-Type: application/json' \
  -d '{"text": "hello from the voice API"}' > hello.wav && aplay hello.wav
```

## POST /api/v1/transcribe

Transcribe one audio clip.

- Body `audio/wav` (mono PCM16) — sample rate read from the WAV header, or
- Body `application/octet-stream` of raw little-endian PCM16 with
  `?sample_rate=16000` (the default when omitted).

Sample rates outside 8000–48000 Hz and clips longer than
`QANTARA_TRANSCRIBE_MAX_SECONDS` (default 120 s) get `400`; both are checked
before the audio is decoded. Bodies are capped at 32 MiB (`413`) — this is a
one-shot convenience call, not a streaming ingest path.

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/transcribe \
  -H 'Content-Type: audio/wav' --data-binary @question.wav
# {"ok": true, "text": "...", "language": "en", "language_probability": 0.98, "sample_rate": 16000, "provider": "faster_whisper"}
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

Validation errors (`400`/`413`) are returned as JSON before the stream starts.
Once the request is valid the response is always `200 text/event-stream`:
failures after that point, including a backend that cannot start a session,
arrive as a `turn_failed` event rather than an HTTP 500.

Stream rules:

- When the turn is submitted, the first event is `turn_accepted`.
- `assistant_text_final` is always sent before `turn_completed`; if the
  adapter only streamed deltas, the gateway sends the buffered text as
  `assistant_text_final` with `"completed_via": "buffer_flush"`.
- The stream ends with `turn_completed`, or with `turn_failed` /
  `cancel_acknowledged`.
- Events whose `type` is not a plain protocol name (`[a-z_]{1,64}`) are
  dropped, and `assistant_activity` events are re-validated, so a backend
  cannot inject SSE frames.
- A stored `session_id` is reset only when the adapter reports the session is
  unknown (for example after a backend restart or `/api/configure`); the turn
  is then retried once on a fresh session. Other failures keep the
  conversation.
- Turns are bounded by `QANTARA_VOICE_API_TURN_TIMEOUT` (default 120 s); a
  timeout sends `turn_failed` and cancels the backend turn.

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
clients live in [docs/examples/clients/](examples/clients/). To speak through
an already-open browser session instead, use `qantara.control.VoiceControl`
(see [Python SDK](PYTHON_SDK.md#voice-control-client)).

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

## Changes in 0.4.0

- `?format=pcm` responses changed content type from `audio/L16` to
  `audio/pcm;rate=N;channels=1;encoding=signed-int;bits=16;endian=little`.
  The bytes are unchanged. Clients that matched the old content type must be
  updated.
- `X-Sample-Rate` is a plain integer (was `rate=N`), `X-Voice-Fallback-Reason` uses a fixed
  vocabulary, and `X-Voice-Id` is omitted for non-plain identifiers.
- `/speak` text is limited to 4,000 characters by default (was 16,384).
- `/transcribe` rejects out-of-range sample rates and over-long clips with `400`.
- `/converse` reports session-start failures as an SSE `turn_failed` event
  instead of an HTTP 500.
