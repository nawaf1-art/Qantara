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

import array
import asyncio
import contextlib
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import wave
from collections.abc import Sequence

from aiohttp import web

from adapters.base import is_unknown_session_error, make_activity_event
from gateway.transport_spike.auth import AUTH_TOKEN_KEY, require_bearer_token
from gateway.transport_spike.common import TARGET_SAMPLE_RATE
from gateway.transport_spike.runtime import APP_RUNTIME_KEY, GatewayRuntime

LOGGER = logging.getLogger("qantara.voice_api")

# One-shot transcription uploads are bounded: this is a request/response
# convenience API, not a streaming ingest path.
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_TEXT_CHARS = 16 * 1024
# /speak synthesizes the whole reply in one request; keep it to the same
# budget as the control-plane speak endpoint.
MAX_SPEAK_TEXT_CHARS = int(os.environ.get("QANTARA_VOICE_API_MAX_SPEAK_CHARS", "4000"))
MAX_SESSION_ID_CHARS = 256
MAX_GENERATED_TEXT_CHARS = 1024 * 1024
MIN_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = 48000
# Checked from the header/body size before any sample is decoded.
TRANSCRIBE_MAX_SECONDS = float(os.environ.get("QANTARA_TRANSCRIBE_MAX_SECONDS", "120"))
# Concurrent speech jobs (transcribe + speak) across the Voice API.
VOICE_API_CONCURRENCY = max(1, int(os.environ.get("QANTARA_VOICE_API_CONCURRENCY", "2")))
VOICE_API_SEMAPHORE_KEY: web.AppKey[asyncio.Semaphore] = web.AppKey("voice_api_semaphore", asyncio.Semaphore)

CONVERSE_TURN_TIMEOUT_SECONDS = float(os.environ.get("QANTARA_VOICE_API_TURN_TIMEOUT", "120"))

# Adapter-controlled event types become the SSE "event:" line; anything
# else is dropped so a backend cannot inject frames.
SSE_EVENT_TYPE_RE = re.compile(r"[a-z_]{1,64}")
_VOICE_ID_HEADER_RE = re.compile(r"[A-Za-z0-9._:\-]{1,128}")


class AudioInputError(ValueError):
    """The uploaded audio is outside the accepted format or bounds."""

# client session_id -> adapter session handle, bounded LRU like the
# adapter-side session stores.
MAX_API_SESSIONS = 64
_api_sessions: dict[str, str] = {}


def _audit(request: web.Request, detail: str) -> None:
    LOGGER.info("voice_api %s %s %s", request.method, request.path, detail)


