from __future__ import annotations

import unittest

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter
from gateway.transport_spike.server import (
    GatewayRuntime,
    Session,
    ensure_adapter_session,
    stream_assistant_turn,
)
from providers.stt.base import STTProvider
from providers.tts.base import TTSProvider, VoiceSpec


class DummyWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self.strings: list[dict] = []
        self.bytes_payloads: list[bytes] = []
        self.close_code = None

    async def send_str(self, data: str) -> None:
        import json

        self.strings.append(json.loads(data))

    async def send_bytes(self, data: bytes) -> None:
        self.bytes_payloads.append(data)

    def exception(self):  # noqa: ANN001
        return None


class FakeSTT(STTProvider):
    kind = "fake_stt"

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, samples: list[int], sample_rate: int):  # type: ignore[override]
        from providers.stt.base import STTResult
        return STTResult(text=f"{len(samples)}@{sample_rate}", language="en", language_probability=0.99)


class FakeTTS(TTSProvider):
    kind = "fake_tts"

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.requested_voice_ids: list[str | None] = []
        self.requested_speech_rates: list[float | None] = []

    @property
    def available(self) -> bool:
        return True

    @property
    def default_voice_id(self) -> str | None:
        return "fake_voice"

    def list_available_voices(self) -> list[dict]:
        return [
            {"voice_id": "fake_voice", "label": "Fake Voice", "locale": "en-US", "defaults": {"rate": 1.0}},
            {"voice_id": "ar_JO-kareem-medium", "label": "Kareem", "locale": "ar-JO", "defaults": {"rate": 1.3}},
        ]

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        resolved_id = voice_id or "fake_voice"
        if resolved_id == "ar_JO-kareem-medium":
            return VoiceSpec(
                voice_id=resolved_id,
                label="Kareem",
                sample_rate=22050,
                locale="ar-JO",
                defaults={"rate": 1.3, "pitch": 0, "tone": "neutral"},
                allowed_transforms=["rate"],
            ), None
        return VoiceSpec(
            voice_id=resolved_id,
            label="Fake Voice",
            sample_rate=16000,
            locale="en-US",
            defaults={"rate": 1.0, "pitch": 0, "tone": "neutral"},
            allowed_transforms=["rate"],
        ), None

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
        *,
        expressiveness: float | None = None,  # noqa: ARG002
    ) -> tuple[list[int], VoiceSpec, str | None]:
        self.spoken.append(text)
        self.requested_voice_ids.append(voice_id)
        self.requested_speech_rates.append(speech_rate)
        voice, _ = self.resolve_voice(voice_id)
        return [], voice, None


class DeltaOnlyAdapter(RuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(AdapterConfig(kind="mock", name="delta-only"))
        self._turns: dict[str, str] = {}

    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        return "runtime-session"

    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        turn_handle = f"turn-{len(self._turns) + 1}"
        self._turns[turn_handle] = transcript
        return turn_handle

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict:
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")

    async def stream_assistant_output(self, session_handle: str, turn_handle: str):
        yield {"type": "assistant_text_delta", "text": "Hello there"}
        yield {"type": "turn_completed"}


class TransportSpikeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tts = FakeTTS()
        self.runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=self.tts,
            event_sink=lambda record: None,
        )

    async def test_stream_turn_flushes_delta_only_output(self) -> None:
        binding = self.runtime.default_binding()
        binding.adapter = DeltaOnlyAdapter()
        ws = DummyWebSocket()
        session = Session(ws, self.runtime)
        session.client_session_id = "client-a"
        self.runtime.register_session(session)

        await stream_assistant_turn(session, "hello")
        if session.speech_task is not None:
            await session.speech_task

        self.assertIn("Hello there", self.tts.spoken)
        final_messages = [m for m in ws.strings if m.get("type") == "assistant_text_final"]
        self.assertTrue(final_messages)
        self.assertEqual(final_messages[-1]["text"], "Hello there")

    async def test_runtime_close_terminates_managed_bridge_processes(self) -> None:
        import asyncio

        from gateway.transport_spike.runtime import BackendBinding

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode: int | None = None
                self.terminated = False
                self.killed = False

            def terminate(self) -> None:
                self.terminated = True
                self.returncode = 0

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

            async def wait(self) -> int:
                await asyncio.sleep(0)
                return self.returncode or 0

        proc = _FakeProc()
        binding = BackendBinding(
            binding_id="fake-binding",
            backend_type="ollama",
            adapter_config=AdapterConfig(kind="session_gateway_http", name="ollama"),
            adapter=self.runtime.default_binding().adapter,
            managed_bridge_type="ollama",
            managed_bridge_proc=proc,
            managed_bridge_port=19999,
        )
        self.runtime._bindings[binding.binding_id] = binding
        await self.runtime.close()
        self.assertTrue(proc.terminated)
        self.assertFalse(proc.killed)

    async def test_reconnect_without_configure_keeps_binding_and_runtime_session(self) -> None:
        first_ws = DummyWebSocket()
        first = Session(first_ws, self.runtime)
        first.client_session_id = "sticky-client"
        self.runtime.register_session(first)
        await ensure_adapter_session(first)
        original_binding_id = first.binding.binding_id
        original_handle = first.runtime_session_handle
        self.runtime.release_session(first)

        second_ws = DummyWebSocket()
        second = Session(second_ws, self.runtime)
        second.client_session_id = "sticky-client"
        self.runtime.register_session(second)

        self.assertEqual(second.binding.binding_id, original_binding_id)
        self.assertEqual(second.runtime_session_handle, original_handle)

    async def test_reconnect_after_configure_follows_new_binding_and_drops_stale_handle(self) -> None:
        first_ws = DummyWebSocket()
        first = Session(first_ws, self.runtime)
        first.client_session_id = "sticky-client"
        self.runtime.register_session(first)
        await ensure_adapter_session(first)
        original_binding_id = first.binding.binding_id
        self.runtime.release_session(first)

        new_binding = await self.runtime.configure_backend("mock")
        self.assertNotEqual(new_binding.binding_id, original_binding_id)

        second_ws = DummyWebSocket()
        second = Session(second_ws, self.runtime)
        second.client_session_id = "sticky-client"
        self.runtime.register_session(second)

        self.assertEqual(second.binding.binding_id, new_binding.binding_id)
        self.assertIsNone(second.runtime_session_handle)
