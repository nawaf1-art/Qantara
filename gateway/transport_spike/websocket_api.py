from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any

from aiohttp import WSCloseCode, WSMsgType, web

from discovery.scanner import scan_lan
from gateway.transport_spike.auth import AUTH_TOKEN_KEY, has_valid_auth_token, require_bearer_token
from gateway.transport_spike.common import PCM_KIND, TARGET_SAMPLE_RATE
from gateway.transport_spike.runtime import APP_RUNTIME_KEY, GatewayRuntime, Session
from gateway.transport_spike.speech import (
    apply_speech_rate,
    apply_voice_selection,
    apply_voice_transforms,
    cancel_active_turn,
    maybe_run_election_and_claim,
    refresh_adapter_health,
    request_turn_cancel,
    safe_send_str,
    send_tone,
    start_assistant_turn,
    start_partial_loop,
    stop_partial_loop,
)

MAX_WEBSOCKET_MESSAGE_BYTES = 256 * 1024
MAX_CONTROL_MESSAGE_CHARS = 64 * 1024
MAX_AUDIO_FRAME_BYTES = 64 * 1024 + 1
MAX_USER_TEXT_CHARS = 16 * 1024
MAX_CLIENT_IDENTIFIER_CHARS = 256
MAX_VAD_STATE_CHARS = 32
# A voice turn waits at most this long for a still-running mesh election
# before answering anyway (a slow or unreachable peer must not mute us).
MESH_ELECTION_SUBMIT_DEADLINE_SECONDS = 0.3
NUMERIC_SESSION_FIELDS = ("speech_rate", "voice_pitch", "expressiveness")


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    if not has_valid_auth_token(request, AUTH_TOKEN_KEY):
        raise web.HTTPUnauthorized()
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    if not runtime.reserve_websocket_connection():
        raise web.HTTPServiceUnavailable(text="websocket connection limit reached")
    try:
        return await _serve_websocket(request, runtime)
    finally:
        runtime.release_websocket_connection()


async def _serve_websocket(
    request: web.Request,
    runtime: GatewayRuntime,
) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(max_msg_size=MAX_WEBSOCKET_MESSAGE_BYTES, heartbeat=30.0)
    await ws.prepare(request)
    return await run_websocket_session(ws, runtime)


async def _control_error(session: Session, message: str, component: str = "control") -> None:
    await session.emit("recoverable_error", "gateway", {"component": component, "message": message})


