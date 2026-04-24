from __future__ import annotations

import unittest

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime, Session
from tests.test_transport_spike import DummyWebSocket, FakeSTT, FakeTTS


def _make_runtime() -> GatewayRuntime:
    return GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock-initial"),
        stt=FakeSTT(),
        tts=FakeTTS(),
        event_sink=lambda record: None,
    )


class BackendSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnecting_session_picks_up_new_default_binding(self) -> None:
        runtime = _make_runtime()

        first_ws = DummyWebSocket()
        first = Session(first_ws, runtime)
        first.client_session_id = "client-abc"
        runtime.register_session(first)
        original_binding_id = first.binding.binding_id

        new_binding = await runtime.configure_backend("mock")
        self.assertNotEqual(new_binding.binding_id, original_binding_id)
        self.assertEqual(runtime.default_binding_id, new_binding.binding_id)

        runtime.release_session(first)

        second_ws = DummyWebSocket()
        second = Session(second_ws, runtime)
        second.client_session_id = "client-abc"
        runtime.register_session(second)

        self.assertEqual(
            second.binding.binding_id,
            new_binding.binding_id,
            "returning session must follow the new default backend, not the stale snapshot",
        )

    async def test_voice_prefs_survive_backend_switch(self) -> None:
        runtime = _make_runtime()

        ws = DummyWebSocket()
        session = Session(ws, runtime)
        session.client_session_id = "client-voice"
        runtime.register_session(session)
        session.voice_id = "amy"
        session.speech_rate = 1.2
        session.client_name = "kitchen-speaker"
        runtime.save_session_state(session)
        runtime.release_session(session)

        await runtime.configure_backend("mock")

        ws2 = DummyWebSocket()
        returning = Session(ws2, runtime)
        returning.client_session_id = "client-voice"
        runtime.register_session(returning)

        self.assertEqual(returning.voice_id, "amy")
        self.assertEqual(returning.speech_rate, 1.2)
        self.assertEqual(returning.client_name, "kitchen-speaker")


if __name__ == "__main__":
    unittest.main()
