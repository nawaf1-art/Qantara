"""Voice-as-API: programmatic HTTP endpoints for any local app.

POST /api/v1/speak       {text, voice_id?, speech_rate?}  -> audio/wav (or ?format=pcm)
POST /api/v1/transcribe  audio body (WAV or raw PCM16)    -> {text, language, ...}
POST /api/v1/converse    {text, session_id?}              -> SSE stream of adapter events

These endpoints bypass the browser client entirely: an Obsidian plugin, a
shell script, or a Home Assistant automation can call them directly. Audio
in/out is one-shot per request; the long-lived bidirectional path remains
the existing /ws transport. All endpoints honor QANTARA_AUTH_TOKEN and log
one audit line per request to the "qantara.voice_api" logger.
"""

from __future__ import annotations

import io
import json
import logging
import os
import struct
import time
import wave

from aiohttp import web

from gateway.transport_spike.auth import AUTH_TOKEN_KEY, require_bearer_token
from gateway.transport_spike.common import TARGET_SAMPLE_RATE
from gateway.transport_spike.runtime import APP_RUNTIME_KEY, GatewayRuntime

LOGGER = logging.getLogger("qantara.voice_api")

# One-shot transcription uploads are bounded: this is a request/response
# convenience API, not a streaming ingest path.
MAX_AUDIO_BYTES = 32 * 1024 * 1024

CONVERSE_TURN_TIMEOUT_SECONDS = float(os.environ.get("QANTARA_VOICE_API_TURN_TIMEOUT", "120"))

# client session_id -> adapter session handle, bounded LRU like the
# adapter-side session stores.
MAX_API_SESSIONS = 64
_api_sessions: dict[str, str] = {}


def _audit(request: web.Request, detail: str) -> None:
    LOGGER.info("voice_api %s %s %s", request.method, request.path, detail)


def _runtime(request: web.Request) -> GatewayRuntime:
    return request.app[APP_RUNTIME_KEY]


def _pcm16_bytes(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *[max(-32768, min(32767, int(s))) for s in samples])


def _wav_bytes(samples: list[int], sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(_pcm16_bytes(samples))
    return buf.getvalue()


async def api_v1_speak_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "body must be JSON"}, status=400)
    text = str(payload.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "text is required"}, status=400)
    voice_id = payload.get("voice_id")
    speech_rate = payload.get("speech_rate")

    runtime = _runtime(request)
    if not runtime.tts.available:
        return web.json_response({"error": "no TTS provider available"}, status=503)
    started_ms = time.monotonic() * 1000
    try:
        samples, resolved_voice, fallback_reason = await runtime.tts.synthesize(
            text,
            voice_id=voice_id,
            speech_rate=speech_rate,
        )
    except Exception as exc:
        return web.json_response({"error": f"synthesis failed: {exc}"}, status=502)
    sample_rate = resolved_voice.sample_rate
    synthesis_ms = round((time.monotonic() * 1000) - started_ms, 1)
    _audit(request, f"chars={len(text)} voice={resolved_voice.voice_id} synthesis_ms={synthesis_ms}")

    headers = {
        "X-Voice-Id": resolved_voice.voice_id,
        "X-Sample-Rate": f"rate={sample_rate}",
    }
    if fallback_reason:
        headers["X-Voice-Fallback-Reason"] = str(fallback_reason)
    if request.query.get("format", "").strip().lower() == "pcm":
        return web.Response(body=_pcm16_bytes(samples), content_type="audio/L16", headers=headers)
    return web.Response(body=_wav_bytes(samples, sample_rate), content_type="audio/wav", headers=headers)


def _decode_audio_body(body: bytes, content_type: str, sample_rate_param: str | None) -> tuple[list[int], int]:
    """Decode a request body into PCM16 samples + sample rate.

    WAV bodies carry their own rate; raw PCM16 bodies use ?sample_rate
    (default 16000). Raises ValueError for malformed input.
    """
    if content_type.startswith("audio/wav") or body[:4] == b"RIFF":
        with wave.open(io.BytesIO(body), "rb") as wav_file:
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                raise ValueError("WAV must be mono PCM16")
            sample_rate = wav_file.getframerate()
            raw = wav_file.readframes(wav_file.getnframes())
    else:
        sample_rate = int(sample_rate_param or TARGET_SAMPLE_RATE)
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        raw = body
    if len(raw) < 2:
        raise ValueError("audio body is empty")
    if len(raw) % 2:
        raw = raw[:-1]
    samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    return samples, sample_rate


