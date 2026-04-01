import asyncio
import json
import math
import os
import sys
import time
import uuid
from aiohttp import WSMsgType, web

CURRENT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from adapters.mock_adapter import MockAdapter


PCM_KIND = 0x01
TARGET_SAMPLE_RATE = 16000
TONE_HZ = 440.0
TONE_SECONDS = 1.25
FRAME_SAMPLES = 640


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


ADAPTER = MockAdapter()


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
    for offset in range(0, total_samples, FRAME_SAMPLES):
        if generation != session.playback_generation:
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
            return
        frame = []
        for i in range(offset, min(offset + FRAME_SAMPLES, total_samples)):
            value = math.sin(2 * math.pi * TONE_HZ * (i / TARGET_SAMPLE_RATE))
            frame.append(int(amplitude * value))
        await session.websocket.send_bytes(encode_pcm_frame(frame))
        session.frames_out += 1
        sent_any = True
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
        await session.emit("playback_stopped", "playback", {"reason": "tone_complete"})


async def stream_mock_assistant(session: Session, transcript: str) -> None:
    if session.runtime_session_handle is None:
        session.runtime_session_handle = await ADAPTER.start_or_resume_session(
            {"client_name": "browser-transport-spike", "session_id": session.session_id}
        )
        await session.emit(
            "adapter_session_ready",
            "adapter",
            {"runtime_session_handle": session.runtime_session_handle},
        )

    session.turn_id = str(uuid.uuid4())
    await session.emit("turn_submit_started", "adapter", {"turn_id": session.turn_id, "transcript": transcript})
    turn_handle = await ADAPTER.submit_user_turn(
        session.runtime_session_handle,
        transcript,
        {"source": "transport_spike"},
    )
    await session.emit("turn_submit_accepted", "adapter", {"turn_id": session.turn_id, "turn_handle": turn_handle})

    buffered = ""
    await session.emit("assistant_output_started", "adapter", {"turn_handle": turn_handle})
    async for event in ADAPTER.stream_assistant_output(session.runtime_session_handle, turn_handle):
        if event["type"] == "assistant_text_delta":
            buffered += event["text"]
            await session.emit(
                "assistant_output_delta",
                "adapter",
                {"turn_handle": turn_handle, "delta_chars": len(event["text"]), "buffered_chars": len(buffered)},
            )
            await session.websocket.send_str(json.dumps({"type": "assistant_text_delta", "text": event["text"]}))
        elif event["type"] == "assistant_text_final":
            await session.emit(
                "assistant_output_completed",
                "adapter",
                {"turn_handle": turn_handle, "final_chars": len(event["text"])},
            )
            await session.websocket.send_str(json.dumps({"type": "assistant_text_final", "text": event["text"]}))


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
                await ws.send_str(json.dumps({"type": "session_ready", "session_id": session.session_id}))
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
                await session.emit("playback_queue_cleared", "browser", {})
            elif message_type == "submit_mock_turn":
                transcript = payload.get("text", "").strip()
                if not transcript:
                    await session.emit("recoverable_error", "gateway", {"component": "control", "message": "empty mock turn"})
                else:
                    await stream_mock_assistant(session, transcript)
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
        await session.emit("socket_disconnected", "gateway", {})
        await session.emit("session_closed", "gateway", {})

    return ws


async def index_handler(_: web.Request) -> web.StreamResponse:
    return web.Response(
        text=(
            "Qantara transport spike gateway is running.\n"
            "Open client/transport-spike/index.html with a static file server and connect to ws://host:8765/ws\n"
        ),
        content_type="text/plain",
    )


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", websocket_handler)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8765)
