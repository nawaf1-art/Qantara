from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import unicodedata
import uuid

from adapters.base import make_activity_event
from gateway.transport_spike.common import (
    FRAME_SAMPLES,
    PCM_KIND,
    TARGET_SAMPLE_RATE,
    TONE_HZ,
    TONE_SECONDS,
)
from gateway.transport_spike.runtime import Session, TurnState
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
                session.utterance.snapshot().tolist(),
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


_SENTENCE_TERMINATORS = frozenset(".!?;:\n\u061f\u061b\u06d4")  # . ! ? ; : newline ؟ ؛ ۔
_UNSPACED_TERMINATORS = frozenset("\u3002\uff01\uff1f")  # 。！？ (CJK: no space follows)
_CLOSING_PUNCTUATION = frozenset("\"')]}\u00bb\u201d\u2019")
_NON_TERMINAL_ABBREVIATIONS = frozenset({"dr", "mr", "mrs", "ms", "st", "e.g", "i.e", "vs", "etc"})
_SOFT_BREAK_CHARS = frozenset(" \t,\u060c")  # space, tab, comma, Arabic comma
SPEECH_FALLBACK_CHARS = 60


def _word_before(text: str, index: int) -> str:
    start = index
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return text[start:index].lstrip("\"'([{\u00ab\u201c\u2018").lower()


def find_speech_breaks(text: str, *, final: bool) -> list[int]:
    """Return the end offsets of the complete sentences in ``text``.

    A terminator only ends a sentence when whitespace (or, once the stream
    is final, the end of the text) follows it, optionally after closing
    quotes or brackets. So "3.5", "10:30" and "Dr. Smith" never split, and
    a terminator at the very end of a streaming buffer waits for the next
    delta to decide. A colon followed by a digit ("Price: 3") never breaks.
    """
    breaks: list[int] = []
    length = len(text)
    for index, char in enumerate(text):
        if char in _UNSPACED_TERMINATORS:
            breaks.append(index + 1)
            continue
        if char not in _SENTENCE_TERMINATORS:
            continue
        if char == "\n":
            breaks.append(index + 1)
            continue
        end = index + 1
        while end < length and text[end] in _CLOSING_PUNCTUATION:
            end += 1
        if end >= length:
            if final:
                breaks.append(end)
            continue
        if not text[end].isspace():
            continue
        if char == ":":
            rest = text[end:].lstrip()
            if not rest:
                if final:
                    breaks.append(end)
                continue
            if rest[0].isdigit():
                continue
        if char == "." and _word_before(text, index) in _NON_TERMINAL_ABBREVIATIONS:
            continue
        breaks.append(end)
    return breaks


def fallback_speech_cut(text: str) -> int:
    """For long unpunctuated text, the offset after the last space or comma
    (0 if there is none, so a word is never cut in half)."""
    for index in range(len(text) - 1, 0, -1):
        if text[index] in _SOFT_BREAK_CHARS:
            return index + 1
    return 0


def _is_english_context(text: str, language: str | None) -> bool:
    if language:
        return language.strip().lower().replace("_", "-").split("-")[0] == "en"
    # Unknown language: only assume English wording for Latin-script text.
    return not any(char.isalpha() and ord(char) > 0x024F for char in text)


