from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import unicodedata

from gateway.transport_spike.common import (
    FRAME_SAMPLES,
    PCM_KIND,
    TARGET_SAMPLE_RATE,
    TONE_HZ,
    TONE_SECONDS,
)
from gateway.transport_spike.runtime import Session
from providers.stt.base import STTProvider

PARTIAL_TICK_INTERVAL_SEC = 0.4


def should_enable_partials() -> bool:
    override = os.environ.get("QANTARA_STT_STREAMING", "auto").strip().lower()
    if override in {"on", "1", "true", "yes"}:
        return True
    if override in {"off", "0", "false", "no"}:
        return False
    # auto: trust the configured Whisper device as the best local signal —
    # GPU/Apple Silicon users have the headroom for re-transcribing every tick
    device = os.environ.get("QANTARA_WHISPER_DEVICE", "cpu").strip().lower()
    return device in {"cuda", "mps", "gpu"}


async def compute_partial_transcript(
    stt: STTProvider,
    samples: list[int],
    sample_rate: int,
    prev_text: str,
) -> tuple[str, int] | None:
    if not samples or not stt.supports_partial:
        return None
    try:
        partial_result = await stt.transcribe_partial(samples, sample_rate)
    except Exception:
        return None
    text = partial_result.text if hasattr(partial_result, "text") else str(partial_result)
    if not text or text == prev_text:
        return None
    stable_chars = 0
    for a, b in zip(prev_text, text, strict=False):
        if a == b:
            stable_chars += 1
        else:
            break
    return text, stable_chars


async def _partial_tick_loop(session: Session, tick_interval_sec: float) -> None:
    stt = session.runtime.stt
    try:
        while True:
            await asyncio.sleep(tick_interval_sec)
            result = await compute_partial_transcript(
                stt,
                list(session.recent_pcm),
                TARGET_SAMPLE_RATE,
                session.partial_last_text,
            )
            if result is None:
                continue
            text, stable_chars = result
            session.partial_last_text = text
            ms_since_start = (
                round((time.monotonic() * 1000) - session.speech_started_ms, 3)
                if session.speech_started_ms is not None
                else 0.0
            )
            payload = {
                "text": text,
                "ms_since_speech_start": ms_since_start,
                "stable_prefix_chars": stable_chars,
                "provider_kind": stt.kind,
            }
            await session.emit("partial_transcript_ready", "speech", payload)
            await safe_send_str(session, {"type": "partial_transcript_ready", **payload})
    except asyncio.CancelledError:
        pass


def start_partial_loop(
    session: Session,
    tick_interval_sec: float = PARTIAL_TICK_INTERVAL_SEC,
) -> None:
    if not should_enable_partials():
        return
    if not session.runtime.stt.supports_partial:
        return
    stop_partial_loop(session)
    session.speech_started_ms = time.monotonic() * 1000
    session.partial_last_text = ""
    session.partial_task = asyncio.create_task(_partial_tick_loop(session, tick_interval_sec))


def stop_partial_loop(session: Session) -> None:
    task = session.partial_task
    session.partial_task = None
    session.partial_last_text = ""
    session.speech_started_ms = None
    if task is not None and not task.done():
        task.cancel()


async def maybe_run_election_and_claim(session: Session, local_rms: float) -> bool:
    """Ask the mesh controller (if any) to elect a responder for this
    utterance. Returns True if this node should claim and proceed with
    the turn; False if another peer is taking it.

    When mesh is disabled, always returns True — single-node install."""
    controller = session.runtime.mesh_controller
    if controller is None:
        return True
    peer_count = len(controller.registry.list_peers())
    await session.emit("mesh_election_started", "session", {
        "session_id": session.session_id,
        "local_rms": local_rms,
        "peer_count": peer_count,
    })
    outcome = await controller.run_election(
        session_id=session.session_id,
        local_rms=local_rms,
    )
    await session.emit("mesh_election_resolved", "session", {
        "session_id": session.session_id,
        "winner_node_id": outcome.winner_node_id,
        "should_claim": outcome.should_claim,
        "window_ms": 150,
        "local_rms": local_rms,
        "peer_count": peer_count,
    })
    return outcome.should_claim


def websocket_is_writable(session: Session) -> bool:
    return not session.websocket.closed


