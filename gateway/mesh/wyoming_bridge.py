from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from wyoming.event import Event
from wyoming.info import Attribution, Info, Satellite
from wyoming.server import AsyncEventHandler

from gateway.transport_spike.common import TARGET_SAMPLE_RATE

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineContext:
    """Thin dispatch layer between Wyoming events and Qantara's audio
    pipeline. The WyomingBridge holds one of these per connection and
    funnels incoming audio-chunks to the registered callable."""

    on_audio_chunk: Callable[[bytes, int], Awaitable[None]] | None = None
    on_audio_stop: Callable[[], Awaitable[None]] | None = None

    async def handle_audio_chunk(self, pcm: bytes, rate: int) -> None:
        if self.on_audio_chunk is not None:
            await self.on_audio_chunk(pcm, rate)

    async def handle_audio_stop(self) -> None:
        if self.on_audio_stop is not None:
            await self.on_audio_stop()


class SessionConnector:
    """Glues a Wyoming connection into Qantara's STT/adapter/TTS. One
    per Wyoming connection. Accumulates audio-chunks until audio-stop,
    then runs the turn through the runtime's default binding and
    streams TTS back to HA as audio-chunk frames."""

    def __init__(self, runtime, writer) -> None:  # type: ignore[no-untyped-def]
        self._runtime = runtime
        self._writer = writer
        self._pcm_buffer: bytearray = bytearray()
        self._rate = TARGET_SAMPLE_RATE

    def context(self) -> PipelineContext:
        return PipelineContext(
            on_audio_chunk=self._accept_chunk,
            on_audio_stop=self._finalize,
        )

    async def _accept_chunk(self, pcm: bytes, rate: int) -> None:
        self._rate = rate
        self._pcm_buffer.extend(pcm)

    async def _finalize(self) -> None:
        import struct
        if not self._pcm_buffer:
            return
        sample_count = len(self._pcm_buffer) // 2
        samples = list(struct.unpack(f"<{sample_count}h", bytes(self._pcm_buffer)))
        self._pcm_buffer.clear()
        # STT
        stt_result = await self._runtime.stt.transcribe(samples, self._rate)
        text = stt_result.text if hasattr(stt_result, "text") else str(stt_result)
        if not text.strip():
            return
        # Adapter
        binding = self._runtime.default_binding()
        handle = await binding.adapter.start_or_resume_session({"source": "wyoming"})
        turn_handle = await binding.adapter.submit_user_turn(handle, text, {"source": "wyoming"})
        response_text = ""
        async for event in binding.adapter.stream_assistant_output(handle, turn_handle):
            etype = event.get("type")
            if etype == "assistant_text_delta":
                response_text += event.get("text", "")
            elif etype == "assistant_text_final":
                response_text = event.get("text") or response_text
                break
            elif etype == "turn_completed":
                break
        if not response_text.strip():
            return
        # TTS
        tts_result = await self._runtime.tts.synthesize(response_text)
        # synthesize may return (samples, voice, _fallback_reason); accept both 2- and 3-tuple
        if len(tts_result) == 3:
            out_samples, voice, _ = tts_result
        else:
            out_samples, voice = tts_result
        if not out_samples:
            return
        pcm_bytes = struct.pack(f"<{len(out_samples)}h", *out_samples)
        await _write_event(self._writer, Event(type="audio-start", data={
            "rate": voice.sample_rate, "width": 2, "channels": 1,
        }, payload=None))
        frame_samples = int(voice.sample_rate * 0.02)
        frame_bytes = frame_samples * 2
        for offset in range(0, len(pcm_bytes), frame_bytes):
            chunk = pcm_bytes[offset:offset + frame_bytes]
            await _write_event(self._writer, Event(type="audio-chunk", data={
                "rate": voice.sample_rate, "width": 2, "channels": 1,
            }, payload=chunk))
        await _write_event(self._writer, Event(type="audio-stop", data={}, payload=None))


def build_satellite_info(node_name: str, area: str, version: str, has_vad: bool) -> Info:
    """Shape the Wyoming Info event that HA uses to describe the satellite."""
    satellite = Satellite(
        name=node_name,
        area=area or None,
        has_vad=has_vad,
        installed=True,
        description=f"Qantara voice satellite ({node_name})",
        version=version,
        attribution=Attribution(name="Qantara", url="https://github.com/nawaf1-art/Qantara"),
    )
    return Info(satellite=satellite)


