from __future__ import annotations

import unittest

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime, Session
from gateway.transport_spike.speech import apply_voice_transforms
from providers.tts.base import VoiceSpec
from tests.test_transport_spike import DummyWebSocket, FakeSTT, FakeTTS


class _FakeTTSAllowingExpressiveness(FakeTTS):
    kind = "fake-allows-expr"
    _allowed: list[str]

    def __init__(self, allowed: list[str]) -> None:
        super().__init__()
        self._allowed = allowed

    def resolve_voice(self, voice_id):
        return VoiceSpec(
            voice_id="warm",
            label="Warm",
            locale="en-US",
            sample_rate=24000,
            defaults={"rate": 1.0, "expressiveness": 0.5},
            allowed_transforms=self._allowed,
        ), None


class VoiceTransformExpressivenessTests(unittest.IsolatedAsyncioTestCase):
    def _make_session(self, allowed: list[str]) -> Session:
        runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=_FakeTTSAllowingExpressiveness(allowed),
            event_sink=lambda _r: None,
        )
        session = Session(DummyWebSocket(), runtime)
        runtime.register_session(session)
        return session

    async def test_expressiveness_accepted_when_allowed(self) -> None:
        session = self._make_session(["rate", "expressiveness"])
        result = apply_voice_transforms(session, None, None, 0.8)
        self.assertAlmostEqual(session.expressiveness, 0.8)
        self.assertIn("expressiveness", result["active_transforms"])

    async def test_expressiveness_clamped_to_unit_interval(self) -> None:
        session = self._make_session(["rate", "expressiveness"])
        apply_voice_transforms(session, None, None, 1.5)
        self.assertEqual(session.expressiveness, 1.0)
        apply_voice_transforms(session, None, None, -0.2)
        self.assertEqual(session.expressiveness, 0.0)

    async def test_expressiveness_dropped_when_not_allowed(self) -> None:
        session = self._make_session(["rate"])
        result = apply_voice_transforms(session, None, None, 0.8)
        self.assertIsNone(session.expressiveness)
        self.assertNotIn("expressiveness", result["active_transforms"])


if __name__ == "__main__":
    unittest.main()
