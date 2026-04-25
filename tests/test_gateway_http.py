from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
from protocol_fixtures import (
    assert_playback_cleared_payload,
    assert_session_ready_payload,
    assert_tts_status_payload,
)

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter
from gateway.transport_spike.runtime import GatewayRuntime
from gateway.transport_spike.server import create_app
from providers.stt.base import STTProvider
from providers.tts.base import TTSProvider, VoiceSpec


class FakeSTT(STTProvider):
    kind = "fake_stt"

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, samples: list[int], sample_rate: int) -> str:
        return "transcribed"


class FakeTTS(TTSProvider):
    kind = "fake_tts"

    @property
    def available(self) -> bool:
        return True

    @property
    def default_voice_id(self) -> str | None:
        return "fake_voice"

    def list_available_voices(self) -> list[dict]:
        return [
            {
                "voice_id": "fake_voice",
                "label": "Fake Voice",
                "locale": "en-US",
                "sample_rate": 16000,
                "defaults": {"rate": 1.0, "pitch": 0, "tone": "neutral"},
                "allowed_transforms": ["rate", "tone"],
            }
        ]

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        return (
            VoiceSpec(
                voice_id=voice_id or "fake_voice",
                label="Fake Voice",
                sample_rate=16000,
                locale="en-US",
                defaults={"rate": 1.0, "pitch": 0, "tone": "neutral"},
                allowed_transforms=["rate", "tone"],
            ),
            None,
        )

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
        *,
        expressiveness: float | None = None,  # noqa: ARG002
    ) -> tuple[list[int], VoiceSpec, str | None]:
        voice, _ = self.resolve_voice(voice_id)
        return [], voice, None


class DeltaOnlyAdapter(RuntimeAdapter):
    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        return "runtime-session"

    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        return "turn-1"

    async def stream_assistant_output(self, session_handle: str, turn_handle: str):
        yield {"type": "assistant_text_delta", "text": "hello from ws"}
        yield {"type": "turn_completed"}

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, str]:
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")


class GatewayHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {"QANTARA_AUTH_TOKEN": "", "QANTARA_ADMIN_TOKEN": ""},
        )
        self.env_patch.start()
        await self._start_client()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.env_patch.stop()

    async def _start_client(self) -> None:
        self.runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda record: None,
        )
        self.runtime.default_binding().adapter = DeltaOnlyAdapter(
            AdapterConfig(kind="mock", name="mock")
        )
        self.server = TestServer(create_app(self.runtime))
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def _restart_client(self, env: dict[str, str]) -> None:
        await self.client.close()
        self.env_patch.stop()
        merged_env = {
            "QANTARA_AUTH_TOKEN": "",
            "QANTARA_ADMIN_TOKEN": "",
            **env,
        }
        self.env_patch = patch.dict(os.environ, merged_env)
        self.env_patch.start()
        await self._start_client()

    async def test_status_endpoint_exposes_runtime_state(self) -> None:
        resp = await self.client.get("/api/status")
        body = await resp.json()
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["type"], "mock")
        self.assertEqual(body["adapter_kind"], "mock")

    async def test_admin_runtime_endpoint_exposes_bindings_and_sessions(self) -> None:
        await self._restart_client({"QANTARA_ADMIN_TOKEN": "admin-secret-token-123456"})
        ws = await self.client.ws_connect("/ws")
        await ws.send_json(
            {
                "type": "session_init",
                "client_name": "admin-test-client",
                "client_session_id": "admin-client",
                "voice_id": "fake_voice",
                "voice_tone": "warm",
            }
        )
        await ws.receive_json()
        await ws.receive_json()

        resp = await self.client.get(
            "/api/admin/runtime",
            headers={"Authorization": "Bearer admin-secret-token-123456"},
        )
        body = await resp.json()
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["default_binding_id"], self.runtime.default_binding_id)
        self.assertEqual(len(body["bindings"]), 1)
        self.assertEqual(body["bindings"][0]["reference_count"], 1)
        self.assertEqual(body["active_sessions"][0]["binding_id"], self.runtime.default_binding_id)
        self.assertEqual(body["stored_sessions"][0]["client_session_id"], "admin-client")
        self.assertEqual(body["stored_sessions"][0]["voice_tone"], "warm")
        await ws.close()

    async def test_admin_runtime_endpoint_requires_admin_token(self) -> None:
        resp = await self.client.get("/api/admin/runtime")
        self.assertEqual(resp.status, 404)

        await self._restart_client({"QANTARA_ADMIN_TOKEN": "admin-secret-token-123456"})
        wrong = await self.client.get(
            "/api/admin/runtime",
            headers={"Authorization": "Bearer wrong"},
        )
        self.assertEqual(wrong.status, 401)

    async def test_configure_rejects_public_url(self) -> None:
        with patch("gateway.transport_spike.http_api.unload_previous_model", new_callable=AsyncMock) as unload:
            resp = await self.client.post(
                "/api/configure",
                json={"type": "custom", "url": "https://example.com"},
            )
        body = await resp.json()
        self.assertEqual(resp.status, 403)
        self.assertEqual(body["error"], "Only private network URLs are allowed")
        unload.assert_not_awaited()

    async def test_configure_rejects_invalid_json_before_unload(self) -> None:
        with patch("gateway.transport_spike.http_api.unload_previous_model", new_callable=AsyncMock) as unload:
            resp = await self.client.post(
                "/api/configure",
                data="not-json",
                headers={"Content-Type": "application/json"},
            )
        body = await resp.json()
        self.assertEqual(resp.status, 400)
        self.assertEqual(body["error"], "invalid JSON body")
        unload.assert_not_awaited()

    async def test_configure_endpoint_auth_token_behavior(self) -> None:
        allowed = await self.client.post(
            "/api/configure",
            json={"type": "custom", "url": "http://127.0.0.1:1"},
        )
        self.assertEqual(allowed.status, 200)

        await self._restart_client({"QANTARA_AUTH_TOKEN": "voice-secret-token-123456"})
        missing = await self.client.post(
            "/api/configure",
            json={"type": "custom", "url": "http://127.0.0.1:1"},
        )
        self.assertEqual(missing.status, 401)

        wrong = await self.client.post(
            "/api/configure",
            json={"type": "custom", "url": "http://127.0.0.1:1"},
            headers={"Authorization": "Bearer wrong"},
        )
        self.assertEqual(wrong.status, 401)

        correct = await self.client.post(
            "/api/configure",
            json={"type": "custom", "url": "http://127.0.0.1:1"},
            headers={"Authorization": "Bearer voice-secret-token-123456"},
        )
        self.assertEqual(correct.status, 200)

    async def test_browser_auth_cookie_unlocks_api_and_websocket(self) -> None:
        await self._restart_client({"QANTARA_AUTH_TOKEN": "voice-secret-token-123456"})

        status = await self.client.get("/api/auth/status")
        status_body = await status.json()
        self.assertEqual(status.status, 200)
        self.assertTrue(status_body["required"])
        self.assertFalse(status_body["authenticated"])

        wrong = await self.client.post("/api/auth/login", json={"token": "wrong"})
        self.assertEqual(wrong.status, 401)

        login = await self.client.post(
            "/api/auth/login",
            json={"token": "voice-secret-token-123456"},
        )
        self.assertEqual(login.status, 200)

        authed_status = await self.client.get("/api/auth/status")
        authed_body = await authed_status.json()
        self.assertTrue(authed_body["authenticated"])

        configured = await self.client.post(
            "/api/configure",
            json={"type": "custom", "url": "http://127.0.0.1:1"},
        )
        self.assertEqual(configured.status, 200)

        ws = await self.client.ws_connect("/ws")
        await ws.close()

    async def test_short_auth_token_is_rejected_at_startup(self) -> None:
        await self.client.close()
        self.env_patch.stop()
        self.env_patch = patch.dict(
            os.environ,
            {"QANTARA_AUTH_TOKEN": "too-short", "QANTARA_ADMIN_TOKEN": ""},
        )
        self.env_patch.start()
        with self.assertRaisesRegex(RuntimeError, "QANTARA_AUTH_TOKEN"):
            await self._start_client()

        self.env_patch.stop()
        self.env_patch = patch.dict(
            os.environ,
            {"QANTARA_AUTH_TOKEN": "", "QANTARA_ADMIN_TOKEN": ""},
        )
        self.env_patch.start()
        await self._start_client()

    async def test_warmup_test_url_and_discovery_require_auth_when_configured(self) -> None:
        await self._restart_client({"QANTARA_AUTH_TOKEN": "voice-secret-token-123456"})

        warmup = await self.client.post("/api/warmup")
        self.assertEqual(warmup.status, 401)

        test_url = await self.client.post("/api/test-url", json={})
        self.assertEqual(test_url.status, 401)

        discovery = await self.client.get("/api/discovery/scan")
        self.assertEqual(discovery.status, 401)

        backends = await self.client.get("/api/backends")
        self.assertEqual(backends.status, 401)

    async def test_websocket_endpoint_auth_token_behavior(self) -> None:
        ws = await self.client.ws_connect("/ws")
        await ws.close()

        await self._restart_client({"QANTARA_AUTH_TOKEN": "voice-secret-token-123456"})
        with self.assertRaises(WSServerHandshakeError) as missing_ctx:
            await self.client.ws_connect("/ws")
        self.assertEqual(missing_ctx.exception.status, 401)

        with self.assertRaises(WSServerHandshakeError) as wrong_ctx:
            await self.client.ws_connect(
                "/ws",
                headers={"Authorization": "Bearer wrong"},
            )
        self.assertEqual(wrong_ctx.exception.status, 401)

        authed = await self.client.ws_connect(
            "/ws",
            headers={"Authorization": "Bearer voice-secret-token-123456"},
        )
        await authed.close()

    async def test_websocket_session_ready_includes_voice_capabilities(self) -> None:
        ws = await self.client.ws_connect("/ws")
        await ws.send_json(
            {
                "type": "session_init",
                "client_name": "test-client",
                "client_session_id": "sticky-http-client",
                "voice_id": "fake_voice",
                "speech_rate": 1.1,
            }
        )
        ready = await ws.receive_json()
        assert_session_ready_payload(self, ready)
        self.assertEqual(ready["voice_defaults"]["rate"], 1.0)
        self.assertEqual(ready["allowed_transforms"], ["rate", "tone"])
        await ws.close()

    async def test_websocket_turn_streams_final_text(self) -> None:
        ws = await self.client.ws_connect("/ws")
        await ws.send_json(
            {
                "type": "session_init",
                "client_name": "test-client",
                "client_session_id": "delta-only-client",
                "voice_id": "fake_voice",
            }
        )
        await ws.receive_json()
        await ws.receive_json()
        await ws.send_json({"type": "submit_turn", "text": "hello"})
        seen_tts = False
        seen_final = False
        for _ in range(10):
            msg = await ws.receive_json()
            if msg.get("type") == "tts_status":
                assert_tts_status_payload(self, msg)
                seen_tts = True
            if msg.get("type") == "assistant_text_final":
                self.assertEqual(msg["text"], "hello from ws")
                seen_final = True
            if seen_tts and seen_final:
                break
        self.assertTrue(seen_tts)
        self.assertTrue(seen_final)
        await ws.close()

    async def test_playback_cleared_protocol_fixture(self) -> None:
        ws = await self.client.ws_connect("/ws")
        await ws.send_json({"type": "session_init", "client_session_id": "clear-client"})
        await ws.receive_json()
        await ws.receive_json()
        await ws.send_json({"type": "clear_playback"})
        payload = await ws.receive_json()
        assert_playback_cleared_payload(self, payload)
        await ws.close()

    async def test_full_turn_lifecycle_emits_state_active_then_idle(self) -> None:
        ws = await self.client.ws_connect("/ws")
        await ws.send_json(
            {
                "type": "session_init",
                "client_name": "lifecycle-client",
                "client_session_id": "lifecycle-session",
                "voice_id": "fake_voice",
            }
        )
        await ws.receive_json()
        await ws.receive_json()
        await ws.send_json({"type": "submit_turn", "text": "hello"})
        states: list[str] = []
        saw_final = False
        for _ in range(20):
            msg = await ws.receive_json()
            if msg.get("type") == "turn_state":
                states.append(msg.get("state", ""))
            if msg.get("type") == "assistant_text_final":
                saw_final = True
            if saw_final and "idle" in states:
                break
        self.assertIn("active", states)
        self.assertIn("idle", states)
        self.assertLess(states.index("active"), states.index("idle"))
        self.assertTrue(saw_final)
        await ws.close()

    async def test_test_url_rate_limit_returns_429_after_burst(self) -> None:
        from gateway.transport_spike import http_api

        http_api._test_url_call_log.clear()
        try:
            last_status = 200
            for _ in range(http_api._TEST_URL_RATE_LIMIT_MAX_CALLS + 2):
                resp = await self.client.post("/api/test-url", json={})
                last_status = resp.status
            self.assertEqual(last_status, 429)
        finally:
            http_api._test_url_call_log.clear()