class QantaraWyomingHandler(AsyncEventHandler):
    """Per-connection Wyoming event handler. HA opens one of these per
    session (normally just one). 0.2.2 ships with a minimal handshake:
    `describe` returns our Info. Subsequent tasks will handle
    run-pipeline / audio-start / audio-chunk / audio-stop."""

    def __init__(self, info: Info, reader, writer) -> None:  # type: ignore[no-untyped-def]
        super().__init__(reader, writer)
        self._info = info

    async def handle_event(self, event: Event) -> bool:
        event_type = event.type
        if event_type == "describe":
            await self.write_event(self._info.event())
            return True
        # Unknown event — return True to keep the connection alive; the
        # actual pipeline handling lands in Task D3.
        LOGGER.debug("wyoming: ignoring event %s (not yet implemented)", event_type)
        return True


class WyomingBridge:
    """Runs a Wyoming satellite over TCP on the configured port and
    optionally registers it via mDNS on _wyoming._tcp.local. so HA
    auto-discovers it."""

    def __init__(
        self,
        node_name: str,
        area: str,
        port: int,
        version: str,
        has_vad: bool,
        runtime=None,  # type: ignore[no-untyped-def]
        register_zeroconf: bool = True,
        host: str = "127.0.0.1",
    ) -> None:
        self._info = build_satellite_info(node_name, area, version, has_vad)
        self._host = host
        self._port = port
        self._register_zeroconf = register_zeroconf
        self._runtime = runtime
        self._server = None
        self._aiozc = None

    async def start(self) -> None:
        # Simple raw asyncio server — we parse Wyoming frames ourselves.
        # The wyoming package provides AsyncServer but it's designed
        # for standalone use; a small handler keeps Qantara's event
        # loop ownership clean.
        async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            if self._runtime is not None:
                ctx = SessionConnector(self._runtime, writer).context()
            else:
                ctx = PipelineContext()
            try:
                while not reader.at_eof():
                    header_line = await reader.readline()
                    if not header_line:
                        break
                    try:
                        header = _json_loads(header_line)
                    except Exception:
                        LOGGER.debug("wyoming: malformed header; closing")
                        break
                    data_length = int(header.get("data_length") or 0)
                    payload_length = int(header.get("payload_length") or 0)
                    data_extra = b""
                    if data_length > 0:
                        data_extra = await reader.readexactly(data_length)
                    payload = b""
                    if payload_length > 0:
                        payload = await reader.readexactly(payload_length)
                    event = _event_from_frame(header, data_extra, payload)
                    if event.type == "describe":
                        await _write_event(writer, self._info.event())
                    elif event.type == "audio-chunk":
                        rate = int((event.data or {}).get("rate", 16000))
                        await ctx.handle_audio_chunk(event.payload or b"", rate)
                    elif event.type == "audio-stop":
                        await ctx.handle_audio_stop()
                    else:
                        LOGGER.debug("wyoming: unhandled event type %s", event.type)
            except (asyncio.IncompleteReadError, ConnectionResetError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        self._server = await asyncio.start_server(_handle, self._host, self._port)
        if self._register_zeroconf:
            await self._register_mdns()

    async def stop(self) -> None:
        if self._aiozc is not None:
            await self._aiozc.async_close()
            self._aiozc = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _register_mdns(self) -> None:
        import socket

        from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf
        self._aiozc = AsyncZeroconf()
        info = AsyncServiceInfo(
            type_="_wyoming._tcp.local.",
            name=f"qantara-{self._info.satellite.name}._wyoming._tcp.local.",
            addresses=[socket.inet_aton(_resolve_local_ipv4_for_wyoming())],
            port=self._port,
            properties={},
            server=f"qantara-{self._info.satellite.name}-wyoming.local.",
        )
        await self._aiozc.async_register_service(info)


def _resolve_local_ipv4_for_wyoming() -> str:
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.168.1.1", 9))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        return "127.0.0.1"


def _json_loads(data: bytes):  # type: ignore[return]
    return json.loads(data.decode("utf-8").strip())


def _event_from_frame(header: dict, data_extra: bytes, payload: bytes) -> Event:
    data = dict(header.get("data") or {})
    if data_extra:
        merged = json.loads(data_extra.decode("utf-8"))
        data.update(merged)
    return Event(type=header["type"], data=data, payload=payload or None)


async def _write_event(writer: asyncio.StreamWriter, event: Event) -> None:
    header: dict = {"type": event.type}
    data_bytes = b""
    if event.data:
        data_bytes = json.dumps(event.data).encode("utf-8")
        header["data_length"] = len(data_bytes)
    payload_bytes = event.payload or b""
    if payload_bytes:
        header["payload_length"] = len(payload_bytes)
    writer.write((json.dumps(header) + "\n").encode("utf-8"))
    if data_bytes:
        writer.write(data_bytes)
    if payload_bytes:
        writer.write(payload_bytes)
    await writer.drain()
