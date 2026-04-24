from __future__ import annotations

import unittest

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime, Session
from tests.test_transport_spike import DummyWebSocket, FakeSTT, FakeTTS


def _make_runtime() -> GatewayRuntime:
    return GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=FakeSTT(),
        tts=FakeTTS(),
        event_sink=lambda _record: None,
    )


class ExpressivenessSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_defaults_expressiveness_to_none(self) -> None:
        runtime = _make_runtime()
        session = Session(DummyWebSocket(), runtime)
        self.assertIsNone(session.expressiveness)

    async def test_snapshot_round_trips_expressiveness(self) -> None:
        runtime = _make_runtime()
        ws = DummyWebSocket()
        first = Session(ws, runtime)
        first.client_session_id = "c-1"
        runtime.register_session(first)
        first.expressiveness = 0.7
        runtime.save_session_state(first)
        runtime.release_session(first)

        second = Session(DummyWebSocket(), runtime)
        second.client_session_id = "c-1"
        runtime.register_session(second)
        self.assertEqual(second.expressiveness, 0.7)


if __name__ == "__main__":
    unittest.main()