def _session_log_id(client_session_id: str | None) -> str:
    """Return a stable diagnostic identifier without logging the client value."""
    if client_session_id is None:
        return "ephemeral"
    digest = hashlib.sha256(client_session_id.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


def _runtime(request: web.Request) -> GatewayRuntime:
    return request.app[APP_RUNTIME_KEY]


def _speech_semaphore(request: web.Request) -> asyncio.Semaphore:
    semaphore = request.app.get(VOICE_API_SEMAPHORE_KEY)
    if semaphore is None:  # app assembled without mount_voice_api()
        semaphore = asyncio.Semaphore(VOICE_API_CONCURRENCY)
        request.app[VOICE_API_SEMAPHORE_KEY] = semaphore
    return semaphore


def _pcm16_bytes(samples: Sequence[int]) -> bytes:
    """Encode samples as little-endian PCM16, clipping out-of-range values.

    Uses the C-level ``array`` codec; only out-of-range or non-int input
    takes the per-sample clipping path. Call from a worker thread.
    """
    try:
        pcm = array.array("h", samples)
    except (OverflowError, TypeError):
        pcm = array.array("h", (max(-32768, min(32767, int(s))) for s in samples))
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm.tobytes()


def _wav_bytes(samples: Sequence[int], sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(_pcm16_bytes(samples))
    return buf.getvalue()


def _fallback_reason_code(reason: object) -> str:
    """Map a provider's free-text fallback reason to a fixed header value."""
    return "requested_voice_unavailable" if "unavailable" in str(reason).lower() else "fallback"


async def api_v1_speak_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    try:
        payload = await request.json()
    except web.HTTPRequestEntityTooLarge:
        return web.json_response({"ok": False, "error": "body too large"}, status=413)
    except Exception:
        return web.json_response({"ok": False, "error": "body must be JSON"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "body must be a JSON object"}, status=400)
    raw_text = payload.get("text")
    if not isinstance(raw_text, str):
        return web.json_response({"ok": False, "error": "text must be a string"}, status=400)
    text = raw_text.strip()
    if not text:
        return web.json_response({"ok": False, "error": "text is required"}, status=400)
    if len(text) > MAX_SPEAK_TEXT_CHARS:
        return web.json_response(
            {"ok": False, "error": f"text is too long (max {MAX_SPEAK_TEXT_CHARS} characters)"},
            status=413,
        )
    voice_id = payload.get("voice_id")
    speech_rate = payload.get("speech_rate")
    if voice_id is not None and not isinstance(voice_id, str):
        return web.json_response({"ok": False, "error": "voice_id must be a string"}, status=400)
    if speech_rate is not None and (
        isinstance(speech_rate, bool) or not isinstance(speech_rate, (int, float))
    ):
        return web.json_response({"ok": False, "error": "speech_rate must be a number"}, status=400)

    runtime = _runtime(request)
    if not runtime.tts.available:
        return web.json_response({"ok": False, "error": "no TTS provider available"}, status=503)
    want_pcm = request.query.get("format", "").strip().lower() == "pcm"
    started_ms = time.monotonic() * 1000
    async with _speech_semaphore(request):
        try:
            samples, resolved_voice, fallback_reason = await runtime.tts.synthesize(
                text,
                voice_id=voice_id,
                speech_rate=speech_rate,
            )
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"synthesis failed: {exc}"}, status=502)
        sample_rate = int(resolved_voice.sample_rate)
        if want_pcm:
            body = await asyncio.to_thread(_pcm16_bytes, samples)
        else:
            body = await asyncio.to_thread(_wav_bytes, samples, sample_rate)
    synthesis_ms = round((time.monotonic() * 1000) - started_ms, 1)
    _audit(request, f"chars={len(text)} voice={resolved_voice.voice_id} synthesis_ms={synthesis_ms}")

    # Header values are fixed vocabularies or validated identifiers: nothing
    # from the request (or free text derived from it) is reflected.
    headers = {"X-Sample-Rate": str(sample_rate)}
    resolved_voice_id = str(resolved_voice.voice_id or "")
    if _VOICE_ID_HEADER_RE.fullmatch(resolved_voice_id):
        headers["X-Voice-Id"] = resolved_voice_id
    if fallback_reason:
        headers["X-Voice-Fallback-Reason"] = _fallback_reason_code(fallback_reason)
    if want_pcm:
        # Raw little-endian PCM16. Not audio/L16, which RFC 3551 defines as
        # big-endian.
        headers["Content-Type"] = (
            f"audio/pcm;rate={sample_rate};channels=1;encoding=signed-int;bits=16;endian=little"
        )
        return web.Response(body=body, headers=headers)
    return web.Response(body=body, content_type="audio/wav", headers=headers)


def _validated_sample_rate(value: object) -> int:
    try:
        sample_rate = int(str(value).strip())
    except (TypeError, ValueError):
        sample_rate = 0
    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        raise AudioInputError(
            f"sample_rate must be an integer between {MIN_SAMPLE_RATE} and {MAX_SAMPLE_RATE} Hz"
        )
    return sample_rate


def _check_duration(sample_count: int, sample_rate: int) -> None:
    if sample_count > TRANSCRIBE_MAX_SECONDS * sample_rate:
        raise AudioInputError(f"audio is longer than {TRANSCRIBE_MAX_SECONDS:g} seconds")


