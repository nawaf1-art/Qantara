from __future__ import annotations

import json
import time

from aiohttp import WSMsgType, web

from discovery.scanner import scan_lan
from gateway.transport_spike.auth import AUTH_TOKEN_KEY, has_valid_bearer_token
from gateway.transport_spike.common import PCM_KIND, TARGET_SAMPLE_RATE
from gateway.transport_spike.runtime import APP_RUNTIME_KEY, GatewayRuntime, Session
from gateway.transport_spike.speech import (
    apply_speech_rate,
    apply_voice_selection,
    apply_voice_transforms,
    cancel_active_turn,
    maybe_run_election_and_claim,
    refresh_adapter_health,
    send_tone,
    start_assistant_turn,
    start_partial_loop,
    stop_partial_loop,
)


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    if not has_valid_bearer_token(request, AUTH_TOKEN_KEY):
        raise web.HTTPUnauthorized()
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024, heartbeat=30.0)
    await ws.prepare(request)
    session = Session(ws, runtime)
    await session.emit("session_created", "gateway", {})
    await session.emit("session_connected", "gateway", {})
    await session.emit("session_ready", "gateway", {"sample_rate": TARGET_SAMPLE_RATE})
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except Exception:
                    await session.emit("recoverable_error", "gateway", {"component": "websocket", "message": "malformed JSON"})
                    continue
                message_type = payload.get("type")
                if message_type == "session_init":
                    session.client_name = payload.get("client_name") or session.client_name
                    session.client_session_id = payload.get("client_session_id") or session.client_session_id
                    session.runtime.register_session(session)
                    apply_speech_rate(session, payload.get("speech_rate"))
                    transform_details = apply_voice_transforms(
                        session,
                        payload.get("voice_pitch"),
                        payload.get("voice_tone"),
                        payload.get("expressiveness"),
                    )
                    voice_details = apply_voice_selection(session, payload.get("voice_id"))
                    session_payload = {"client_name": session.client_name, "client_session_id": session.client_session_id, **voice_details, **transform_details}
                    await session.emit("session_ready", "gateway", session_payload)
                    await ws.send_str(json.dumps({"type": "session_ready", "session_id": session.session_id, "client_session_id": session.client_session_id, "adapter_kind": session.binding.adapter_kind if session.binding else "unknown", "adapter_health": session.binding.health["status"] if session.binding else "unknown", "adapter_detail": session.binding.health["detail"] if session.binding else "health pending", **session_payload}))
                    await refresh_adapter_health(session)
                elif message_type == "session_update":
                    apply_speech_rate(session, payload.get("speech_rate"))
                    transform_details = apply_voice_transforms(
                        session,
                        payload.get("voice_pitch"),
                        payload.get("voice_tone"),
                        payload.get("expressiveness"),
                    )
                    voice_details = apply_voice_selection(session, payload.get("voice_id"))
                    session_payload = {**voice_details, **transform_details}
                    await session.emit("session_updated", "gateway", session_payload)
                    await ws.send_str(json.dumps({"type": "session_updated", **session_payload}))
                elif message_type == "mic_stream_started":
                    await session.emit("mic_stream_started", "browser", {"sample_rate": payload.get("sample_rate", TARGET_SAMPLE_RATE)})
                elif message_type == "mic_stream_stopped":
                    await session.emit("mic_stream_stopped", "browser", {})
                elif message_type == "request_tone":
                    await session.emit("assistant_output_started", "gateway", {"kind": "synthetic_tone"})
                    await send_tone(session)
                    await session.emit("assistant_output_completed", "gateway", {"kind": "synthetic_tone"})
                elif message_type == "clear_playback":
                    session.playback_generation += 1
                    session.speech_generation += 1
                    await session.emit("playback_queue_cleared", "browser", {})
                    await cancel_active_turn(session, "playback_cleared")
                    await ws.send_str(json.dumps({"type": "playback_cleared", "generation": session.playback_generation}))
                elif message_type in {"submit_mock_turn", "submit_turn"}:
                    transcript = payload.get("text", "").strip()
                    if transcript:
                        await start_assistant_turn(session, transcript)
                    else:
                        await session.emit("recoverable_error", "gateway", {"component": "control", "message": "empty mock turn"})
                elif message_type == "transcribe_recent_audio":
                    await session.emit("transcription_requested", "browser", {"available_samples": len(session.recent_pcm), "engine": session.runtime.stt.kind if session.runtime.stt.available else "fallback", "submit_turn": bool(payload.get("submit_turn"))})
                    if not session.recent_pcm:
                        await session.websocket.send_str(json.dumps({"type": "transcript_result", "text": "", "engine": "none"}))
                    elif session.runtime.stt.available:
                        try:
                            from gateway.transport_spike.language_resolution import resolve_effective_language
                            stt_result = await session.runtime.stt.transcribe(session.recent_pcm, TARGET_SAMPLE_RATE)
                            text = stt_result.text if hasattr(stt_result, "text") else str(stt_result)
                            detected_language = getattr(stt_result, "language", None)
                            language_probability = getattr(stt_result, "language_probability", None)
                            duration_ms = 1000.0 * len(session.recent_pcm) / max(TARGET_SAMPLE_RATE, 1)
                            effective_language = resolve_effective_language(
                                detected=detected_language,
                                probability=language_probability,
                                duration_ms=duration_ms,
                                primary_language=session.primary_language,
                                transcript=text,
                            )
                            session.input_language = effective_language
                            await session.emit("final_transcript_ready", "speech", {"char_count": len(text), "engine": session.runtime.stt.kind, "language": effective_language, "detected_language": detected_language, "language_probability": language_probability})
                            await session.websocket.send_str(json.dumps({"type": "transcript_result", "text": text, "engine": session.runtime.stt.kind, "language": effective_language, "detected_language": detected_language}))
                            if payload.get("submit_turn") and text.strip():
                                if getattr(session, "mesh_should_respond", True):
                                    await start_assistant_turn(session, text.strip())
                                else:
                                    await session.emit(
                                        "turn_deferred_to_peer", "session",
                                        {"reason": "mesh_election_lost"},
                                    )
                                    await session.websocket.send_str(json.dumps({
                                        "type": "turn_deferred_to_peer",
                                    }))
                            session.recent_pcm.clear()
                        except Exception as exc:
                            await session.emit("recoverable_error", "speech", {"component": "stt", "message": str(exc), "engine": session.runtime.stt.kind})
                            await session.websocket.send_str(json.dumps({"type": "transcript_result", "text": "", "engine": session.runtime.stt.kind, "error": str(exc)}))
                    else:
                        fallback = f"[stt unavailable] captured {len(session.recent_pcm)} samples"
                        await session.emit("final_transcript_ready", "speech", {"char_count": len(fallback), "engine": "fallback"})
                        await session.websocket.send_str(json.dumps({"type": "transcript_result", "text": fallback, "engine": "fallback"}))
                        session.recent_pcm.clear()
                elif message_type == "endpoint_candidate":
                    await session.emit("endpoint_timer_started", "browser", {"silence_ms": payload.get("silence_ms")})
                elif message_type == "vad_state":
                    new_state = payload.get("state", "unknown")
                    previous_state = session.last_vad_state
                    session.last_vad_state = new_state
                    if new_state == "speech":
                        await session.emit("speech_start_detected", "browser", {"state": new_state, "rms": payload.get("rms")})
                        if previous_state != "speech":
                            await session.set_state("listening", reason="speech_start_detected")
                            start_partial_loop(session)
                            # Mesh election: if another peer wins, mark this
                            # session as non-responder for the current turn.
                            local_rms = float(payload.get("rms") or 0.0)
                            session.mesh_should_respond = await maybe_run_election_and_claim(session, local_rms)
                    else:
                        await session.emit("speech_end_detected", "browser", {"state": new_state, "rms": payload.get("rms")})
                        if previous_state == "speech":
                            stop_partial_loop(session)
                else:
                    await session.emit("recoverable_error", "gateway", {"component": "control", "message": f"unknown control {message_type}"})
            elif msg.type == WSMsgType.BINARY:
                if not msg.data:
                    continue
                if msg.data[0] != PCM_KIND:
                    await session.emit("recoverable_error", "gateway", {"component": "transport", "message": f"unknown binary kind {msg.data[0]}"})
                    continue
                session.frames_in += 1
                samples = (len(msg.data) - 1) // 2
                for i in range(1, len(msg.data), 2):
                    session.recent_pcm.append(int.from_bytes(msg.data[i:i + 2], "little", signed=True))
                if len(session.recent_pcm) > session.recent_pcm_limit:
                    session.recent_pcm = session.recent_pcm[-session.recent_pcm_limit:]
                await session.emit("input_audio_frame_received", "gateway", {"frame_index": session.frames_in, "frame_bytes": len(msg.data), "frame_samples": samples, "sample_rate": TARGET_SAMPLE_RATE})
            elif msg.type == WSMsgType.ERROR:
                await session.emit("terminal_error", "gateway", {"message": str(ws.exception())})
    finally:
        stop_partial_loop(session)
        await cancel_active_turn(session, "socket_disconnected")
        if session.current_turn_task is not None and not session.current_turn_task.done():
            session.current_turn_task.cancel()
        runtime.release_session(session)
        close_payload = {"close_code": ws.close_code, "exception": str(ws.exception()) if ws.exception() else "", "session_duration_ms": round((time.monotonic() * 1000) - session.started_monotonic_ms, 3)}
        await session.emit("socket_disconnected", "gateway", close_payload)
        await session.emit("session_closed", "gateway", {**close_payload, "frames_in": session.frames_in, "frames_out": session.frames_out, "turns_completed": session.turns_completed, "playback_generation": session.playback_generation})
    return ws


async def api_discovery_scan_handler(request: web.Request) -> web.StreamResponse:
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
