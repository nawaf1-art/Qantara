"""Gateway-level check: a missing voice surfaces as no_voice_for_language.

Uses the unmodified gateway speak path with a routed provider of fake
engines, so no model is loaded.
"""
from __future__ import annotations

import unittest

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime, Session
from gateway.transport_spike.speech import speak_text
from providers.tts.routing import RoutedTTSProvider
from tests.test_audit_speech_tts import ScriptedTTS, _kokoro_like, _piper_like
from tests.test_transport_spike import DummyWebSocket, FakeSTT


def _session(tts) -> tuple[Session, DummyWebSocket]:
    runtime = GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=FakeSTT(),
        tts=tts,
        event_sink=lambda _r: None,
    )
    ws = DummyWebSocket()
    session = Session(ws, runtime)
    session.client_session_id = "c"
    runtime.register_session(session)
    return session, ws


class GatewayNoVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_arabic_reply_without_arabic_voice_reports_reason(self) -> None:
        kokoro = _kokoro_like()
        session, ws = _session(RoutedTTSProvider([kokoro, ScriptedTTS("piper", [("lessac", "en-US")])]))
        await speak_text(session, "مرحبا، كيف حالك اليوم؟")
        reasons = [m.get("reason") or "" for m in ws.strings if m.get("type") == "tts_status"]
        self.assertTrue(any("no_voice_for_language" in r for r in reasons), reasons)
        self.assertEqual(kokoro.calls, [])

    async def test_arabic_reply_routes_to_piper_voice(self) -> None:
        kokoro, piper = _kokoro_like(), _piper_like()
        session, _ws = _session(RoutedTTSProvider([kokoro, piper]))
        session.voice_id = "af_heart"
        await speak_text(session, "مرحبا، كيف حالك اليوم؟")
        self.assertEqual(piper.calls[-1][1], "ar_JO-kareem-medium")
        self.assertEqual(kokoro.calls, [])


if __name__ == "__main__":
    unittest.main()