async def api_v1_transcribe_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    body = await request.read()
    if len(body) > MAX_AUDIO_BYTES:
        return web.json_response({"error": "audio body too large"}, status=413)
    try:
        samples, sample_rate = _decode_audio_body(
            body, request.content_type or "", request.query.get("sample_rate")
        )
    except Exception as exc:
        return web.json_response({"error": f"could not decode audio: {exc}"}, status=400)

    runtime = _runtime(request)
    if not runtime.stt.available:
        return web.json_response({"error": "no STT provider available"}, status=503)
    started_ms = time.monotonic() * 1000
    try:
        result = await runtime.stt.transcribe(samples, sample_rate)
    except Exception as exc:
        return web.json_response({"error": f"transcription failed: {exc}"}, status=502)
    transcribe_ms = round((time.monotonic() * 1000) - started_ms, 1)
    _audit(request, f"samples={len(samples)} rate={sample_rate} transcribe_ms={transcribe_ms}")
    return web.json_response({
        "text": result.text,
        "language": result.language,
        "language_probability": result.language_probability,
        "sample_rate": sample_rate,
        "provider": runtime.stt.kind,
    })


async def _resolve_adapter_session(runtime: GatewayRuntime, client_session_id: str | None) -> tuple[object, str]:
    binding = runtime.default_binding()
    adapter = binding.adapter
    if client_session_id:
        existing = _api_sessions.get(client_session_id)
        if existing is not None:
            # Refresh recency for LRU eviction.
            _api_sessions[client_session_id] = _api_sessions.pop(client_session_id)
            return adapter, existing
    handle = await adapter.start_or_resume_session({"source": "voice_api", "client_session_id": client_session_id})
    if client_session_id:
        _api_sessions[client_session_id] = handle
        while len(_api_sessions) > MAX_API_SESSIONS:
            _api_sessions.pop(next(iter(_api_sessions)), None)
    return adapter, handle


async def api_v1_converse_handler(request: web.Request) -> web.StreamResponse:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "body must be JSON"}, status=400)
    text = str(payload.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "text is required"}, status=400)
    client_session_id = (str(payload.get("session_id") or "").strip()) or None

    runtime = _runtime(request)
    adapter, session_handle = await _resolve_adapter_session(runtime, client_session_id)

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    async def send_event(event: dict) -> None:
        line = f"event: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n"
        await response.write(line.encode("utf-8"))

    started = time.monotonic()
    _audit(request, f"chars={len(text)} session={client_session_id or 'ephemeral'}")
    try:
        turn_handle = await adapter.submit_user_turn(session_handle, text, {"source": "voice_api", "modality": "text"})
        await send_event({"type": "turn_accepted", "turn_handle": turn_handle, "session_id": client_session_id})
        saw_final = False
        buffered = ""
        async for event in adapter.stream_assistant_output(session_handle, turn_handle):
            if time.monotonic() - started > CONVERSE_TURN_TIMEOUT_SECONDS:
                await send_event({"type": "turn_failed", "message": "turn timed out"})
                break
            event_type = event.get("type")
            if event_type == "assistant_text_delta":
                buffered += event.get("text", "")
            if event_type == "assistant_text_final":
                saw_final = True
            await send_event(event)
        if not saw_final and buffered:
            await send_event({"type": "assistant_text_final", "text": buffered, "completed_via": "buffer_flush"})
        await send_event({"type": "turn_completed"})
    except Exception as exc:
        await send_event({"type": "turn_failed", "message": str(exc)})
    await response.write_eof()
    return response


def mount_voice_api(app: web.Application) -> None:
    app.router.add_post("/api/v1/speak", api_v1_speak_handler)
    app.router.add_post("/api/v1/transcribe", api_v1_transcribe_handler)
    app.router.add_post("/api/v1/converse", api_v1_converse_handler)