def normalize_tts_text(text: str, language: str | None = None) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized
    english = _is_english_context(normalized, language)
    normalized = normalized.replace("\r", "\n")
    normalized = re.sub(r"(?m)^\s*```[^\n]*$", "", normalized)
    normalized = normalized.replace("```", "")
    normalized = re.sub(r"`([^`]*)`", r"\1", normalized)
    normalized = re.sub(r"!?\[([^\]\n]*)\]\([^)\n]*\)", r"\1", normalized)
    normalized = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", normalized)
    normalized = normalized.replace("**", "").replace("__", "").replace("*", "")
    normalized = re.sub(r"(?m)^\s*[-\u2022]\s+", "", normalized)
    normalized = re.sub(r"(?<!\d) - (?!\d)", ". ", normalized)
    normalized = re.sub(r"\n+", ". ", normalized.strip())
    if english:
        normalized = re.sub(r"([+-])\s*(\d+)\s*\u00b0\s*C\b", lambda m: f"{'minus' if m.group(1) == '-' else 'plus'} {m.group(2)} degrees Celsius", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(\d+(?:\.\d+)?)\s*\u00b0\s*C\b", r"\1 degrees Celsius", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(\d+(?:\.\d+)?)\s*\u00b0\s*F\b", r"\1 degrees Fahrenheit", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(\d+(?:\.\d+)?)\s*km/h\b", r"\1 kilometers per hour", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(\d+(?:\.\d+)?)\s*mm\b", r"\1 millimeters", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", normalized)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "So")
    normalized = normalized.replace("\u2198", " ")
    normalized = re.sub(r"[|]+", ". ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"([!?.,]){2,}", r"\1", normalized)
    normalized = re.sub(r"\s+([!?.,])", r"\1", normalized)
    normalized = re.sub(r"^[.\s]+", "", normalized)
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
    try:
        from gateway.transport_spike.languages_catalog import voice_matches_language
        return voice_matches_language(voice, language)
    except Exception:
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
        from gateway.transport_spike.languages_catalog import select_voice_for_language
        preferred = select_voice_for_language(list(catalog.values()), output_language)
    except Exception:
        preferred = None
    if preferred:
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


# Playback is paced against an absolute schedule that runs this far ahead of
# real time: the first ~250 ms of each segment go out immediately and the
# client keeps that cushion, instead of the server sleeping a full frame
# after every send and the client starving at each frame boundary (V-4).
PLAYBACK_LEAD_SECONDS = 0.25
_pace_clock = time.monotonic
_pace_sleep = asyncio.sleep


async def send_pcm_samples(session: Session, samples: list[int], sample_rate: int, kind: str, engine: str | None = None, tts_started_ms: float | None = None, synthesis_ms: float | None = None, expected_generation: int | None = None) -> None:
    generation = session.playback_generation if expected_generation is None else expected_generation
    if generation != session.playback_generation:
        return
    await session.emit("playback_started", "playback", {"kind": kind, "sample_rate": sample_rate})
    sent_any = False
    first_frame_sent = False
    schedule_start = _pace_clock()
    sent_seconds = 0.0
    try:
        for offset in range(0, len(samples), FRAME_SAMPLES):
            # Checked before every frame, so a barge-in stops playback within
            # one frame even while the lead is being sent.
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
            sent_seconds += len(frame) / sample_rate
            ahead = sent_seconds - (_pace_clock() - schedule_start)
            if ahead > PLAYBACK_LEAD_SECONDS:
                await _pace_sleep(ahead - PLAYBACK_LEAD_SECONDS)
            else:
                # Stay cooperative while sending the lead.
                await asyncio.sleep(0)
    except asyncio.CancelledError:
        if sent_any:
            # Barge-in cancelled this segment mid-playback: tell the client
            # playback stopped so it can re-arm.
            await safe_send_str(session, {"type": "playback_stopped", "reason": "cleared", "kind": kind})
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
        raise
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
    session.turn_cancel_requested = False


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
    if not math.isfinite(value):
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
            pitch = float(requested_pitch)
            # "nan"/"inf" would be stored and then emitted as invalid JSON.
            if math.isfinite(pitch):
                session.voice_pitch = pitch
    except (TypeError, ValueError):
        session.voice_pitch = 0.0
    if requested_tone is not None:
        session.voice_tone = str(requested_tone).strip() or "neutral"
    if requested_expressiveness is not None:
        try:
            expressiveness = float(requested_expressiveness)
            session.expressiveness = _clamp_unit_interval(expressiveness) if math.isfinite(expressiveness) else None
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


def _turn_cancel_grace_seconds() -> float:
    try:
        grace_ms = float(os.environ.get("QANTARA_TURN_CANCEL_GRACE_MS", "750"))
    except ValueError:
        grace_ms = 750.0
    if not math.isfinite(grace_ms):
        grace_ms = 750.0
    return max(grace_ms, 0.0) / 1000.0


# How long a cancel request waits for the adapter's cancel_turn call before
# giving up on it (it keeps running in the background, retained).
ADAPTER_CANCEL_WAIT_SECONDS = 5.0


def _cancel_speech_tasks(session: Session) -> None:
    for task in list(session.speech_tasks):
        if not task.done():
            task.cancel()


def request_turn_cancel(session: Session, reason: str) -> asyncio.Task | None:
    """Claim the active turn for cancellation, synchronously.

    Runs to completion before any await: marks the turn cancelled, stops its
    output (generation bump + speech tasks cancelled), and schedules the
    teardown (state change, adapter cancel, ``turn_interrupted``, the
    grace-then-force watchdog) as a retained background task. Returns that
    task, or None when there is no active turn or it is already being
    cancelled, so concurrent or re-entrant cancels are no-ops.
    """
    turn = session.current_turn
    task = session.current_turn_task
    if turn is None or task is None or task.done() or turn.cancel_requested:
        return None
    turn.cancel_requested = True
    turn.cancel_reason = reason
    turn.partial_text = session.current_turn_buffered_text
    turn.interrupted_during_state = session.current_turn_phase or "thinking"
    session.turn_cancel_requested = True
    if session.speech_generation == turn.speech_generation:
        # The caller did not already clear playback: stop the turn's audio.
        session.playback_generation += 1
        session.speech_generation = max(session.speech_generation + 1, session.playback_generation)
    _cancel_speech_tasks(session)
    teardown = asyncio.create_task(_run_turn_cancel(session, turn, task))
    turn.teardown_task = teardown
    session.runtime.retain_task(teardown)
    return teardown


async def cancel_active_turn(session: Session, reason: str) -> None:
    """Request a cancel and wait for its teardown.

    The WebSocket receive loop uses ``request_turn_cancel`` directly so it
    never blocks on teardown; this awaiting form is kept for HTTP control
    handlers and tests. A second concurrent call returns immediately.
    """
    teardown = request_turn_cancel(session, reason)
    if teardown is not None:
        await asyncio.wait({teardown})


async def _send_cancel_status(session: Session, turn: TurnState, result: dict) -> None:
    if turn.cancel_status_sent:
        return
    turn.cancel_status_sent = True
    await session.emit("turn_cancel_acknowledged", "adapter", {"turn_handle": turn.handle, "result": result})
    await safe_send_str(session, {"type": "cancel_status", "result": result})


async def _send_adapter_cancel(session: Session, turn: TurnState) -> None:
    if turn.adapter_cancel_sent or turn.handle is None or session.binding is None:
        return
    turn.adapter_cancel_sent = True
    try:
        result = await session.binding.adapter.cancel_turn(session.runtime_session_handle, turn.handle, {"reason": turn.cancel_reason})
    except Exception as exc:
        await session.emit("recoverable_error", "adapter", {"component": "cancel", "message": str(exc), "turn_handle": turn.handle})
        return
    await _send_cancel_status(session, turn, result if isinstance(result, dict) else {"status": str(result)})


async def _announce_turn_interrupted(session: Session, turn: TurnState) -> None:
    if turn.interrupted_emitted:
        return
    turn.interrupted_emitted = True
    payload = {
        "partial_text": turn.partial_text,
        "interrupted_during_state": turn.interrupted_during_state or "thinking",
    }
    await session.emit("turn_interrupted", "session", payload)
    await safe_send_str(session, {"type": "turn_interrupted", **payload})


async def _run_turn_cancel(session: Session, turn: TurnState, turn_task: asyncio.Task) -> None:
    try:
        # Interrupted regardless of what session.state reads now: the client
        # may have sent vad_state concurrently and bumped us to "listening".
        if session.current_turn is turn and not turn_task.done():
            await session.set_state("interrupted", reason=turn.cancel_reason)
        await session.emit("turn_cancel_requested", "adapter", {"turn_handle": turn.handle, "reason": turn.cancel_reason})
        # Always announce a real cancel, even with empty partial text:
        # adapters that buffer their whole reply (OpenClaw) would otherwise
        # suppress every barge-in during the thinking phase.
        await _announce_turn_interrupted(session, turn)
    finally:
        turn.interrupt_announced.set()
    if turn.handle is None:
        # Barge-in during session start / turn acceptance: the turn loop
        # honors it the moment it has (or fails to get) a handle.
        return
    adapter_cancel = asyncio.create_task(_send_adapter_cancel(session, turn))
    session.runtime.retain_task(adapter_cancel)
    # Do not rely on adapter cooperation: a wedged backend that never ends
    # its stream would pin the turn task forever. Give it a bounded grace
    # window to unwind, then force-cancel it.
    grace_seconds = _turn_cancel_grace_seconds()
    if not turn_task.done():
        done, _pending = await asyncio.wait({turn_task}, timeout=grace_seconds)
        if not done:
            await session.emit("turn_cancel_forced", "gateway", {"turn_handle": turn.handle, "grace_ms": grace_seconds * 1000})
            turn_task.cancel()
            await asyncio.wait({turn_task})
    if not adapter_cancel.done():
        await asyncio.wait({adapter_cancel}, timeout=ADAPTER_CANCEL_WAIT_SECONDS)


async def speak_text(
    session: Session,
    text: str,
    expected_generation: int | None = None,
    voice_id: str | None = None,
    language: str | None = None,
) -> None:
    if expected_generation is not None and expected_generation != session.playback_generation:
        return
    spoken_text = normalize_tts_text(text, language=language)
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
            # The resolved voice is per segment (a turn may pick a voice for its
            # output language); it must not stick to the session (V-9).
            await session.emit("tts_chunk_ready", "playback", {"char_count": len(spoken_text), "engine": tts.kind, "sample_count": len(samples), "synthesis_ms": synthesis_ms, "voice_id": resolved_voice.voice_id, "requested_voice_id": session.requested_voice_id or resolved_voice.voice_id, "speech_rate": effective_speech_rate, "session_speech_rate": session.speech_rate, "fallback_reason": fallback_reason, "source_char_count": len(text)})
            await send_pcm_samples(session, samples, resolved_voice.sample_rate, f"{tts.kind}_tts", engine=tts.kind, tts_started_ms=session.last_tts_started_ms, synthesis_ms=synthesis_ms, expected_generation=expected_generation)
            return
        except Exception as exc:
            await session.emit("recoverable_error", "playback", {"component": "tts", "message": str(exc), "engine": tts.kind})
            await safe_send_str(session, {"type": "tts_status", "engine": "synthetic", "available": False, "reason": f"{tts.kind} failed: {exc}"})


async def _await_previous_speech(previous_task: asyncio.Task | None) -> None:
    """Wait for the previous segment without inheriting its outcome.

    ``asyncio.wait`` does not propagate the previous task's cancellation or
    exception, so a segment cancelled by a barge-in cannot silence the next
    reply (Q-05a); the generation check that follows decides whether to
    speak.
    """
    if previous_task is not None and previous_task is not asyncio.current_task():
        await asyncio.wait({previous_task})


def _track_speech_task(session: Session, task: asyncio.Task) -> asyncio.Task:
    session.speech_tasks.add(task)
    task.add_done_callback(session.speech_tasks.discard)
    session.speech_task = task
    return task


async def _run_speech_segment(
    previous_task: asyncio.Task | None,
    session: Session,
    text: str,
    expected_generation: int,
    voice_id: str | None = None,
    language: str | None = None,
) -> None:
    await _await_previous_speech(previous_task)
    if expected_generation != session.speech_generation:
        return
    await speak_text(session, text, expected_generation=expected_generation, voice_id=voice_id, language=language)


def enqueue_speech(
    session: Session,
    text: str,
    frozen_generation: int | None = None,
    voice_id: str | None = None,
    *,
    language: str | None = None,
) -> None:
    if not text.strip():
        return
    previous_task = session.speech_task
    generation = frozen_generation if frozen_generation is not None else session.speech_generation
    _track_speech_task(session, asyncio.create_task(_run_speech_segment(previous_task, session, text, generation, voice_id, language)))


async def _run_control_speech_segment(
    previous_task: asyncio.Task | None,
    session: Session,
    text: str,
    expected_generation: int,
    voice_id: str | None = None,
) -> None:
    await _await_previous_speech(previous_task)
    if expected_generation != session.speech_generation:
        return
    # If a real backend turn is in flight, play the injected audio but do NOT
    # drive the session state machine: forcing speaking->idle here would make
    # every state consumer (barge-in eligibility, endpoint auto-submit, the UI)
    # believe the assistant finished mid-turn. State is only ours to manage
    # when this is a standalone announcement with no active turn.
    turn_active = session.current_turn_task is not None and not session.current_turn_task.done()
    if not turn_active:
        await session.set_state("speaking", reason="control_voice_speak")
    await session.emit("assistant_output_started", "control", {"kind": "voice_speak", "char_count": len(text)})
    session.record_transcript_item(role="assistant", text=text, source="control", turn_id=None)
    await safe_send_str(session, {"type": "assistant_text_final", "text": text, "source": "control"})
    try:
        await speak_text(session, text, expected_generation=expected_generation, voice_id=voice_id)
    finally:
        await session.emit("assistant_output_completed", "control", {"kind": "voice_speak", "char_count": len(text)})
        if not turn_active and session.state == "speaking":
            await session.set_state("idle", reason="control_voice_speak_completed")


def enqueue_control_speech(
    session: Session,
    text: str,
    frozen_generation: int | None = None,
    voice_id: str | None = None,
) -> None:
    if not text.strip():
        return
    previous_task = session.speech_task
    generation = frozen_generation if frozen_generation is not None else session.speech_generation
    _track_speech_task(session, asyncio.create_task(
        _run_control_speech_segment(previous_task, session, text, generation, voice_id)
    ))


def _enqueue_turn_speech(session: Session, turn: TurnState, chunk: str, voice_id: str | None, language: str | None) -> None:
    if turn.cancel_requested or not chunk:
        return
    enqueue_speech(session, chunk, turn.speech_generation, voice_id, language=language)
    turn.spoken_text = f"{turn.spoken_text} {chunk}" if turn.spoken_text else chunk


def _enqueue_complete_sentences(
    session: Session,
    turn: TurnState,
    buffered: str,
    spoken_so_far: str,
    voice_id: str | None,
    language: str | None,
) -> str:
    """Enqueue every complete sentence of the unspoken part of ``buffered``;
    return the new spoken prefix."""
    unsent = buffered[len(spoken_so_far):]
    consumed = 0
    for end in find_speech_breaks(unsent, final=False):
        _enqueue_turn_speech(session, turn, unsent[consumed:end].strip(), voice_id, language)
        consumed = end
    rest = unsent[consumed:]
    if len(rest.strip()) >= SPEECH_FALLBACK_CHARS:
        cut = fallback_speech_cut(rest)
        if cut:
            _enqueue_turn_speech(session, turn, rest[:cut].strip(" \t,،"), voice_id, language)
            consumed += cut
    return buffered[:len(spoken_so_far) + consumed]


def _enqueue_final_text(
    session: Session,
    turn: TurnState,
    text: str,
    voice_id: str | None,
    language: str | None,
) -> None:
    """Enqueue the remaining text sentence by sentence (end of stream)."""
    consumed = 0
    for end in find_speech_breaks(text, final=True):
        _enqueue_turn_speech(session, turn, text[consumed:end].strip(), voice_id, language)
        consumed = end
    _enqueue_turn_speech(session, turn, text[consumed:].strip(), voice_id, language)


def _failure_details(exc: BaseException, stage: str) -> tuple[str, str, bool]:
    message = str(exc).strip() or type(exc).__name__
    if len(message) > 300:
        message = message[:297] + "..."
    kind = getattr(exc, "failure_kind", None)
    retriable = getattr(exc, "retriable", None)
    if not isinstance(kind, str) or not kind:
        if isinstance(exc, TimeoutError):
            kind = "timeout"
        elif stage in {"session_start", "submit"}:
            kind = "backend_unavailable"
        else:
            kind = "backend_error"
    if not isinstance(retriable, bool):
        retriable = True
    return message, kind, retriable


async def _report_turn_failure(
    session: Session,
    turn: TurnState,
    *,
    message: str,
    failure_kind: str | None,
    retriable: bool | None,
    stage: str,
) -> None:
    await session.emit("recoverable_error", "adapter", {"component": "turn", "stage": stage, "turn_handle": turn.handle, "message": message, "failure_kind": failure_kind, "retriable": retriable})
    payload: dict = {"type": "turn_failed", "message": message}
    if failure_kind is not None:
        payload["failure_kind"] = failure_kind
    if retriable is not None:
        payload["retriable"] = retriable
    await safe_send_str(session, payload)


class _TurnStageError(Exception):
    def __init__(self, stage: str, original: BaseException) -> None:
        super().__init__(str(original))
        self.stage = stage
        self.original = original


async def _start_session_and_submit(session: Session, turn: TurnState, transcript: str, turn_context: dict) -> str | None:
    """Start (if needed) the backend session and submit the turn.

    On failure, drop the (possibly stale) runtime session handle, start a
    fresh backend session and retry once (Q-03). Returns None when the turn
    was cancelled before it was submitted.
    """
    last_error: _TurnStageError | None = None
    for attempt in range(2):
        if turn.cancel_requested:
            return None
        stage = "session_start"
        try:
            await ensure_adapter_session(session)
            if turn.cancel_requested:
                return None
            stage = "submit"
            return await session.binding.adapter.submit_user_turn(session.runtime_session_handle, transcript, turn_context)
        except Exception as exc:
            last_error = _TurnStageError(stage, exc)
            if turn.cancel_requested:
                return None
            await session.emit("recoverable_error", "adapter", {"component": "turn", "stage": stage, "message": str(exc), "retrying": attempt == 0})
            session.runtime_session_handle = None
            session.runtime.save_session_state(session)
    assert last_error is not None
    raise last_error


def _event_text(event: dict) -> str | None:
    text = event.get("text")
    return text if isinstance(text, str) else None


async def stream_assistant_turn(
    session: Session,
    transcript: str,
    *,
    turn: TurnState | None = None,
    previous_task: asyncio.Task | None = None,
) -> None:
    if turn is None:
        turn = TurnState(turn_id=uuid.uuid4().hex)
    session.current_turn = turn
    if previous_task is not None and not previous_task.done():
        # The previous turn is still tearing down after a barge-in; its
        # watchdog force-cancels it within the grace window.
        await asyncio.wait({previous_task}, timeout=_turn_cancel_grace_seconds() + 1.0)
    session.turn_id = turn.turn_id
    session.turn_cancel_requested = turn.cancel_requested
    session.speech_generation = session.playback_generation
    turn.speech_generation = session.speech_generation
    session.current_turn_buffered_text = ""
    session.current_turn_phase = "thinking"
    buffered = ""
    spoken_so_far = ""
    final_text: str | None = None
    try:
        await emit_turn_state(session, "active")
        if not turn.cancel_requested:
            await session.set_state("thinking", reason="turn_submit_started")
        session.record_transcript_item(role="user", text=transcript, source="browser", turn_id=turn.turn_id)
        await session.emit("turn_submit_started", "adapter", {"turn_id": turn.turn_id, "transcript": transcript})
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

        turn_handle = await _start_session_and_submit(session, turn, transcript, turn_context)
        if turn_handle is None:
            return
        turn.handle = turn_handle
        session.current_turn_handle = turn_handle
        await session.emit("turn_submit_accepted", "adapter", {"turn_id": turn.turn_id, "turn_handle": turn_handle})
        if turn.cancel_requested:
            # A barge-in arrived while the backend was accepting the turn;
            # honor it now that a handle exists.
            await _send_adapter_cancel(session, turn)
            return
        await session.emit("assistant_output_started", "adapter", {"turn_handle": turn_handle})
        try:
            async for event in session.binding.adapter.stream_assistant_output(session.runtime_session_handle, turn_handle):
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if turn.cancel_requested:
                    # After a cancel nothing more reaches the client or the
                    # transcript (LC-5); only the acknowledgement matters.
                    if event_type == "cancel_acknowledged":
                        await _send_cancel_status(session, turn, {"status": "acknowledged"})
                    return
                if event_type == "assistant_text_delta":
                    delta = _event_text(event)
                    if not delta:
                        continue
                    buffered += delta
                    session.current_turn_buffered_text = buffered
                    await session.emit("assistant_output_delta", "adapter", {"turn_handle": turn_handle, "delta_chars": len(delta), "buffered_chars": len(buffered)})
                    if not await safe_send_str(session, {"type": "assistant_text_delta", "text": delta}):
                        return
                    spoken_so_far = _enqueue_complete_sentences(session, turn, buffered, spoken_so_far, turn_voice_id, output_language)
                elif event_type == "assistant_text_final":
                    text = _event_text(event)
                    if text is None:
                        text = buffered
                    final_text = text
                    await session.emit("assistant_output_completed", "adapter", {"turn_handle": turn_handle, "final_chars": len(text)})
                    if not await safe_send_str(session, {"type": "assistant_text_final", "text": text}):
                        return
                    # Speak the rest of what was streamed; the final text is for
                    # the transcript only. Bridges may normalise their final
                    # (drop '*', '#', newlines), so slicing it by the streamed
                    # length would garble the tail (B-1).
                    if buffered:
                        remaining = buffered[len(spoken_so_far):]
                    elif text.startswith(spoken_so_far):
                        remaining = text[len(spoken_so_far):]
                    else:
                        remaining = text
                    _enqueue_final_text(session, turn, remaining, turn_voice_id, output_language)
                    spoken_so_far = buffered if buffered else text
                elif event_type == "assistant_activity":
                    # Re-validate through the protocol-v1 builder: adapter events
                    # cross a trust boundary into the browser, so malformed
                    # tool-call metadata is dropped here, not rendered.
                    normalized = make_activity_event(
                        activity_type=event.get("activity_type", "other"),
                        summary=event.get("summary", ""),
                        progress=event.get("progress"),
                        tool_name=event.get("tool_name"),
                        parameters=event.get("parameters") if isinstance(event.get("parameters"), dict) else None,
                        confidence=event.get("confidence"),
                    )
                    payload = {k: v for k, v in normalized.items() if k != "type"}
                    await session.emit("assistant_activity", "adapter", payload)
                    if not await safe_send_str(session, {"type": "assistant_activity", **payload}):
                        return
                elif event_type == "cancel_acknowledged":
                    await _send_cancel_status(session, turn, {"status": "acknowledged"})
                    return
                elif event_type == "turn_failed":
                    message = event.get("message")
                    failure_kind = event.get("failure_kind")
                    retriable = event.get("retriable")
                    await _report_turn_failure(
                        session,
                        turn,
                        message=message if isinstance(message, str) and message else "turn failed",
                        failure_kind=failure_kind if isinstance(failure_kind, str) and failure_kind else None,
                        retriable=retriable if isinstance(retriable, bool) else None,
                        stage="stream",
                    )
                    return
                elif event_type == "turn_completed":
                    session.turns_completed += 1
                    await session.emit("assistant_output_completed", "adapter", {"turn_handle": turn_handle, "completed_via": "turn_completed"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise _TurnStageError("stream", exc) from exc
        if final_text is None and buffered and not turn.cancel_requested:
            final_text = buffered
            await session.emit("assistant_output_completed", "adapter", {"turn_handle": turn_handle, "final_chars": len(buffered), "completed_via": "buffer_flush"})
            await safe_send_str(session, {"type": "assistant_text_final", "text": buffered})
            _enqueue_final_text(session, turn, buffered[len(spoken_so_far):], turn_voice_id, output_language)
            spoken_so_far = buffered
    except _TurnStageError as failure:
        if not turn.cancel_requested:
            message, kind, retriable = _failure_details(failure.original, failure.stage)
            await _report_turn_failure(session, turn, message=message, failure_kind=kind, retriable=retriable, stage=failure.stage)
    except Exception as exc:
        if not turn.cancel_requested:
            message, kind, retriable = _failure_details(exc, "gateway")
            await _report_turn_failure(session, turn, message=message, failure_kind=kind, retriable=retriable, stage="gateway")
    finally:
        await _finish_turn(session, turn, final_text)


async def _finish_turn(session: Session, turn: TurnState, final_text: str | None) -> None:
    """Turn cleanup; safe to run while the turn task is being force-cancelled."""
    cancelled_during_cleanup = False
    try:
        speech_task = session.speech_task
        if (
            not turn.cancel_requested
            and session.speech_generation == turn.speech_generation
            and speech_task is not None
            and not speech_task.done()
        ):
            # Keep the turn active until its queued speech has played. Speech
            # whose generation is stale (barge-in) is not waited for.
            await asyncio.wait({speech_task})
        if turn.cancel_requested and turn.teardown_task is not None:
            await turn.interrupt_announced.wait()
    except asyncio.CancelledError:
        cancelled_during_cleanup = True
    if turn.cancel_requested:
        session.record_transcript_item(role="assistant", text=turn.spoken_text, source="adapter", turn_id=turn.turn_id, interrupted=True)
    elif final_text:
        session.record_transcript_item(role="assistant", text=final_text, source="adapter", turn_id=turn.turn_id)
    if session.current_turn is turn:
        try:
            await emit_turn_state(session, "idle")
            # The user may still be talking (barge-in): report listening, not
            # idle, so control clients don't speak over them (B-5).
            end_state = "listening" if session.last_vad_state == "speech" else "idle"
            await session.set_state(end_state, reason="turn_interrupted" if turn.cancel_requested else "turn_completed")
        except asyncio.CancelledError:
            cancelled_during_cleanup = True
        finally:
            session.current_turn_buffered_text = ""
            session.current_turn_phase = None
            session.current_turn = None
            clear_turn_state(session)
    if cancelled_during_cleanup:
        raise asyncio.CancelledError()


async def start_assistant_turn(session: Session, transcript: str) -> None:
    previous_task: asyncio.Task | None = None
    active = session.current_turn_task
    if active is not None and not active.done():
        current = session.current_turn
        if current is None or not current.cancel_requested:
            await session.emit("recoverable_error", "gateway", {"component": "control", "message": "turn already active"})
            await safe_send_str(session, {"type": "turn_rejected", "reason": "turn already active"})
            return
        # The active turn was interrupted and is still unwinding: queue behind it.
        previous_task = active
    turn = TurnState(turn_id=uuid.uuid4().hex)
    session.current_turn = turn
    task = asyncio.create_task(stream_assistant_turn(session, transcript, turn=turn, previous_task=previous_task))
    session.current_turn_task = task
    session.runtime.retain_task(task)