def _decode_audio_body(body: bytes, content_type: str, sample_rate_param: str | None) -> tuple[list[int], int]:
    """Decode a request body into PCM16 samples + sample rate.

    WAV bodies carry their own rate; raw PCM16 bodies use ?sample_rate
    (default 16000). The rate must be 8000-48000 Hz and the clip no longer
    than TRANSCRIBE_MAX_SECONDS; both are checked before samples are
    decoded. Raises AudioInputError for out-of-bounds input and ValueError
    (or wave.Error) for malformed input. Call from a worker thread.
    """
    if content_type.startswith("audio/wav") or body[:4] == b"RIFF":
        with wave.open(io.BytesIO(body), "rb") as wav_file:
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                raise ValueError("WAV must be mono PCM16")
            sample_rate = _validated_sample_rate(wav_file.getframerate())
            frame_count = wav_file.getnframes()
            _check_duration(frame_count, sample_rate)
            raw = wav_file.readframes(frame_count)
    else:
        sample_rate = _validated_sample_rate(sample_rate_param or TARGET_SAMPLE_RATE)
        _check_duration(len(body) // 2, sample_rate)
        raw = body
    if len(raw) < 2:
        raise ValueError("audio body is empty")
    if len(raw) % 2:
        raw = raw[:-1]
    pcm = array.array("h")
    pcm.frombytes(raw)
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm.tolist(), sample_rate


async def api_v1_transcribe_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    if request.content_length is not None and request.content_length > MAX_AUDIO_BYTES:
        return web.json_response({"ok": False, "error": "audio body too large"}, status=413)
    audio_request = request.clone(client_max_size=MAX_AUDIO_BYTES + 1)
    try:
        body = await audio_request.read()
    except web.HTTPRequestEntityTooLarge:
        return web.json_response({"ok": False, "error": "audio body too large"}, status=413)
    if len(body) > MAX_AUDIO_BYTES:
        return web.json_response({"ok": False, "error": "audio body too large"}, status=413)

    runtime = _runtime(request)
    if not runtime.stt.available:
        return web.json_response({"ok": False, "error": "no STT provider available"}, status=503)
    async with _speech_semaphore(request):
        try:
            samples, sample_rate = await asyncio.to_thread(
                _decode_audio_body, body, request.content_type or "", request.query.get("sample_rate")
            )
        except AudioInputError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"could not decode audio: {exc}"}, status=400)
        started_ms = time.monotonic() * 1000
        try:
            result = await runtime.stt.transcribe(samples, sample_rate)
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"transcription failed: {exc}"}, status=502)
    transcribe_ms = round((time.monotonic() * 1000) - started_ms, 1)
    _audit(request, f"samples={len(samples)} rate={sample_rate} transcribe_ms={transcribe_ms}")
    return web.json_response({
        "ok": True,
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


async def _reset_adapter_session(adapter: object, client_session_id: str | None) -> str:
    """Drop any cached handle for this client and start a fresh adapter session.

    Used when a stored handle is stale (e.g. the backend was switched via
    /api/configure), so converse can transparently continue rather than fail.
    """
    if client_session_id:
        _api_sessions.pop(client_session_id, None)
    handle = await adapter.start_or_resume_session({"source": "voice_api", "client_session_id": client_session_id})
    if client_session_id:
        _api_sessions[client_session_id] = handle
        while len(_api_sessions) > MAX_API_SESSIONS:
            _api_sessions.pop(next(iter(_api_sessions)), None)
    return handle


async def api_v1_converse_handler(request: web.Request) -> web.StreamResponse:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    try:
        payload = await request.json()
    except web.HTTPRequestEntityTooLarge:
        return web.json_response({"ok": False, "error": "body too large"}, status=413)
    except Exception:
        return web.json_response({"ok": False, "error": "body must be JSON"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "body must be a JSON object"}, status=400)
    raw_text = payload.get("text")
    if not isinstance(raw_text, str):
        return web.json_response({"ok": False, "error": "text must be a string"}, status=400)
    text = raw_text.strip()
    if not text:
        return web.json_response({"ok": False, "error": "text is required"}, status=400)
    if len(text) > MAX_TEXT_CHARS:
        return web.json_response({"ok": False, "error": "text is too long"}, status=413)
    raw_session_id = payload.get("session_id")
    if raw_session_id is not None and not isinstance(raw_session_id, str):
        return web.json_response({"ok": False, "error": "session_id must be a string"}, status=400)
    client_session_id = (raw_session_id or "").strip() or None
    if client_session_id is not None and len(client_session_id) > MAX_SESSION_ID_CHARS:
        return web.json_response({"ok": False, "error": "session_id is too long"}, status=413)

    runtime = _runtime(request)
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
        event_type = event.get("type")
        if not isinstance(event_type, str) or not SSE_EVENT_TYPE_RE.fullmatch(event_type):
            return
        line = f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        await response.write(line.encode("utf-8"))

    _audit(request, f"chars={len(text)} session={_session_log_id(client_session_id)}")
    adapter: object | None = None
    session_handle: str | None = None
    turn_handle: str | None = None
    turn_context = {"source": "voice_api", "modality": "text"}
    try:
        # Everything that can fail runs after the stream is prepared, so the
        # client always gets SSE events, never a plain-text 500.
        adapter, session_handle = await _resolve_adapter_session(runtime, client_session_id)
        try:
            turn_handle = await adapter.submit_user_turn(session_handle, text, turn_context)
        except Exception as exc:
            if not is_unknown_session_error(exc):
                raise  # a transient failure must not discard the conversation
            # Stale adapter session handle (the backend restarted, evicted it,
            # or was switched via /api/configure): start a fresh adapter
            # session and retry once, honoring the "reuse session_id to keep
            # history" contract instead of an opaque failure.
            session_handle = await _reset_adapter_session(adapter, client_session_id)
            turn_handle = await adapter.submit_user_turn(session_handle, text, turn_context)
        await send_event({"type": "turn_accepted", "turn_handle": turn_handle, "session_id": client_session_id})
        saw_final = False
        saw_completed = False
        terminal_failure = False
        buffered = ""
        try:
            # Hard deadline that fires even if the adapter yields nothing: a
            # wedged backend must not pin the SSE request/worker. Mirrors the
            # force-cancel the WS path applies via cancel_active_turn().
            async with asyncio.timeout(CONVERSE_TURN_TIMEOUT_SECONDS):
                async for event in adapter.stream_assistant_output(session_handle, turn_handle):
                    if not isinstance(event, dict):
                        continue
                    event_type = event.get("type")
                    if not isinstance(event_type, str) or not SSE_EVENT_TYPE_RE.fullmatch(event_type):
                        continue  # not a protocol event; never reaches the SSE line
                    if event_type == "assistant_text_delta":
                        delta = event.get("text", "")
                        if not isinstance(delta, str):
                            raise RuntimeError("adapter returned non-text assistant output")
                        if len(buffered) + len(delta) > MAX_GENERATED_TEXT_CHARS:
                            raise RuntimeError("assistant output exceeded the configured limit")
                        buffered += delta
                    elif event_type == "assistant_text_final":
                        final_text = event.get("text", "")
                        if not isinstance(final_text, str):
                            raise RuntimeError("adapter returned non-text assistant output")
                        if len(final_text) > MAX_GENERATED_TEXT_CHARS:
                            raise RuntimeError("assistant output exceeded the configured limit")
                        saw_final = True
                    elif event_type == "turn_completed":
                        saw_completed = True
                        if not saw_final and buffered:
                            # Clients read the final text before completion.
                            await send_event({"type": "assistant_text_final", "text": buffered, "completed_via": "buffer_flush"})
                            saw_final = True
                    elif event_type in {"turn_failed", "cancel_acknowledged"}:
                        terminal_failure = True
                    elif event_type == "assistant_activity":
                        # Re-validate through the protocol-v1 builder so the SSE
                        # surface applies the same trust-boundary normalization the
                        # WS path does (invalid activity_type coerced, progress/
                        # confidence clamped, malformed tool metadata dropped)
                        # instead of forwarding raw adapter output.
                        event = make_activity_event(
                            activity_type=event.get("activity_type", "other"),
                            summary=event.get("summary", ""),
                            progress=event.get("progress"),
                            tool_name=event.get("tool_name"),
                            parameters=event.get("parameters") if isinstance(event.get("parameters"), dict) else None,
                            confidence=event.get("confidence"),
                        )
                    await send_event(event)
                    if terminal_failure or saw_completed:
                        break
        except TimeoutError:
            await send_event({"type": "turn_failed", "message": "turn timed out"})
            terminal_failure = True
            with contextlib.suppress(Exception):
                await adapter.cancel_turn(session_handle, turn_handle)
        if not terminal_failure:
            if not saw_final and buffered:
                await send_event({"type": "assistant_text_final", "text": buffered, "completed_via": "buffer_flush"})
            if not saw_completed:
                await send_event({"type": "turn_completed"})
    except Exception as exc:
        if adapter is not None and session_handle is not None and turn_handle is not None:
            with contextlib.suppress(Exception):
                await adapter.cancel_turn(session_handle, turn_handle)
        with contextlib.suppress(Exception):
            await send_event({"type": "turn_failed", "message": str(exc)})
    with contextlib.suppress(Exception):
        await response.write_eof()
    return response


def mount_voice_api(app: web.Application) -> None:
    app[VOICE_API_SEMAPHORE_KEY] = asyncio.Semaphore(VOICE_API_CONCURRENCY)
    app.router.add_post("/api/v1/speak", api_v1_speak_handler)
    app.router.add_post("/api/v1/transcribe", api_v1_transcribe_handler)
    app.router.add_post("/api/v1/converse", api_v1_converse_handler)