async def safe_send_str(session: Session, payload: dict) -> bool:
    if not websocket_is_writable(session):
        return False
    try:
        await session.websocket.send_str(json.dumps(payload))
        return True
    except Exception:
        return False


async def safe_send_bytes(session: Session, payload: bytes) -> bool:
    if not websocket_is_writable(session):
        return False
    try:
        await session.websocket.send_bytes(payload)
        return True
    except Exception:
        return False


def encode_pcm_frame(samples: list[int]) -> bytes:
    import struct

    return struct.pack(f"<B{len(samples)}h", PCM_KIND, *samples)


def normalize_tts_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized
    normalized = normalized.replace("\r", "\n")
    normalized = re.sub(r"`([^`]*)`", r"\1", normalized)
    normalized = normalized.replace("**", "").replace("__", "").replace("*", "")
    normalized = re.sub(r"(?m)^\s*[-•]\s+", "", normalized)
    normalized = normalized.replace(" - ", ". ").replace("\n- ", ". ").replace("\n", ". ")
    normalized = re.sub(r"([A-Za-z0-9])\s*/\s*([A-Za-z0-9])", r"\1 or \2", normalized)
    normalized = re.sub(r"([+-])\s*(\d+)\s*°\s*C", lambda m: f"{'minus' if m.group(1) == '-' else 'plus'} {m.group(2)} degrees Celsius", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d+)\s*°\s*C", r"\1 degrees Celsius", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d+)\s*km/h", r"\1 kilometers per hour", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d+(?:\.\d+)?)\s*mm", r"\1 millimeters", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", normalized)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "So")
    normalized = normalized.replace("↘", " ")
    normalized = re.sub(r"[|]+", ". ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"([!?.,]){2,}", r"\1", normalized)
    normalized = re.sub(r"\s+([!?.,])", r"\1", normalized)
    return normalized.strip()


def _clamp_unit_interval(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _clamp_speech_rate(value: float) -> float:
    return max(0.85, min(1.30, value))


def _voice_default_rate(resolved_voice) -> float:
    defaults = dict(getattr(resolved_voice, "defaults", {}) or {})
    try:
        return _clamp_speech_rate(float(defaults.get("rate", 1.0)))
    except (TypeError, ValueError):
        return 1.0


def effective_speech_rate_for_voice(session: Session, resolved_voice) -> float:
    voice_baseline = _voice_default_rate(resolved_voice) if resolved_voice is not None else 1.0
    return _clamp_speech_rate(session.speech_rate * voice_baseline)


def _build_transform_status(session: Session, resolved_voice, active_rate: float | None = None) -> tuple[dict, list[str]]:
    defaults = dict(getattr(resolved_voice, "defaults", {}) or {})
    allowed = list(getattr(resolved_voice, "allowed_transforms", []) or [])
    ignored: list[str] = []
    if "pitch" not in allowed and abs(session.voice_pitch) > 1e-9:
        ignored.append("pitch")
    if "tone" not in allowed and session.voice_tone not in {"", "neutral"}:
        ignored.append("tone")
    if "expressiveness" not in allowed and session.expressiveness is not None:
        ignored.append("expressiveness")
    active: dict[str, object] = {
        "rate": active_rate if active_rate is not None else session.speech_rate,
        "pitch": session.voice_pitch,
        "tone": session.voice_tone,
    }
    if "expressiveness" in allowed and session.expressiveness is not None:
        active["expressiveness"] = session.expressiveness
    return {
        "voice_defaults": defaults,
        "allowed_transforms": allowed,
        "active_transforms": active,
    }, ignored


def _available_voice_ids(session: Session) -> set[str]:
    try:
        return {
            str(voice.get("voice_id"))
            for voice in session.runtime.tts.list_available_voices()
            if voice.get("voice_id")
        }
    except Exception:
        return set()


def _available_voice_catalog(session: Session) -> dict[str, dict]:
    try:
        return {
            str(voice.get("voice_id")): voice
            for voice in session.runtime.tts.list_available_voices()
            if voice.get("voice_id")
        }
    except Exception:
        return {}


def _voice_matches_language(voice: dict | None, language: str) -> bool:
    if not voice:
        return False
    locale = str(voice.get("locale") or "").strip().lower()
    return locale == language.lower() or locale.startswith(f"{language.lower()}-")


def resolve_turn_voice_id(session: Session, output_language: str | None) -> str | None:
    if not output_language:
        return session.voice_id
    catalog = _available_voice_catalog(session)
    for candidate in (session.requested_voice_id, session.voice_id):
        if candidate and _voice_matches_language(catalog.get(candidate), output_language):
            return candidate
    try:
        from gateway.transport_spike.languages_catalog import PREFERRED_VOICE_PER_LANGUAGE
        preferred = PREFERRED_VOICE_PER_LANGUAGE.get(output_language)
    except Exception:
        preferred = None
    if preferred and preferred in _available_voice_ids(session):
        return preferred
    return session.voice_id


def resolve_turn_output_language(session: Session, active_mode: str | None) -> str | None:
    if active_mode in {"directional", "live"} and session.translation_target:
        return session.translation_target
    if session.input_language:
        return session.input_language
    return session.primary_language


async def send_tone(session: Session) -> None:
    generation = session.playback_generation
    total_samples = int(TARGET_SAMPLE_RATE * TONE_SECONDS)
    await session.emit("playback_started", "playback", {"kind": "synthetic_tone"})
    sent_any = False
    first_frame_sent = False
    for offset in range(0, total_samples, FRAME_SAMPLES):
        if generation != session.playback_generation:
            await safe_send_str(session, {"type": "playback_stopped", "reason": "cleared", "kind": "synthetic_tone"})
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
            return
        frame = [int(0.22 * 32767 * math.sin(2 * math.pi * TONE_HZ * (i / TARGET_SAMPLE_RATE))) for i in range(offset, min(offset + FRAME_SAMPLES, total_samples))]
        if not await safe_send_bytes(session, encode_pcm_frame(frame)):
            return
        session.frames_out += 1
        sent_any = True
        if not first_frame_sent:
            first_frame_sent = True
            await safe_send_str(session, {"type": "playback_metrics", "engine": "synthetic", "kind": "synthetic_tone", "tts_to_first_audio_ms": 0, "synthesis_ms": 0})
            await session.emit("playback_first_frame_sent", "playback", {"kind": "synthetic_tone", "tts_to_first_audio_ms": 0})
        await session.emit("output_audio_frame_sent", "playback", {"frame_index": session.frames_out, "frame_samples": len(frame), "sample_rate": TARGET_SAMPLE_RATE})
        await asyncio.sleep(len(frame) / TARGET_SAMPLE_RATE)
    if sent_any:
        await safe_send_str(session, {"type": "playback_stopped", "reason": "tone_complete", "kind": "synthetic_tone"})
        await session.emit("playback_stopped", "playback", {"reason": "tone_complete"})


async def send_pcm_samples(session: Session, samples: list[int], sample_rate: int, kind: str, engine: str | None = None, tts_started_ms: float | None = None, synthesis_ms: float | None = None, expected_generation: int | None = None) -> None:
    generation = session.playback_generation if expected_generation is None else expected_generation
    if generation != session.playback_generation:
        return
    await session.emit("playback_started", "playback", {"kind": kind, "sample_rate": sample_rate})
    sent_any = False
    first_frame_sent = False
    for offset in range(0, len(samples), FRAME_SAMPLES):
        if generation != session.playback_generation:
            await safe_send_str(session, {"type": "playback_stopped", "reason": "cleared", "kind": kind})
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
            return
        frame = samples[offset:offset + FRAME_SAMPLES]
        if not await safe_send_bytes(session, encode_pcm_frame(frame)):
            return
        session.frames_out += 1
        sent_any = True
        if not first_frame_sent:
            first_frame_sent = True
            first_audio_ms = round((time.monotonic() * 1000) - tts_started_ms, 3) if tts_started_ms is not None else None
            await safe_send_str(session, {"type": "playback_metrics", "engine": engine or "synthetic", "kind": kind, "tts_to_first_audio_ms": first_audio_ms, "synthesis_ms": synthesis_ms})
            await session.emit("playback_first_frame_sent", "playback", {"kind": kind, "tts_to_first_audio_ms": first_audio_ms, "synthesis_ms": synthesis_ms})
            if session.state == "thinking":
                await session.set_state("speaking", reason="playback_first_frame_sent")
            if session.current_turn_phase == "thinking":
                session.current_turn_phase = "speaking"
        await session.emit("output_audio_frame_sent", "playback", {"frame_index": session.frames_out, "frame_samples": len(frame), "sample_rate": sample_rate, "kind": kind})
        await asyncio.sleep(len(frame) / sample_rate)
    if sent_any:
        reason = f"{kind}_complete"
        await safe_send_str(session, {"type": "playback_stopped", "reason": reason, "kind": kind})
        await session.emit("playback_stopped", "playback", {"reason": reason})


async def refresh_adapter_health(session: Session | None = None) -> None:
    if session is None or session.binding is None:
        return
    health = await session.runtime.refresh_binding_health(session.binding)
    try:
        await session.websocket.send_str(json.dumps({"type": "adapter_status", "adapter_kind": session.binding.adapter_kind, "adapter_health": health["status"], "adapter_detail": health["detail"]}))
    except Exception:
        pass


async def ensure_adapter_session(session: Session) -> None:
    if session.binding is None:
        session.runtime.register_session(session)
    if session.runtime_session_handle is None:
        session.runtime_session_handle = await session.binding.adapter.start_or_resume_session({"client_name": session.client_name, "session_id": session.session_id, "client_session_id": session.client_session_id, "voice_id": session.voice_id})
        session.runtime.save_session_state(session)
        health = await session.runtime.refresh_binding_health(session.binding)
        await session.emit("adapter_session_ready", "adapter", {"runtime_session_handle": session.runtime_session_handle, "adapter_kind": session.binding.adapter_kind, "adapter_health": health["status"]})


def clear_turn_state(session: Session) -> None:
    session.current_turn_handle = None
    session.current_turn_task = None


async def emit_turn_state(session: Session, state: str, reason: str | None = None) -> None:
    payload = {"type": "turn_state", "state": state}
    if reason:
        payload["reason"] = reason
    await safe_send_str(session, payload)


def apply_voice_selection(session: Session, requested_voice_id: str | None) -> dict:
    tts = session.runtime.tts
    session.requested_voice_id = requested_voice_id or session.requested_voice_id or tts.default_voice_id
    fallback_reason = None
    resolved_voice = None
    try:
        resolved_voice, fallback_reason = tts.resolve_voice(session.requested_voice_id)
        session.voice_id = resolved_voice.voice_id
    except Exception:
        session.voice_id = None
    session.runtime.save_session_state(session)
    active_rate = effective_speech_rate_for_voice(session, resolved_voice)
    transform_status, ignored_transforms = _build_transform_status(session, resolved_voice, active_rate=active_rate) if resolved_voice is not None else ({"voice_defaults": {}, "allowed_transforms": [], "active_transforms": {"rate": active_rate, "pitch": session.voice_pitch, "tone": session.voice_tone}}, [])
    return {
        "requested_voice_id": session.requested_voice_id,
        "voice_id": session.voice_id,
        "speech_rate": session.speech_rate,
        "sample_rate": resolved_voice.sample_rate if resolved_voice is not None else None,
        **transform_status,
        "ignored_transforms": ignored_transforms,
        "available_voices": tts.list_available_voices(),
        "fallback_reason": fallback_reason,
    }


def apply_speech_rate(session: Session, requested_speech_rate: float | int | str | None) -> float:
    try:
        value = float(requested_speech_rate) if requested_speech_rate is not None else session.speech_rate
    except (TypeError, ValueError):
        value = session.speech_rate
    session.speech_rate = _clamp_speech_rate(value)
    session.runtime.save_session_state(session)
    return session.speech_rate


def apply_voice_transforms(
    session: Session,
    requested_pitch: float | int | str | None = None,
    requested_tone: str | None = None,
    requested_expressiveness: float | int | str | None = None,
) -> dict[str, object]:
    try:
        if requested_pitch is not None:
            session.voice_pitch = float(requested_pitch)
    except (TypeError, ValueError):
        session.voice_pitch = 0.0
    if requested_tone is not None:
        session.voice_tone = str(requested_tone).strip() or "neutral"
    if requested_expressiveness is not None:
        try:
            session.expressiveness = _clamp_unit_interval(float(requested_expressiveness))
        except (TypeError, ValueError):
            session.expressiveness = None
        # Honor allowed_transforms: only retain expressiveness if voice allows.
        try:
            resolved, _ = session.runtime.tts.resolve_voice(session.voice_id or session.requested_voice_id)
            allowed = list(getattr(resolved, "allowed_transforms", []) or [])
            if "expressiveness" not in allowed:
                session.expressiveness = None
        except Exception:
            pass
    session.runtime.save_session_state(session)
    try:
        resolved_voice, _ = session.runtime.tts.resolve_voice(session.voice_id or session.requested_voice_id)
    except Exception:
        resolved_voice = None
    active_rate = effective_speech_rate_for_voice(session, resolved_voice)
    transform_status, ignored = _build_transform_status(session, resolved_voice, active_rate=active_rate) if resolved_voice is not None else ({"voice_defaults": {}, "allowed_transforms": [], "active_transforms": {"rate": active_rate, "pitch": session.voice_pitch, "tone": session.voice_tone}}, ["pitch", "tone"])
    return {
        **transform_status,
        "ignored_transforms": ignored,
    }


async def cancel_active_turn(session: Session, reason: str) -> None:
    if session.runtime_session_handle is None or session.current_turn_handle is None or session.current_turn_task is None or session.current_turn_task.done():
        return
    # Past the guard => a real turn was active and is about to be cancelled.
    # That's the semantic for "interrupted" regardless of what session.state
    # currently reads — the client may have sent vad_state concurrently and
    # already bumped us into "listening" before this coroutine got scheduled.
    partial_text = session.current_turn_buffered_text
    # Phase is explicit state carried with the turn; falls back to "thinking"
    # because reaching here means the turn was mid-flight and the adapter
    # hadn't completed (otherwise the task would be done).
    interrupted_during_state = session.current_turn_phase or "thinking"
    await session.set_state("interrupted", reason=reason)
    await session.emit("turn_cancel_requested", "adapter", {"turn_handle": session.current_turn_handle, "reason": reason})
    try:
        result = await session.binding.adapter.cancel_turn(session.runtime_session_handle, session.current_turn_handle, {"reason": reason})
        await session.emit("turn_cancel_acknowledged", "adapter", {"turn_handle": session.current_turn_handle, "result": result})
        await safe_send_str(session, {"type": "cancel_status", "result": result})
    except Exception as exc:
        await session.emit("recoverable_error", "adapter", {"component": "cancel", "message": str(exc), "turn_handle": session.current_turn_handle})
    # Always emit turn_interrupted for a real cancel of an active turn, even
    # if partial_text is empty. Adapters that buffer their entire response
    # (OpenClaw sends one final delta at the very end) would otherwise
    # suppress every voice barge-in during the thinking phase.
    resumable = session.runtime_session_handle is not None
    payload = {
        "partial_text": partial_text,
        "resumable": resumable,
        "interrupted_during_state": interrupted_during_state,
    }
    await session.emit("turn_interrupted", "session", payload)
    await safe_send_str(session, {"type": "turn_interrupted", **payload})


async def speak_text(
    session: Session,
    text: str,
    expected_generation: int | None = None,
    voice_id: str | None = None,
) -> None:
    if expected_generation is not None and expected_generation != session.playback_generation:
        return
    spoken_text = normalize_tts_text(text)
    if not spoken_text:
        return
    tts = session.runtime.tts
    engine = tts.kind if tts.available else "synthetic"
    resolved_voice = None
    fallback_reason = None
    selected_voice_id = voice_id or session.voice_id
    if tts.available:
        try:
            resolved_voice, fallback_reason = tts.resolve_voice(selected_voice_id)
        except Exception:
            resolved_voice = None
    session.last_tts_started_ms = time.monotonic() * 1000
    await session.emit("tts_chunk_ready", "playback", {"char_count": len(spoken_text), "engine": engine, "source_char_count": len(text)})
    effective_speech_rate = effective_speech_rate_for_voice(session, resolved_voice)
    transform_status, ignored_transforms = _build_transform_status(session, resolved_voice, active_rate=effective_speech_rate) if resolved_voice is not None else ({"voice_defaults": {}, "allowed_transforms": [], "active_transforms": {"rate": effective_speech_rate, "pitch": session.voice_pitch, "tone": session.voice_tone}}, [])
    if not await safe_send_str(session, {"type": "tts_status", "engine": engine, "available": tts.available, "voice_id": resolved_voice.voice_id if resolved_voice is not None else session.voice_id, "requested_voice_id": session.requested_voice_id or session.voice_id, "speech_rate": effective_speech_rate, "sample_rate": resolved_voice.sample_rate if resolved_voice is not None else TARGET_SAMPLE_RATE, **transform_status, "ignored_transforms": ignored_transforms, "reason": fallback_reason if resolved_voice is not None else (None if tts.available else "tts provider unavailable or no voice configured")}):
        return
    if tts.available:
        try:
            synthesis_started_ms = time.monotonic() * 1000
            samples, resolved_voice, fallback_reason = await tts.synthesize(spoken_text, voice_id=selected_voice_id, speech_rate=effective_speech_rate, expressiveness=session.expressiveness)
            synthesis_ms = round((time.monotonic() * 1000) - synthesis_started_ms, 3)
            session.voice_id = resolved_voice.voice_id
            await session.emit("tts_chunk_ready", "playback", {"char_count": len(spoken_text), "engine": tts.kind, "sample_count": len(samples), "synthesis_ms": synthesis_ms, "voice_id": resolved_voice.voice_id, "requested_voice_id": session.requested_voice_id or resolved_voice.voice_id, "speech_rate": effective_speech_rate, "session_speech_rate": session.speech_rate, "fallback_reason": fallback_reason, "source_char_count": len(text)})
            await send_pcm_samples(session, samples, resolved_voice.sample_rate, f"{tts.kind}_tts", engine=tts.kind, tts_started_ms=session.last_tts_started_ms, synthesis_ms=synthesis_ms, expected_generation=expected_generation)
            return
        except Exception as exc:
            await session.emit("recoverable_error", "playback", {"component": "tts", "message": str(exc), "engine": tts.kind})
            await safe_send_str(session, {"type": "tts_status", "engine": "synthetic", "available": False, "reason": f"{tts.kind} failed: {exc}"})


async def _run_speech_segment(
    previous_task: asyncio.Task | None,
    session: Session,
    text: str,
    expected_generation: int,
    voice_id: str | None = None,
) -> None:
    if previous_task is not None:
        try:
            await previous_task
        except asyncio.CancelledError:
            return
        except Exception:
            return
    if expected_generation != session.speech_generation:
        return
    await speak_text(session, text, expected_generation=expected_generation, voice_id=voice_id)


def enqueue_speech(
    session: Session,
    text: str,
    frozen_generation: int | None = None,
    voice_id: str | None = None,
) -> None:
    if not text.strip():
        return
    previous_task = session.speech_task
    generation = frozen_generation if frozen_generation is not None else session.speech_generation
    session.speech_task = asyncio.create_task(_run_speech_segment(previous_task, session, text, generation, voice_id))


async def stream_assistant_turn(session: Session, transcript: str) -> None:
    await ensure_adapter_session(session)
    session.turn_id = __import__("uuid").uuid4().hex
    session.speech_generation = session.playback_generation
    turn_speech_generation = session.speech_generation
    await emit_turn_state(session, "active")
    await session.set_state("thinking", reason="turn_submit_started")
    await session.emit("turn_submit_started", "adapter", {"turn_id": session.turn_id, "transcript": transcript})
    # Compose translation directive for the active mode (assistant by default
    # if any translation mode is configured on the session; else empty).
    from gateway.transport_spike.prompts import build_translation_directive
    effective_language = session.input_language or session.primary_language
    active_mode = session.translation_mode or ("assistant" if session.input_language else None)
    output_language = resolve_turn_output_language(session, active_mode)
    turn_voice_id = resolve_turn_voice_id(session, output_language)
    translation_directive = ""
    if active_mode is not None:
        try:
            translation_directive = build_translation_directive(
                mode=active_mode,
                source=session.translation_source,
                target=session.translation_target,
                detected_language=effective_language,
            )
        except ValueError:
            translation_directive = ""
    turn_context: dict = {
        "source": "transport_spike",
        "modality": "voice",
        "primary_language": session.primary_language,
        "output_language": output_language,
        "speech_rate": session.speech_rate,
    }
    optional_turn_context = {
        "input_language": session.input_language,
        "translation_mode": active_mode,
        "translation_source": session.translation_source,
        "translation_target": session.translation_target,
        "translation_directive": translation_directive,
        "voice_id": turn_voice_id or session.voice_id,
        "requested_voice_id": session.requested_voice_id,
    }
    for key, value in optional_turn_context.items():
        if value is not None and value != "":
            turn_context[key] = value
    turn_handle = await session.binding.adapter.submit_user_turn(session.runtime_session_handle, transcript, turn_context)
    session.current_turn_handle = turn_handle
    await session.emit("turn_submit_accepted", "adapter", {"turn_id": session.turn_id, "turn_handle": turn_handle})
    buffered = ""
    spoken_so_far = ""
    saw_final = False
    session.current_turn_buffered_text = ""
    session.current_turn_phase = "thinking"
    try:
        await session.emit("assistant_output_started", "adapter", {"turn_handle": turn_handle})
        async for event in session.binding.adapter.stream_assistant_output(session.runtime_session_handle, turn_handle):
            event_type = event["type"]
            if event_type == "assistant_text_delta":
                buffered += event["text"]
                session.current_turn_buffered_text = buffered
                await session.emit("assistant_output_delta", "adapter", {"turn_handle": turn_handle, "delta_chars": len(event["text"]), "buffered_chars": len(buffered)})
                if not await safe_send_str(session, {"type": "assistant_text_delta", "text": event["text"]}):
                    return
                unsent = buffered[len(spoken_so_far):]
                last_break = max((i for i, char in enumerate(unsent) if char in ".!?;:\n"), default=-1)
                if last_break >= 0:
                    chunk = unsent[:last_break + 1].strip()
                    if chunk:
                        enqueue_speech(session, chunk, turn_speech_generation, turn_voice_id)
                        spoken_so_far = buffered[:len(spoken_so_far) + last_break + 1]
                elif len(unsent.strip()) >= 60:
                    enqueue_speech(session, unsent.strip(), turn_speech_generation, turn_voice_id)
                    spoken_so_far = buffered
            elif event_type == "assistant_text_final":
                saw_final = True
                await session.emit("assistant_output_completed", "adapter", {"turn_handle": turn_handle, "final_chars": len(event["text"])})
                if not await safe_send_str(session, {"type": "assistant_text_final", "text": event["text"]}):
                    return
                remaining = event["text"][len(spoken_so_far):].strip()
                if remaining:
                    enqueue_speech(session, remaining, turn_speech_generation, turn_voice_id)
            elif event_type == "cancel_acknowledged":
                await session.emit("turn_cancel_acknowledged", "adapter", {"turn_handle": turn_handle})
                await safe_send_str(session, {"type": "cancel_status", "result": {"status": "acknowledged"}})
                return
            elif event_type == "turn_failed":
                await session.emit("recoverable_error", "adapter", {"component": "turn", "turn_handle": turn_handle, "message": event.get("message", "turn failed")})
                await safe_send_str(session, {"type": "turn_failed", "message": event.get("message", "turn failed")})
                return
            elif event_type == "turn_completed":
                session.turns_completed += 1
                await session.emit("assistant_output_completed", "adapter", {"turn_handle": turn_handle, "completed_via": "turn_completed"})
        if not saw_final and buffered:
            await session.emit("assistant_output_completed", "adapter", {"turn_handle": turn_handle, "final_chars": len(buffered), "completed_via": "buffer_flush"})
            await safe_send_str(session, {"type": "assistant_text_final", "text": buffered})
            remaining = buffered[len(spoken_so_far):] if buffered.startswith(spoken_so_far) else buffered
            enqueue_speech(session, remaining.strip(), turn_speech_generation, turn_voice_id)
    finally:
        speech_task = session.speech_task
        if speech_task is not None and not speech_task.done():
            try:
                await speech_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        await emit_turn_state(session, "idle")
        await session.set_state("idle", reason="turn_completed")
        session.current_turn_buffered_text = ""
        session.current_turn_phase = None
        clear_turn_state(session)


async def start_assistant_turn(session: Session, transcript: str) -> None:
    if session.current_turn_task is not None and not session.current_turn_task.done():
        await session.emit("recoverable_error", "gateway", {"component": "control", "message": "turn already active"})
        await safe_send_str(session, {"type": "turn_rejected", "reason": "turn already active"})
        return
    session.current_turn_task = asyncio.create_task(stream_assistant_turn(session, transcript))
