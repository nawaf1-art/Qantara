from __future__ import annotations

import asyncio
import io
import json
import unittest
import wave

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter
from gateway.transport_spike.auth import AUTH_TOKEN_KEY
from gateway.transport_spike.http_api import APP_RUNTIME_KEY, mount_static_routes
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS


class SamplesFakeTTS(FakeTTS):
    """FakeTTS that returns real PCM samples so audio responses have frames."""

    async def synthesize(self, text, voice_id=None, speech_rate=None, *, expressiveness=None):
        _, voice, reason = await super().synthesize(text, voice_id, speech_rate, expressiveness=expressiveness)
        return [100, -100, 200, -200, 300, -300], voice, reason


def _make_app(auth_token: str | None = None) -> web.Application:
    app = web.Application()
    app[APP_RUNTIME_KEY] = GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=FakeSTT(),
        tts=SamplesFakeTTS(),
        event_sink=lambda _r: None,
    )
    app[AUTH_TOKEN_KEY] = auth_token
    mount_static_routes(app)
    return app


def _wav_bytes(samples: list[int], sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        raw = bytearray()
        for sample in samples:
            raw.extend(int(sample).to_bytes(2, "little", signed=True))
        wav_file.writeframes(bytes(raw))
    return buf.getvalue()


class VoiceAPITestBase(unittest.IsolatedAsyncioTestCase):
    auth_token: str | None = None

    async def asyncSetUp(self) -> None:
        self.app = _make_app(self.auth_token)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()


class SpeakEndpointTests(VoiceAPITestBase):
    async def test_speak_returns_wav_audio(self) -> None:
        resp = await self.client.post("/api/v1/speak", json={"text": "hello world"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers["Content-Type"], "audio/wav")
        body = await resp.read()
        self.assertTrue(body.startswith(b"RIFF"))
        with wave.open(io.BytesIO(body), "rb") as wav_file:
            self.assertGreater(wav_file.getnframes(), 0)
            self.assertEqual(wav_file.getnchannels(), 1)
        tts = self.app[APP_RUNTIME_KEY].tts
        self.assertIn("hello world", tts.spoken)

    async def test_speak_pcm_format(self) -> None:
        resp = await self.client.post("/api/v1/speak?format=pcm", json={"text": "hi"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers["Content-Type"], "audio/L16")
        self.assertIn("rate=", resp.headers.get("X-Sample-Rate", "rate=") or "")
        body = await resp.read()
        self.assertEqual(len(body) % 2, 0)
        self.assertGreater(len(body), 0)

    async def test_speak_missing_text_is_400(self) -> None:
        resp = await self.client.post("/api/v1/speak", json={})
        self.assertEqual(resp.status, 400)

    async def test_speak_voice_id_is_forwarded(self) -> None:
        resp = await self.client.post(
            "/api/v1/speak", json={"text": "مرحبا", "voice_id": "ar_JO-kareem-medium"}
        )
        self.assertEqual(resp.status, 200)
        tts = self.app[APP_RUNTIME_KEY].tts
        self.assertIn("ar_JO-kareem-medium", tts.requested_voice_ids)


class TranscribeEndpointTests(VoiceAPITestBase):
    async def test_transcribe_wav_body(self) -> None:
        audio = _wav_bytes([10, -10] * 800)
        resp = await self.client.post(
            "/api/v1/transcribe", data=audio, headers={"Content-Type": "audio/wav"}
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        # FakeSTT echoes "<len>@<rate>"
        self.assertEqual(body["text"], "1600@16000")
        self.assertEqual(body["language"], "en")

    async def test_transcribe_raw_pcm_body(self) -> None:
        pcm = (b"\x10\x00" * 320)
        resp = await self.client.post(
            "/api/v1/transcribe?sample_rate=16000",
            data=pcm,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["text"], "320@16000")

    async def test_transcribe_empty_body_is_400(self) -> None:
        resp = await self.client.post(
            "/api/v1/transcribe", data=b"", headers={"Content-Type": "audio/wav"}
        )
        self.assertEqual(resp.status, 400)


class ConverseEndpointTests(VoiceAPITestBase):
    async def test_converse_streams_sse_events_to_final_text(self) -> None:
        resp = await self.client.post("/api/v1/converse", json={"text": "hello"})
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
        raw = (await resp.read()).decode("utf-8")
        events = [json.loads(line[len("data: "):]) for line in raw.splitlines() if line.startswith("data: ")]
        types = [e["type"] for e in events]
        self.assertIn("assistant_text_final", types)
        final = next(e for e in events if e["type"] == "assistant_text_final")
        self.assertTrue(final["text"])

    async def test_converse_session_id_reuses_adapter_session(self) -> None:
        first = await self.client.post("/api/v1/converse", json={"text": "one", "session_id": "client-a"})
        await first.read()
        second = await self.client.post("/api/v1/converse", json={"text": "two", "session_id": "client-a"})
        await second.read()
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)

    async def test_converse_missing_text_is_400(self) -> None:
        resp = await self.client.post("/api/v1/converse", json={})
        self.assertEqual(resp.status, 400)


class ErrorEnvelopeTests(VoiceAPITestBase):
    async def test_error_responses_carry_ok_false(self) -> None:
        # Voice-as-API JSON errors use the same {"ok": false, "error": ...}
        # envelope as the /api/control/* surface, so a generic client can key
        # on one field to detect failure.
        resp = await self.client.post("/api/v1/speak", json={})
        self.assertEqual(resp.status, 400)
        body = await resp.json()
        self.assertFalse(body["ok"])
        self.assertIn("error", body)

    async def test_json_success_carries_ok_true(self) -> None:
        audio = _wav_bytes([10, -10] * 400)
        resp = await self.client.post("/api/v1/transcribe", data=audio, headers={"Content-Type": "audio/wav"})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertIn("text", body)


class VoiceAPIAuthTests(VoiceAPITestBase):
    auth_token = "verify-voice-api-token-0123456789"

    async def test_endpoints_require_bearer_when_token_configured(self) -> None:
        for path, kwargs in (
            ("/api/v1/speak", {"json": {"text": "x"}}),
            ("/api/v1/transcribe", {"data": b"12", "headers": {"Content-Type": "application/octet-stream"}}),
            ("/api/v1/converse", {"json": {"text": "x"}}),
        ):
            resp = await self.client.post(path, **kwargs)
            self.assertEqual(resp.status, 401, path)

    async def test_bearer_token_grants_access(self) -> None:
        resp = await self.client.post(
            "/api/v1/speak",
            json={"text": "authorized"},
            headers={"Authorization": f"Bearer {self.auth_token}"},
        )
        self.assertEqual(resp.status, 200)


class VoiceAPIAuditLogTests(VoiceAPITestBase):
    async def test_requests_emit_audit_log_line(self) -> None:
        with self.assertLogs("qantara.voice_api", level="INFO") as captured:
            await self.client.post("/api/v1/speak", json={"text": "log me"})
        self.assertTrue(any("/api/v1/speak" in line for line in captured.output))


class HangingAdapter(RuntimeAdapter):
    """Adapter whose stream never yields — simulates a wedged backend."""

    def __init__(self) -> None:
        super().__init__(AdapterConfig(kind="mock", name="hang"))
        self.cancel_called = False

    async def start_or_resume_session(self, client_context=None) -> str:
        return "hang-session"

    async def submit_user_turn(self, session_handle, transcript, turn_context=None) -> str:
        return "hang-turn"

    async def stream_assistant_output(self, session_handle, turn_handle):
        await asyncio.Event().wait()  # never completes — a wedged backend
        yield {}  # pragma: no cover - unreachable; makes this an async generator

    async def cancel_turn(self, session_handle, turn_handle, cancel_context=None) -> dict:
        self.cancel_called = True
        return {"status": "acknowledged", "turn_handle": turn_handle}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")


class _ActivityAdapter(RuntimeAdapter):
    """Emits a malformed assistant_activity to prove converse re-validates it."""

    def __init__(self) -> None:
        super().__init__(AdapterConfig(kind="mock", name="activity"))

    async def start_or_resume_session(self, client_context=None) -> str:
        return "s"

    async def submit_user_turn(self, session_handle, transcript, turn_context=None) -> str:
        return "t"

    async def stream_assistant_output(self, session_handle, turn_handle):
        yield {
            "type": "assistant_activity",
            "activity_type": "NOT_A_REAL_TYPE",  # invalid -> coerced to "other"
            "summary": "doing a thing",
            "confidence": 5.0,                    # out of range -> clamped to 1.0
            "parameters": "not-a-dict",           # invalid -> dropped
            "tool_name": "",                      # empty -> dropped
        }
        yield {"type": "assistant_text_final", "text": "done"}

    async def cancel_turn(self, session_handle, turn_handle, cancel_context=None) -> dict:
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")


class ConverseActivityValidationTests(VoiceAPITestBase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.app[APP_RUNTIME_KEY].default_binding().adapter = _ActivityAdapter()

    async def test_converse_normalizes_assistant_activity(self) -> None:
        resp = await self.client.post("/api/v1/converse", json={"text": "go"})
        raw = (await resp.read()).decode("utf-8")
        events = [json.loads(line[len("data: "):]) for line in raw.splitlines() if line.startswith("data: ")]
        activity = next(e for e in events if e["type"] == "assistant_activity")
        self.assertEqual(activity["activity_type"], "other", "invalid activity_type must be coerced")
        self.assertEqual(activity["confidence"], 1.0, "out-of-range confidence must be clamped")
        self.assertNotIn("parameters", activity, "non-dict parameters must be dropped")
        self.assertNotIn("tool_name", activity, "empty tool_name must be dropped")


class ConverseBackendSwitchTests(VoiceAPITestBase):
    async def test_converse_session_survives_backend_switch(self) -> None:
        # First turn creates and caches an adapter session handle.
        first = await self.client.post("/api/v1/converse", json={"text": "one", "session_id": "sw"})
        await first.read()
        self.assertEqual(first.status, 200)

        # Simulate /api/configure swapping the backend: a brand-new adapter
        # instance that has never seen the cached handle.
        from adapters.mock_adapter import MockAdapter
        self.app[APP_RUNTIME_KEY].default_binding().adapter = MockAdapter()

        # Reusing the same session_id must transparently start a fresh session
        # and still stream a normal response — not an opaque turn_failed.
        second = await self.client.post("/api/v1/converse", json={"text": "two", "session_id": "sw"})
        raw = (await second.read()).decode("utf-8")
        events = [json.loads(line[len("data: "):]) for line in raw.splitlines() if line.startswith("data: ")]
        types = [e["type"] for e in events]
        self.assertIn("assistant_text_final", types, "reused session after a backend switch must still respond")
        self.assertNotIn("turn_failed", types, "backend switch must not surface an opaque turn_failed")


class ConverseTimeoutTests(VoiceAPITestBase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.hanging = HangingAdapter()
        self.app[APP_RUNTIME_KEY].default_binding().adapter = self.hanging

    async def test_converse_times_out_and_cancels_wedged_backend(self) -> None:
        # The deadline must fire even though the adapter yields nothing, and the
        # backend turn must be cancelled rather than abandoned.
        import gateway.transport_spike.voice_api as voice_api

        original = voice_api.CONVERSE_TURN_TIMEOUT_SECONDS
        voice_api.CONVERSE_TURN_TIMEOUT_SECONDS = 0.2
        try:
            resp = await self.client.post("/api/v1/converse", json={"text": "hello"})
            raw = await asyncio.wait_for(resp.read(), timeout=5.0)
        finally:
            voice_api.CONVERSE_TURN_TIMEOUT_SECONDS = original
        self.assertEqual(resp.status, 200)
        self.assertIn("turn timed out", raw.decode("utf-8"))
        self.assertTrue(self.hanging.cancel_called, "wedged turn should be cancelled on timeout")


if __name__ == "__main__":
    unittest.main()
