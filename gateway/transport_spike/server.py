import asyncio
import json
import math
import os
import ssl
import sys
import time
import uuid
from aiohttp import WSMsgType, web

CURRENT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
CLIENT_SPIKE_DIR = os.path.join(REPO_ROOT, "client", "transport-spike")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from adapters.factory import create_adapter, load_adapter_config
from gateway.transport_spike.stt_faster_whisper import FasterWhisperSTT
from gateway.transport_spike.tts_piper import PiperTTS


PCM_KIND = 0x01
TARGET_SAMPLE_RATE = 16000
TONE_HZ = 440.0
TONE_SECONDS = 1.25
FRAME_SAMPLES = 640
PIPER_VOICE_PATH = os.environ.get("QANTARA_PIPER_MODEL")
FASTER_WHISPER_MODEL = os.environ.get("QANTARA_WHISPER_MODEL", "base.en")
FASTER_WHISPER_DEVICE = os.environ.get("QANTARA_WHISPER_DEVICE", "cpu")
FASTER_WHISPER_COMPUTE = os.environ.get("QANTARA_WHISPER_COMPUTE", "int8")
DEFAULT_HOST = os.environ.get("QANTARA_SPIKE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("QANTARA_SPIKE_PORT", "8765"))
TLS_CERT_FILE = os.environ.get("QANTARA_TLS_CERT")
TLS_KEY_FILE = os.environ.get("QANTARA_TLS_KEY")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Session:
    def __init__(self, websocket: web.WebSocketResponse) -> None:
        self.websocket = websocket
        self.session_id = str(uuid.uuid4())
        self.connection_id = str(uuid.uuid4())
        self.runtime_session_handle = None
        self.turn_id = None
        self.frames_in = 0
        self.frames_out = 0
        self.playback_generation = 0
        self.last_vad_state = "silence"
        self.recent_pcm: list[int] = []
        self.recent_pcm_limit = TARGET_SAMPLE_RATE * 6
        self.last_tts_started_ms: float | None = None
        self.current_turn_handle: str | None = None
        self.current_turn_task: asyncio.Task | None = None
        self.speech_task: asyncio.Task | None = None
        self.speech_generation = 0

    async def emit(self, event_name: str, source: str, payload: dict) -> None:
        record = {
            "event_name": event_name,
            "session_id": self.session_id,
            "connection_id": self.connection_id,
            "turn_id": self.turn_id,
            "ts_monotonic_ms": round(time.monotonic() * 1000, 3),
            "ts_wall_time": utc_now(),
            "source": source,
            "payload": payload,
        }
        print(json.dumps(record), flush=True)


ADAPTER_CONFIG = load_adapter_config()
ADAPTER = create_adapter(ADAPTER_CONFIG)
PIPER = PiperTTS(voice_path=PIPER_VOICE_PATH)
STT = FasterWhisperSTT(
    model_name=FASTER_WHISPER_MODEL,
    device=FASTER_WHISPER_DEVICE,
    compute_type=FASTER_WHISPER_COMPUTE,
)


def encode_pcm_frame(samples: list[int]) -> bytes:
    payload = bytearray(1 + len(samples) * 2)
    payload[0] = PCM_KIND
    offset = 1
    for sample in samples:
        payload[offset:offset + 2] = int(sample).to_bytes(2, "little", signed=True)
        offset += 2
    return bytes(payload)


async def send_tone(session: Session) -> None:
    generation = session.playback_generation
    total_samples = int(TARGET_SAMPLE_RATE * TONE_SECONDS)
    amplitude = 0.22 * 32767

    await session.emit("playback_started", "playback", {"kind": "synthetic_tone"})

    sent_any = False
    first_frame_sent = False
    for offset in range(0, total_samples, FRAME_SAMPLES):
        if generation != session.playback_generation:
            await session.websocket.send_str(json.dumps({"type": "playback_stopped", "reason": "cleared", "kind": "synthetic_tone"}))
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
            return
        frame = []
        for i in range(offset, min(offset + FRAME_SAMPLES, total_samples)):
            value = math.sin(2 * math.pi * TONE_HZ * (i / TARGET_SAMPLE_RATE))
            frame.append(int(amplitude * value))
        await session.websocket.send_bytes(encode_pcm_frame(frame))
        session.frames_out += 1
        sent_any = True
        if not first_frame_sent:
            first_frame_sent = True
            await session.websocket.send_str(
                json.dumps(
                    {
                        "type": "playback_metrics",
                        "engine": "synthetic",
                        "kind": "synthetic_tone",
                        "tts_to_first_audio_ms": 0,
                        "synthesis_ms": 0,
                    }
                )
            )
            await session.emit(
                "playback_first_frame_sent",
                "playback",
                {"kind": "synthetic_tone", "tts_to_first_audio_ms": 0},
            )
        await session.emit(
            "output_audio_frame_sent",
            "playback",
            {
                "frame_index": session.frames_out,
                "frame_samples": len(frame),
                "sample_rate": TARGET_SAMPLE_RATE,
            },
        )
        await asyncio.sleep(len(frame) / TARGET_SAMPLE_RATE)

    if sent_any:
        await session.websocket.send_str(json.dumps({"type": "playback_stopped", "reason": "tone_complete", "kind": "synthetic_tone"}))
        await session.emit("playback_stopped", "playback", {"reason": "tone_complete"})


async def send_pcm_samples(
    session: Session,
    samples: list[int],
    sample_rate: int,
    kind: str,
    tts_started_ms: float | None = None,
    synthesis_ms: float | None = None,
    expected_generation: int | None = None,
) -> None:
    generation = session.playback_generation if expected_generation is None else expected_generation
    if generation != session.playback_generation:
        return
    await session.emit("playback_started", "playback", {"kind": kind, "sample_rate": sample_rate})

    sent_any = False
    first_frame_sent = False
    for offset in range(0, len(samples), FRAME_SAMPLES):
        if generation != session.playback_generation:
            await session.websocket.send_str(json.dumps({"type": "playback_stopped", "reason": "cleared", "kind": kind}))
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
            return

        frame = samples[offset:offset + FRAME_SAMPLES]
        await session.websocket.send_bytes(encode_pcm_frame(frame))
        session.frames_out += 1
        sent_any = True
        if not first_frame_sent:
            first_frame_sent = True
            first_audio_ms = None
            if tts_started_ms is not None:
                first_audio_ms = round((time.monotonic() * 1000) - tts_started_ms, 3)
            await session.websocket.send_str(
                json.dumps(
                    {
                        "type": "playback_metrics",
                        "engine": "piper" if kind == "piper_tts" else "synthetic",
                        "kind": kind,
                        "tts_to_first_audio_ms": first_audio_ms,
                        "synthesis_ms": synthesis_ms,
                    }
                )
            )
            await session.emit(
                "playback_first_frame_sent",
                "playback",
                {
                    "kind": kind,
                    "tts_to_first_audio_ms": first_audio_ms,
                    "synthesis_ms": synthesis_ms,
                },
            )
        await session.emit(
            "output_audio_frame_sent",
            "playback",
            {
                "frame_index": session.frames_out,
                "frame_samples": len(frame),
                "sample_rate": sample_rate,
                "kind": kind,
            },
        )
        await asyncio.sleep(len(frame) / sample_rate)

    if sent_any:
        reason = f"{kind}_complete"
        await session.websocket.send_str(json.dumps({"type": "playback_stopped", "reason": reason, "kind": kind}))
        await session.emit("playback_stopped", "playback", {"reason": reason})


async def send_pcm_stream(
    session: Session,
    sample_stream,
    sample_rate: int,
    kind: str,
    tts_started_ms: float | None = None,
    expected_generation: int | None = None,
) -> None:
    """Stream PCM chunks to the browser as they arrive from TTS, without waiting for full synthesis."""
    generation = session.playback_generation if expected_generation is None else expected_generation
    if generation != session.playback_generation:
        return
    await session.emit("playback_started", "playback", {"kind": kind, "sample_rate": sample_rate})

    sent_any = False
    first_frame_sent = False
    total_samples = 0
    async for samples in sample_stream:
        if generation != session.playback_generation:
            await session.websocket.send_str(json.dumps({"type": "playback_stopped", "reason": "cleared", "kind": kind}))
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
            return

        total_samples += len(samples)
        for offset in range(0, len(samples), FRAME_SAMPLES):
            if generation != session.playback_generation:
                await session.websocket.send_str(json.dumps({"type": "playback_stopped", "reason": "cleared", "kind": kind}))
                await session.emit("playback_stopped", "playback", {"reason": "cleared"})
                return
            frame = samples[offset:offset + FRAME_SAMPLES]
            await session.websocket.send_bytes(encode_pcm_frame(frame))
            session.frames_out += 1
            sent_any = True
            if not first_frame_sent:
                first_frame_sent = True
                first_audio_ms = None
                if tts_started_ms is not None:
                    first_audio_ms = round((time.monotonic() * 1000) - tts_started_ms, 3)
                await session.websocket.send_str(
                    json.dumps(
                        {
                            "type": "playback_metrics",
                            "engine": "piper",
                            "kind": kind,
                            "tts_to_first_audio_ms": first_audio_ms,
                            "streaming": True,
                        }
                    )
                )
                await session.emit(
                    "playback_first_frame_sent",
                    "playback",
                    {"kind": kind, "tts_to_first_audio_ms": first_audio_ms, "streaming": True},
                )
            await asyncio.sleep(len(frame) / sample_rate)

    if sent_any:
        synthesis_ms = None
        if tts_started_ms is not None:
            synthesis_ms = round((time.monotonic() * 1000) - tts_started_ms, 3)
        await session.emit(
            "tts_stream_complete",
            "playback",
            {"kind": kind, "total_samples": total_samples, "synthesis_ms": synthesis_ms},
        )
        reason = f"{kind}_complete"
        await session.websocket.send_str(json.dumps({"type": "playback_stopped", "reason": reason, "kind": kind}))
        await session.emit("playback_stopped", "playback", {"reason": reason})


async def speak_text(session: Session, text: str, expected_generation: int | None = None) -> None:
    if expected_generation is not None and expected_generation != session.playback_generation:
        return
    engine = "piper" if PIPER.available else "synthetic"
    session.last_tts_started_ms = time.monotonic() * 1000
    await session.emit("tts_chunk_ready", "playback", {"char_count": len(text), "engine": engine})
    await session.websocket.send_str(
        json.dumps(
            {
                "type": "tts_status",
                "engine": engine,
                "available": PIPER.available,
                "reason": None if PIPER.available else "piper unavailable or no model configured",
            }
        )
    )

    if PIPER.available:
        try:
            await send_pcm_stream(
                session,
                PIPER.synthesize_stream(text),
                PIPER.sample_rate,
                "piper_tts",
                tts_started_ms=session.last_tts_started_ms,
                expected_generation=expected_generation,
            )
            return
        except Exception as exc:
            await session.emit(
                "recoverable_error",
                "playback",
                {"component": "tts", "message": str(exc), "engine": "piper"},
            )
            await session.websocket.send_str(
                json.dumps(
                    {
                        "type": "tts_status",
                        "engine": "synthetic",
                        "available": False,
                        "reason": f"piper failed: {exc}",
                    }
                )
            )

    await send_tone(session)


async def _run_speech_segment(
    previous_task: asyncio.Task | None,
    session: Session,
    text: str,
    expected_generation: int,
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

    await speak_text(session, text, expected_generation=expected_generation)


def enqueue_speech(session: Session, text: str) -> None:
    if not text.strip():
        return

    previous_task = session.speech_task
    generation = session.speech_generation
    session.speech_task = asyncio.create_task(_run_speech_segment(previous_task, session, text, generation))


async def ensure_adapter_session(session: Session) -> None:
    if session.runtime_session_handle is None:
        session.runtime_session_handle = await ADAPTER.start_or_resume_session(
            {"client_name": "browser-transport-spike", "session_id": session.session_id}
        )
        health = await ADAPTER.check_health()
        await session.emit(
            "adapter_session_ready",
            "adapter",
            {
                "runtime_session_handle": session.runtime_session_handle,
                "adapter_kind": ADAPTER.adapter_kind,
                "adapter_health": health.status,
            },
        )


def clear_turn_state(session: Session) -> None:
    session.current_turn_handle = None
    session.current_turn_task = None


async def cancel_active_turn(session: Session, reason: str) -> None:
    if (
        session.runtime_session_handle is None
        or session.current_turn_handle is None
        or session.current_turn_task is None
        or session.current_turn_task.done()
    ):
        return

    await session.emit(
        "turn_cancel_requested",
        "adapter",
        {"turn_handle": session.current_turn_handle, "reason": reason},
    )
    try:
        result = await ADAPTER.cancel_turn(
            session.runtime_session_handle,
            session.current_turn_handle,
            {"reason": reason},
        )
        await session.emit(
            "turn_cancel_acknowledged",
            "adapter",
            {"turn_handle": session.current_turn_handle, "result": result},
        )
        await session.websocket.send_str(json.dumps({"type": "cancel_status", "result": result}))
    except Exception as exc:
        await session.emit(
            "recoverable_error",
            "adapter",
            {"component": "cancel", "message": str(exc), "turn_handle": session.current_turn_handle},
        )


async def stream_assistant_turn(session: Session, transcript: str) -> None:
    await ensure_adapter_session(session)

    session.turn_id = str(uuid.uuid4())
    session.speech_generation = session.playback_generation
    await session.emit("turn_submit_started", "adapter", {"turn_id": session.turn_id, "transcript": transcript})
    turn_handle = await ADAPTER.submit_user_turn(
        session.runtime_session_handle,
        transcript,
        {"source": "transport_spike"},
    )
    session.current_turn_handle = turn_handle
    await session.emit("turn_submit_accepted", "adapter", {"turn_id": session.turn_id, "turn_handle": turn_handle})

    buffered = ""
    spoken_so_far = ""
    saw_final = False
    chunk_index = 0
    try:
        await session.emit("assistant_output_started", "adapter", {"turn_handle": turn_handle})
        async for event in ADAPTER.stream_assistant_output(session.runtime_session_handle, turn_handle):
            event_type = event["type"]
            if event_type == "assistant_text_delta":
                buffered += event["text"]
                await session.emit(
                    "assistant_output_delta",
                    "adapter",
                    {"turn_handle": turn_handle, "delta_chars": len(event["text"]), "buffered_chars": len(buffered)},
                )
                await session.websocket.send_str(json.dumps({"type": "assistant_text_delta", "text": event["text"]}))
                # Progressive chunking: first chunk triggers early (sentence end or 32 chars),
                # later chunks use longer thresholds to reduce TTS call overhead.
                unsent = buffered[len(spoken_so_far):]
                candidate = unsent.strip()
                min_chars = 28 if chunk_index == 0 else 60
                if candidate and (candidate.endswith((".", "!", "?", ";", ":")) or len(candidate) >= min_chars):
                    enqueue_speech(session, candidate)
                    spoken_so_far = buffered
                    chunk_index += 1
            elif event_type == "assistant_text_final":
                saw_final = True
                await session.emit(
                    "assistant_output_completed",
                    "adapter",
                    {"turn_handle": turn_handle, "final_chars": len(event["text"])},
                )
                await session.websocket.send_str(json.dumps({"type": "assistant_text_final", "text": event["text"]}))
                remaining = event["text"][len(spoken_so_far):].strip()
                enqueue_speech(session, remaining)
            elif event_type == "cancel_acknowledged":
                await session.emit("turn_cancel_acknowledged", "adapter", {"turn_handle": turn_handle})
                await session.websocket.send_str(json.dumps({"type": "cancel_status", "result": {"status": "acknowledged"}}))
                return
            elif event_type == "turn_failed":
                await session.emit(
                    "recoverable_error",
                    "adapter",
                    {"component": "turn", "turn_handle": turn_handle, "message": event.get("message", "turn failed")},
                )
                await session.websocket.send_str(json.dumps({"type": "turn_failed", "message": event.get("message", "turn failed")}))
                return
            elif event_type == "turn_completed":
                await session.emit("assistant_output_completed", "adapter", {"turn_handle": turn_handle, "completed_via": "turn_completed"})

        if not saw_final and buffered:
            await session.emit(
                "assistant_output_completed",
                "adapter",
                {"turn_handle": turn_handle, "final_chars": len(buffered), "completed_via": "buffer_flush"},
            )
            await session.websocket.send_str(json.dumps({"type": "assistant_text_final", "text": buffered}))
            remaining = buffered[len(spoken_so_far):].strip()
            enqueue_speech(session, remaining)
    finally:
        clear_turn_state(session)


async def start_assistant_turn(session: Session, transcript: str) -> None:
    if session.current_turn_task is not None and not session.current_turn_task.done():
        await session.emit(
            "recoverable_error",
            "gateway",
            {"component": "control", "message": "turn already active"},
        )
        await session.websocket.send_str(json.dumps({"type": "turn_rejected", "reason": "turn already active"}))
        return

    session.current_turn_task = asyncio.create_task(stream_assistant_turn(session, transcript))


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)

    session = Session(ws)
    await session.emit("session_created", "gateway", {})
    await session.emit("session_connected", "gateway", {})
    await session.emit("session_ready", "gateway", {"sample_rate": TARGET_SAMPLE_RATE})

    try:
      async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            payload = json.loads(msg.data)
            message_type = payload.get("type")

            if message_type == "session_init":
                await session.emit("session_ready", "gateway", {"client_name": payload.get("client_name")})
                health = await ADAPTER.check_health()
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "session_ready",
                            "session_id": session.session_id,
                            "adapter_kind": ADAPTER.adapter_kind,
                            "adapter_health": health.status,
                            "adapter_detail": health.detail,
                        }
                    )
                )
            elif message_type == "mic_stream_started":
                await session.emit(
                    "mic_stream_started",
                    "browser",
                    {"sample_rate": payload.get("sample_rate", TARGET_SAMPLE_RATE)},
                )
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
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "playback_cleared",
                            "generation": session.playback_generation,
                        }
                    )
                )
            elif message_type in {"submit_mock_turn", "submit_turn"}:
                transcript = payload.get("text", "").strip()
                if not transcript:
                    await session.emit("recoverable_error", "gateway", {"component": "control", "message": "empty mock turn"})
                else:
                    await start_assistant_turn(session, transcript)
            elif message_type == "transcribe_recent_audio":
                await session.emit(
                    "transcription_requested",
                    "browser",
                    {
                        "available_samples": len(session.recent_pcm),
                        "engine": "faster-whisper" if STT.available else "fallback",
                        "submit_turn": bool(payload.get("submit_turn")),
                    },
                )
                if not session.recent_pcm:
                    await session.websocket.send_str(json.dumps({"type": "transcript_result", "text": "", "engine": "none"}))
                elif STT.available:
                    try:
                        text = await STT.transcribe(session.recent_pcm, TARGET_SAMPLE_RATE)
                        await session.emit(
                            "final_transcript_ready",
                            "speech",
                            {"char_count": len(text), "engine": "faster-whisper"},
                        )
                        await session.websocket.send_str(
                            json.dumps({"type": "transcript_result", "text": text, "engine": "faster-whisper"})
                        )
                        if payload.get("submit_turn") and text.strip():
                            await start_assistant_turn(session, text.strip())
                        session.recent_pcm.clear()
                    except Exception as exc:
                        await session.emit(
                            "recoverable_error",
                            "speech",
                            {"component": "stt", "message": str(exc), "engine": "faster-whisper"},
                        )
                        await session.websocket.send_str(
                            json.dumps({"type": "transcript_result", "text": "", "engine": "faster-whisper", "error": str(exc)})
                        )
                else:
                    fallback = f"[stt unavailable] captured {len(session.recent_pcm)} samples"
                    await session.emit(
                        "final_transcript_ready",
                        "speech",
                        {"char_count": len(fallback), "engine": "fallback"},
                    )
                    await session.websocket.send_str(
                        json.dumps({"type": "transcript_result", "text": fallback, "engine": "fallback"})
                    )
                    session.recent_pcm.clear()
            elif message_type == "endpoint_candidate":
                await session.emit(
                    "endpoint_timer_started",
                    "browser",
                    {"silence_ms": payload.get("silence_ms")},
                )
            elif message_type == "vad_state":
                session.last_vad_state = payload.get("state", "unknown")
                event_name = "speech_start_detected" if session.last_vad_state == "speech" else "speech_end_detected"
                await session.emit(
                    event_name,
                    "browser",
                    {"state": session.last_vad_state, "rms": payload.get("rms")},
                )
            else:
                await session.emit("recoverable_error", "gateway", {"component": "control", "message": f"unknown control {message_type}"})

        elif msg.type == WSMsgType.BINARY:
            if not msg.data:
                continue
            kind = msg.data[0]
            if kind != PCM_KIND:
                await session.emit("recoverable_error", "gateway", {"component": "transport", "message": f"unknown binary kind {kind}"})
                continue

            session.frames_in += 1
            samples = (len(msg.data) - 1) // 2
            for i in range(1, len(msg.data), 2):
                session.recent_pcm.append(int.from_bytes(msg.data[i:i + 2], "little", signed=True))
            if len(session.recent_pcm) > session.recent_pcm_limit:
                session.recent_pcm = session.recent_pcm[-session.recent_pcm_limit:]
            await session.emit(
                "input_audio_frame_received",
                "gateway",
                {
                    "frame_index": session.frames_in,
                    "frame_bytes": len(msg.data),
                    "frame_samples": samples,
                    "sample_rate": TARGET_SAMPLE_RATE,
                },
            )

        elif msg.type == WSMsgType.ERROR:
            await session.emit("terminal_error", "gateway", {"message": str(ws.exception())})

    finally:
        await cancel_active_turn(session, "socket_disconnected")
        if session.current_turn_task is not None and not session.current_turn_task.done():
            session.current_turn_task.cancel()
        await session.emit("socket_disconnected", "gateway", {})
        await session.emit("session_closed", "gateway", {})

    return ws


async def index_handler(_: web.Request) -> web.StreamResponse:
    request = _
    scheme = "https" if request.secure else "http"
    spike_url = f"{scheme}://{request.host}/spike"
    return web.Response(
        text=(
            "Qantara transport spike gateway is running.\n"
            f"Open {spike_url} to use the browser client.\n"
        ),
        content_type="text/plain",
    )


async def spike_handler(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/spike/index.html")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/spike", spike_handler)
    app.router.add_static("/spike", CLIENT_SPIKE_DIR, show_index=True)
    return app


def create_ssl_context() -> ssl.SSLContext | None:
    if not TLS_CERT_FILE or not TLS_KEY_FILE:
        return None

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(TLS_CERT_FILE, TLS_KEY_FILE)
    return context


if __name__ == "__main__":
    web.run_app(
        create_app(),
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        ssl_context=create_ssl_context(),
    )
