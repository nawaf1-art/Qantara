from __future__ import annotations

import unittest

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime, Session
from tests.test_transport_spike import DummyWebSocket, FakeSTT, FakeTTS


class SessionTranslationStateTests(unittest.IsolatedAsyncioTestCase):
    def _make_runtime(self) -> GatewayRuntime:
        return GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda _r: None,
        )

    async def test_session_defaults(self) -> None:
        session = Session(DummyWebSocket(), self._make_runtime())
        self.assertIsNone(session.input_language)
        self.assertEqual(session.primary_language, "en")
        self.assertIsNone(session.translation_mode)
        self.assertIsNone(session.translation_source)
        self.assertIsNone(session.translation_target)

    async def test_snapshot_round_trip(self) -> None:
        runtime = self._make_runtime()
        first = Session(DummyWebSocket(), runtime)
        first.client_session_id = "client-xyz"
        runtime.register_session(first)
        first.primary_language = "ar"
        first.translation_mode = "directional"
        first.translation_source = "en"
        first.translation_target = "ar"
        runtime.save_session_state(first)
        runtime.release_session(first)

        second = Session(DummyWebSocket(), runtime)
        second.client_session_id = "client-xyz"
        runtime.register_session(second)

        self.assertEqual(second.primary_language, "ar")
        self.assertEqual(second.translation_mode, "directional")
        self.assertEqual(second.translation_source, "en")
        self.assertEqual(second.translation_target, "ar")


if __name__ == "__main__":
    unittest.main()
