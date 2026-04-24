from __future__ import annotations

import unittest
from typing import Any

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime, Session
from gateway.transport_spike.speech import start_assistant_turn
from tests.test_transport_spike import DeltaOnlyAdapter, DummyWebSocket, FakeSTT, FakeTTS


class CapturingAdapter(DeltaOnlyAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.submitted: list[dict[str, Any]] = []

    async def submit_user_turn(self, handle, transcript, context):  # type: ignore[override]
        self.submitted.append({"transcript": transcript, "context": dict(context)})
        return await super().submit_user_turn(handle, transcript, context)


class SpeechTranslationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def _run_turn(self, *, mode: str | None, input_lang: str | None, source: str | None, target: str | None) -> CapturingAdapter:
        _adapter, _session, _runtime, tts = await self._run_turn_with_session(
            mode=mode,
            input_lang=input_lang,
            source=source,
            target=target,
        )
        self.last_tts = tts
        return _adapter

    async def _run_turn_with_session(self, *, mode: str | None, input_lang: str | None, source: str | None, target: str | None):
        tts = FakeTTS()
        runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=tts,
            event_sink=lambda _r: None,
        )
        session = Session(DummyWebSocket(), runtime)
        session.client_session_id = "c"
        runtime.register_session(session)
        adapter = CapturingAdapter()
        session.binding.adapter = adapter
        session.translation_mode = mode
        session.input_language = input_lang
        session.translation_source = source
        session.translation_target = target
        await start_assistant_turn(session, "test message")
        if session.current_turn_task is not None:
            try:
                await session.current_turn_task
            except Exception:
                pass
        if session.speech_task is not None:
            try:
                await session.speech_task
            except Exception:
                pass
        return adapter, session, runtime, tts

    async def test_assistant_mode_adds_directive_and_language(self) -> None:
        adapter = await self._run_turn(mode="assistant", input_lang="es", source=None, target=None)
        ctx = adapter.submitted[0]["context"]
        self.assertEqual(ctx.get("input_language"), "es")
        self.assertIn("same language", ctx.get("translation_directive", "").lower())

    async def test_directional_mode_adds_pair_directive(self) -> None:
        adapter = await self._run_turn(mode="directional", input_lang="en", source="en", target="ar")
        ctx = adapter.submitted[0]["context"]
        self.assertIn("arabic", ctx.get("translation_directive", "").lower())
        self.assertIn("respond only in", ctx.get("translation_directive", "").lower())

    async def test_no_mode_no_directive(self) -> None:
        adapter = await self._run_turn(mode=None, input_lang=None, source=None, target=None)
        ctx = adapter.submitted[0]["context"]
        self.assertNotIn("translation_directive", ctx)

    async def test_arabic_turn_routes_to_arabic_voice_when_available(self) -> None:
        _adapter, _session, _runtime, tts = await self._run_turn_with_session(
            mode="assistant",
            input_lang="ar",
            source=None,
            target=None,
        )

        self.assertIn("ar_JO-kareem-medium", tts.requested_voice_ids)
        self.assertIn(1.3, tts.requested_speech_rates)


if __name__ == "__main__":
    unittest.main()
