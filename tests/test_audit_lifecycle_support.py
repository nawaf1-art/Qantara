"""Shared fakes for the 2026-09-24 lifecycle audit regression tests.

This module holds no tests itself. It provides a scripted WebSocket that
drives the real gateway receive loop (``run_websocket_session``) without a
network, a TTS fake that returns real (non-empty) PCM samples, and a few
small wait helpers that poll the event loop instead of sleeping on the wall
clock.
"""
from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Callable
from typing import Any

from aiohttp import WSMessage, WSMsgType

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter
from gateway.transport_spike.runtime import GatewayRuntime
from providers.stt.base import STTProvider, STTResult
from tests.test_transport_spike import FakeTTS

PCM_KIND = 0x01


def pcm_frame(value: int, count: int = 640) -> bytes:
    return struct.pack(f"<B{count}h", PCM_KIND, *([value] * count))


class ScriptedWebSocket:
    """Minimal stand-in for aiohttp's WebSocketResponse.

    Tests push inbound messages with ``feed_*``; the gateway loop consumes
    them through async iteration. Everything the gateway sends is recorded.
    """

    def __init__(self) -> None:
        self.closed = False
        self.close_code: int | None = None
        self.strings: list[dict[str, Any]] = []
        self.bytes_payloads: list[bytes] = []
        self._inbox: asyncio.Queue[WSMessage | None] = asyncio.Queue()
        self.consumed = 0

    def feed_json(self, payload: dict[str, Any]) -> None:
        self._inbox.put_nowait(WSMessage(WSMsgType.TEXT, json.dumps(payload), None))

    def feed_text(self, raw: str) -> None:
        self._inbox.put_nowait(WSMessage(WSMsgType.TEXT, raw, None))

    def feed_bytes(self, payload: bytes) -> None:
        self._inbox.put_nowait(WSMessage(WSMsgType.BINARY, payload, None))

    def finish(self) -> None:
        self._inbox.put_nowait(None)

    def __aiter__(self) -> ScriptedWebSocket:
        return self

    async def __anext__(self) -> WSMessage:
        item = await self._inbox.get()
        if item is None:
            self.closed = True
            raise StopAsyncIteration
        self.consumed += 1
        return item

    def pending_inbound(self) -> int:
        return self._inbox.qsize()

    async def send_str(self, data: str) -> None:
        self.strings.append(json.loads(data))

    async def send_bytes(self, data: bytes) -> None:
        self.bytes_payloads.append(data)

    async def close(self, **_kwargs: Any) -> bool:
        self.closed = True
        return True

    def exception(self) -> BaseException | None:
        return None

    def of_type(self, message_type: str) -> list[dict[str, Any]]:
        return [m for m in self.strings if m.get("type") == message_type]


class RecordingSTT(STTProvider):
    kind = "recording_stt"

    def __init__(self, text: str = "ok", language: str | None = "en", probability: float | None = 0.99) -> None:
        self.calls: list[list[int]] = []
        self.text = text
        self.language = language
        self.probability = probability

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, samples: list[int], sample_rate: int) -> STTResult:
        self.calls.append(list(samples))
        return STTResult(text=self.text, language=self.language, language_probability=self.probability)


class SampleTTS(FakeTTS):
    """FakeTTS that returns real samples so the playback frame loop runs."""

    def __init__(self, samples_per_call: int = 1920 * 2) -> None:
        super().__init__()
        self.samples_per_call = samples_per_call
        self.gates: dict[int, asyncio.Event] = {}
        self.entered: dict[int, asyncio.Event] = {}

    def gate(self, call_index: int) -> asyncio.Event:
        """Block the call with this zero-based index until the event is set."""
        event = asyncio.Event()
        self.gates[call_index] = event
        self.entered[call_index] = asyncio.Event()
        return event

    async def synthesize(self, text, voice_id=None, speech_rate=None, *, expressiveness=None):  # type: ignore[override]
        index = len(self.spoken)
        self.spoken.append(text)
        self.requested_voice_ids.append(voice_id)
        self.requested_speech_rates.append(speech_rate)
        if index in self.entered:
            self.entered[index].set()
        gate = self.gates.get(index)
        if gate is not None:
            await gate.wait()
        voice, _ = self.resolve_voice(voice_id)
        return [1000] * self.samples_per_call, voice, None