def _finite_number(value: Any) -> float | None:
    """Return ``value`` as a finite float, or None if it is not one."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


async def _sanitize_numeric_fields(session: Session, payload: dict) -> dict:
    """Drop non-finite or non-numeric session fields ("nan", "inf", "x"),
    reporting each as a recoverable error instead of storing it (SP-13)."""
    clean = dict(payload)
    for name in NUMERIC_SESSION_FIELDS:
        if name not in clean or clean[name] is None:
            continue
        if _finite_number(clean[name]) is None:
            clean.pop(name)
            await _control_error(session, f"invalid {name}: must be a finite number")
    return clean


def _start_mesh_election(session: Session, local_rms: float) -> None:
    """Run the mesh election in the background so the receive loop keeps
    processing audio (Q-12 / LC-9); the turn submit waits for it with a
    bounded deadline."""
    previous = session.mesh_election_task
    if previous is not None and not previous.done():
        previous.cancel()
    if session.runtime.mesh_controller is None:
        session.mesh_election_task = None
        session.mesh_should_respond = True
        return

    async def _elect() -> bool:
        should_claim = await maybe_run_election_and_claim(session, local_rms)
        session.mesh_should_respond = should_claim
        return should_claim

    session.mesh_election_task = session.runtime.retain_task(asyncio.create_task(_elect()))


async def _mesh_allows_response(session: Session) -> bool:
    task = session.mesh_election_task
    if task is None:
        return getattr(session, "mesh_should_respond", True)
    if not task.done():
        done, _pending = await asyncio.wait({task}, timeout=MESH_ELECTION_SUBMIT_DEADLINE_SECONDS)
        if not done:
            await session.emit("mesh_election_timeout", "session", {"session_id": session.session_id, "deadline_ms": MESH_ELECTION_SUBMIT_DEADLINE_SECONDS * 1000})
            return True
    if task.cancelled() or task.exception() is not None:
        return True
    return bool(task.result())


def _typed_turn_language(session: Session, text: str) -> str | None:
    """Language for a typed turn: from the text itself, never inherited from
    the previous voice turn (V-9). None means the primary language."""
    try:
        from gateway.transport_spike.language_resolution import resolve_effective_language

        language = resolve_effective_language(
            detected=None,
            probability=None,
            duration_ms=0.0,
            primary_language=session.primary_language,
            transcript=text,
        )
    except Exception:
        return None
    return None if language == session.primary_language else language


async def _handle_session_fields(session: Session, payload: dict) -> dict:
    payload = await _sanitize_numeric_fields(session, payload)
    apply_speech_rate(session, payload.get("speech_rate"))
    transform_details = apply_voice_transforms(
        session,
        payload.get("voice_pitch"),
        payload.get("voice_tone"),
        payload.get("expressiveness"),
    )
    voice_details = apply_voice_selection(session, payload.get("voice_id"))
    return {**voice_details, **transform_details}


async def _handle_vad_state(session: Session, payload: dict) -> None:
    new_state = payload.get("state", "unknown")
    if not isinstance(new_state, str) or len(new_state) > MAX_VAD_STATE_CHARS:
        await _control_error(session, "invalid vad state")
        return
    raw_rms = payload.get("rms")
    rms = 0.0
    if raw_rms is not None:
        parsed = _finite_number(raw_rms)
        if parsed is None:
            await _control_error(session, "invalid rms: must be a finite number")
            raw_rms = None
        else:
            rms = parsed
    previous_state = session.last_vad_state
    session.last_vad_state = new_state
    if new_state == "speech":
        session.utterance.speech_started()
        await session.emit("speech_start_detected", "browser", {"state": new_state, "rms": raw_rms})
        if previous_state != "speech":
            await session.set_state("listening", reason="speech_start_detected")
            start_partial_loop(session)
            _start_mesh_election(session, rms)
    else:
        session.utterance.speech_ended()
        await session.emit("speech_end_detected", "browser", {"state": new_state, "rms": raw_rms})
        if previous_state == "speech":
            stop_partial_loop(session)


async def _handle_control(session: Session, ws: Any, payload: dict, message_type: str) -> bool:
    """Handle one control message. Returns False to close the socket."""
    if message_type == "session_init":
        client_name = payload.get("client_name")
        client_session_id = payload.get("client_session_id")
        if (
            client_name is not None
            and (not isinstance(client_name, str) or len(client_name) > MAX_CLIENT_IDENTIFIER_CHARS)
        ) or (
            client_session_id is not None
            and (
                not isinstance(client_session_id, str)
                or len(client_session_id) > MAX_CLIENT_IDENTIFIER_CHARS
            )
        ):
            await _control_error(session, "client identifier is invalid")
            return True
        session.client_name = client_name or session.client_name
        session.client_session_id = client_session_id or session.client_session_id
        session.runtime.register_session(session)
        session_fields = await _handle_session_fields(session, payload)
        session_payload = {"client_name": session.client_name, "client_session_id": session.client_session_id, **session_fields}
        await session.emit("session_ready", "gateway", session_payload)
        await ws.send_str(json.dumps({"type": "session_ready", "session_id": session.session_id, "client_session_id": session.client_session_id, "adapter_kind": session.binding.adapter_kind if session.binding else "unknown", "adapter_health": session.binding.health["status"] if session.binding else "unknown", "adapter_detail": session.binding.health["detail"] if session.binding else "health pending", **session_payload}))
        await refresh_adapter_health(session)
    elif message_type == "session_update":
        session_payload = await _handle_session_fields(session, payload)
        await session.emit("session_updated", "gateway", session_payload)
        await ws.send_str(json.dumps({"type": "session_updated", **session_payload}))
    elif message_type == "mic_stream_started":
        session.utterance.stream_started()
        sample_rate = payload.get("sample_rate", TARGET_SAMPLE_RATE)
        await session.emit("mic_stream_started", "browser", {"sample_rate": sample_rate if _finite_number(sample_rate) is not None else None})
    elif message_type == "mic_stream_stopped":
        session.utterance.stream_stopped()
        await session.emit("mic_stream_stopped", "browser", {})
    elif message_type == "request_tone":
        await session.emit("assistant_output_started", "gateway", {"kind": "synthetic_tone"})
        await send_tone(session)
        await session.emit("assistant_output_completed", "gateway", {"kind": "synthetic_tone"})
    elif message_type == "clear_playback":
        session.playback_generation += 1
        session.speech_generation += 1
        await session.emit("playback_queue_cleared", "browser", {})
        # Claim the cancel synchronously and let its teardown (adapter
        # cancel, grace window, force-cancel) run in the background: the
        # receive loop must keep processing the user's barge-in audio (V-10).
        request_turn_cancel(session, "playback_cleared")
        await ws.send_str(json.dumps({"type": "playback_cleared", "generation": session.playback_generation}))
    elif message_type in {"submit_mock_turn", "submit_turn"}:
        raw_transcript = payload.get("text", "")
        transcript = raw_transcript.strip() if isinstance(raw_transcript, str) else ""
        if len(transcript) > MAX_USER_TEXT_CHARS:
            await _control_error(session, "turn text too large")
        elif transcript:
            session.input_language = _typed_turn_language(session, transcript)
            await start_assistant_turn(session, transcript)
        else:
            await _control_error(session, "empty mock turn")
    elif message_type == "transcribe_recent_audio":
        await transcribe_utterance(session, bool(payload.get("submit_turn")))
    elif message_type == "endpoint_candidate":
        silence_ms = payload.get("silence_ms")
        await session.emit("endpoint_timer_started", "browser", {"silence_ms": silence_ms if _finite_number(silence_ms) is not None else None})
    elif message_type == "vad_state":
        await _handle_vad_state(session, payload)
    else:
        await _control_error(session, f"unknown control {message_type}")
    return True


async def run_websocket_session(ws: Any, runtime: GatewayRuntime) -> Any:
    """Serve one browser session over an already-prepared WebSocket."""
    session = Session(ws, runtime)
    await session.emit("session_created", "gateway", {})
    await session.emit("session_connected", "gateway", {})
    await session.emit("session_ready", "gateway", {"sample_rate": TARGET_SAMPLE_RATE})
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                if len(msg.data) > MAX_CONTROL_MESSAGE_CHARS:
                    await _control_error(session, "control message too large", component="websocket")
                    await ws.close(code=WSCloseCode.MESSAGE_TOO_BIG, message=b"control message too large")
                    break
                try:
                    payload = json.loads(msg.data)
                except Exception:
                    await _control_error(session, "malformed JSON", component="websocket")
                    continue
                if not isinstance(payload, dict):
                    await _control_error(session, "control message must be an object", component="websocket")
                    continue
                message_type = payload.get("type")
                if not isinstance(message_type, str) or len(message_type) > 64:
                    await _control_error(session, "invalid control type")
                    continue
                try:
                    await _handle_control(session, ws, payload, message_type)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # A malformed field must cost the client one message, not
                    # the whole socket (LC-11).
                    await _control_error(session, f"{message_type} failed: {type(exc).__name__}")
            elif msg.type == WSMsgType.BINARY:
                if not msg.data:
                    continue
                if len(msg.data) > MAX_AUDIO_FRAME_BYTES:
                    await _control_error(session, "audio frame too large", component="transport")
                    await ws.close(code=WSCloseCode.MESSAGE_TOO_BIG, message=b"audio frame too large")
                    break
                if msg.data[0] != PCM_KIND:
                    await _control_error(session, f"unknown binary kind {msg.data[0]}", component="transport")
                    continue
                if (len(msg.data) - 1) % 2:
                    await _control_error(session, "malformed PCM16 frame", component="transport")
                    continue
                session.frames_in += 1
                samples = (len(msg.data) - 1) // 2
                session.utterance.append_pcm(memoryview(msg.data)[1:])
                await session.emit("input_audio_frame_received", "gateway", {"frame_index": session.frames_in, "frame_bytes": len(msg.data), "frame_samples": samples, "sample_rate": TARGET_SAMPLE_RATE})
            elif msg.type == WSMsgType.ERROR:
                await session.emit("terminal_error", "gateway", {"message": str(ws.exception())})
    finally:
        stop_partial_loop(session)
        if session.mesh_election_task is not None and not session.mesh_election_task.done():
            session.mesh_election_task.cancel()
        await cancel_active_turn(session, "socket_disconnected")
        if session.current_turn_task is not None and not session.current_turn_task.done():
            session.current_turn_task.cancel()
        runtime.release_session(session)
        close_payload = {"close_code": ws.close_code, "exception": str(ws.exception()) if ws.exception() else "", "session_duration_ms": round((time.monotonic() * 1000) - session.started_monotonic_ms, 3)}
        await session.emit("socket_disconnected", "gateway", close_payload)
        await session.emit("session_closed", "gateway", {**close_payload, "frames_in": session.frames_in, "frames_out": session.frames_out, "turns_completed": session.turns_completed, "playback_generation": session.playback_generation})
    return ws


async def transcribe_utterance(session: Session, submit_turn: bool) -> None:
    """Transcribe the current utterance (Q-01) and optionally submit it."""
    stt = session.runtime.stt
    available_samples = len(session.utterance)
    await session.emit("transcription_requested", "browser", {"available_samples": available_samples, "engine": stt.kind if stt.available else "fallback", "submit_turn": submit_turn})
    if not available_samples:
        await safe_send_str(session, {"type": "transcript_result", "text": "", "engine": "none"})
        return
    samples, speech_ms = session.utterance.take()
    if not stt.available:
        fallback = f"[stt unavailable] captured {len(samples)} samples"
        await session.emit("final_transcript_ready", "speech", {"char_count": len(fallback), "engine": "fallback"})
        await safe_send_str(session, {"type": "transcript_result", "text": fallback, "engine": "fallback"})
        return
    try:
        from gateway.transport_spike.language_resolution import resolve_effective_language

        stt_result = await stt.transcribe(samples.tolist(), TARGET_SAMPLE_RATE)
        text = stt_result.text if hasattr(stt_result, "text") else str(stt_result)
        detected_language = getattr(stt_result, "language", None)
        language_probability = getattr(stt_result, "language_probability", None)
        effective_language = resolve_effective_language(
            detected=detected_language,
            probability=language_probability,
            duration_ms=speech_ms,
            primary_language=session.primary_language,
            transcript=text,
        )
        session.input_language = effective_language
        await session.emit("final_transcript_ready", "speech", {"char_count": len(text), "engine": stt.kind, "language": effective_language, "detected_language": detected_language, "language_probability": language_probability, "speech_ms": round(speech_ms, 1), "audio_ms": round(1000.0 * len(samples) / TARGET_SAMPLE_RATE, 1)})
        await safe_send_str(session, {"type": "transcript_result", "text": text, "engine": stt.kind, "language": effective_language, "detected_language": detected_language})
    except Exception as exc:
        await session.emit("recoverable_error", "speech", {"component": "stt", "message": str(exc), "engine": stt.kind})
        await safe_send_str(session, {"type": "transcript_result", "text": "", "engine": stt.kind, "error": str(exc)})
        return
    if submit_turn and text.strip():
        if await _mesh_allows_response(session):
            await start_assistant_turn(session, text.strip())
        else:
            await session.emit("turn_deferred_to_peer", "session", {"reason": "mesh_election_lost"})
            await safe_send_str(session, {"type": "turn_deferred_to_peer"})


async def api_discovery_scan_handler(request: web.Request) -> web.StreamResponse:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive"})
    await response.prepare(request)

    async def send_event(event_type: str, data: dict) -> None:
        payload = json.dumps(data).encode("utf-8")
        await response.write(b"event: " + event_type.encode() + b"\ndata: " + payload + b"\n\n")

    try:
        await scan_lan(progress_callback=send_event)
    except Exception as exc:
        await send_event("error", {"message": str(exc)})
    await response.write_eof()
    return response