class ScriptAdapter(RuntimeAdapter):
    """Adapter whose stream is a list of events, optionally blocking at a
    marker until the test releases it or cancel_turn is called."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        super().__init__(AdapterConfig(kind="mock", name="script"))
        self.events = events if events is not None else [
            {"type": "assistant_text_delta", "text": "Hello there."},
            {"type": "turn_completed"},
        ]
        self.sessions_started = 0
        self.submits: list[tuple[str, str, dict[str, Any]]] = []
        self.cancel_calls: list[dict[str, Any]] = []
        self.cancelled = asyncio.Event()
        self.block_after: int | None = None
        self.stream_blocked = asyncio.Event()
        self.release_stream = asyncio.Event()
        self.ack_on_cancel = True
        self.cancel_delay_event: asyncio.Event | None = None

    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        self.sessions_started += 1
        return f"rt-{self.sessions_started}"

    async def submit_user_turn(self, session_handle: str, transcript: str, turn_context: dict | None = None) -> str:
        self.submits.append((session_handle, transcript, dict(turn_context or {})))
        return f"turn-{len(self.submits)}"

    async def stream_assistant_output(self, session_handle: str, turn_handle: str):
        for index, event in enumerate(self.events):
            if self.block_after is not None and index == self.block_after:
                self.stream_blocked.set()
                waiter = asyncio.ensure_future(self.release_stream.wait())
                cancel_waiter = asyncio.ensure_future(self.cancelled.wait())
                try:
                    await asyncio.wait({waiter, cancel_waiter}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    waiter.cancel()
                    cancel_waiter.cancel()
                if self.cancelled.is_set() and self.ack_on_cancel:
                    yield {"type": "cancel_acknowledged"}
                    return
            yield event

    async def cancel_turn(self, session_handle: str, turn_handle: str, cancel_context: dict | None = None) -> dict:
        self.cancel_calls.append({"handle": turn_handle, **(cancel_context or {})})
        if self.cancel_delay_event is not None:
            await self.cancel_delay_event.wait()
        self.cancelled.set()
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")


def make_runtime(
    adapter: RuntimeAdapter | None = None,
    *,
    stt: STTProvider | None = None,
    tts: FakeTTS | None = None,
) -> tuple[GatewayRuntime, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    runtime = GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=stt or RecordingSTT(),
        tts=tts or FakeTTS(),
        event_sink=events.append,
    )
    if adapter is not None:
        runtime.default_binding().adapter = adapter
    return runtime, events


async def wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    """Yield to the loop until ``predicate`` holds (fails after ``timeout``)."""
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(_poll(), timeout=timeout)


def event_names(events: list[dict[str, Any]]) -> list[str]:
    return [e["event_name"] for e in events]


def count_events(events: list[dict[str, Any]], name: str) -> int:
    return sum(1 for e in events if e["event_name"] == name)


async def start_ws_session(
    runtime: GatewayRuntime,
    client_session_id: str = "client",
) -> tuple[ScriptedWebSocket, asyncio.Task]:
    from gateway.transport_spike.websocket_api import run_websocket_session

    ws = ScriptedWebSocket()
    task = asyncio.create_task(run_websocket_session(ws, runtime))
    ws.feed_json({"type": "session_init", "client_session_id": client_session_id})
    await wait_until(lambda: bool(ws.of_type("session_ready")))
    return ws, task


async def drain_inbox(ws: ScriptedWebSocket, *, timeout: float = 2.0) -> None:
    await wait_until(lambda: ws.pending_inbound() == 0, timeout=timeout)
    # One extra turn of the loop so the last message's handler completes.
    for _ in range(5):
        await asyncio.sleep(0)


async def close_ws_session(ws: ScriptedWebSocket, task: asyncio.Task) -> None:
    ws.finish()
    await asyncio.wait_for(task, timeout=5.0)
