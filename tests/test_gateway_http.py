from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import WSCloseCode, WSMsgType, WSServerHandshakeError
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


class _CountingSTT(STTProvider):
    """STT that echoes the decoded sample count, so a test can assert the
    PCM_KIND + int16-LE transport decode produced exactly the frames sent."""

    kind = "counting_stt"

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, samples: list[int], sample_rate: int) -> str:
        return str(len(samples))


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

    async def test_status_hides_backend_details_until_authenticated(self) -> None:
        await self._restart_client(
            {"QANTARA_AUTH_TOKEN": "voice-secret-token-123456"}
        )
        public = await self.client.get("/api/status")
        public_body = await public.json()
        self.assertEqual(public.status, 200)
        self.assertTrue(public_body["authentication_required"])
        self.assertNotIn("url", public_body)
        self.assertNotIn("model", public_body)

        authenticated = await self.client.get(
            "/api/status",
            headers={"Authorization": "Bearer voice-secret-token-123456"},
        )
        authenticated_body = await authenticated.json()
        self.assertEqual(authenticated.status, 200)
        self.assertEqual(authenticated_body["type"], "mock")

    async def test_login_marks_cookie_secure_behind_https_proxy(self) -> None:
        await self._restart_client(
            {"QANTARA_AUTH_TOKEN": "voice-secret-token-123456"}
        )
        response = await self.client.post(
            "/api/auth/login",
            json={"token": "voice-secret-token-123456"},
            headers={"X-Forwarded-Proto": "https"},
        )
        self.assertEqual(response.status, 200)
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Secure", cookie)

    async def test_api_responses_include_browser_security_headers(self) -> None:
        resp = await self.client.get("/api/status")
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp.headers["X-Frame-Options"], "DENY")
        self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", resp.headers["Content-Security-Policy"])

    async def test_rejects_public_host_header(self) -> None:
        resp = await self.client.get("/api/status", headers={"Host": "evil.example"})
        self.assertEqual(resp.status, 421)

    async def test_rejects_malformed_host_authority(self) -> None:
        for host in ("localhost?public.example", "localhost#public.example"):
            with self.subTest(host=host):
                resp = await self.client.get("/api/status", headers={"Host": host})
                self.assertEqual(resp.status, 421)

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

    async def test_configure_pins_resolved_ip_against_dns_rebinding(self) -> None:
        from types import SimpleNamespace

        captured: dict[str, str] = {}

        async def fake_configure(backend_type: str, *, url: str, **kwargs: object):
            captured["url"] = url
            return SimpleNamespace(
                adapter_kind="session_gateway_http",
                url=url,
                health={"status": "ok"},
                managed_bridge_type=None,
                binding_id="bid-1",
            )

        getaddr = [(2, 1, 6, "", ("192.168.1.50", 8080))]
        with patch(
            "gateway.transport_spike.http_api.unload_previous_model", new_callable=AsyncMock
        ), patch(
            "gateway.transport_spike.http_api._sock.getaddrinfo", return_value=getaddr
        ), patch.object(self.runtime, "configure_backend", side_effect=fake_configure):
            resp = await self.client.post(
                "/api/configure",
                json={"type": "custom", "url": "http://printer.local:8080"},
            )
        self.assertEqual(resp.status, 200)
        # The rebindable hostname must be pinned to the validated IP before being
        # forwarded to the backend, so a later DNS flip cannot redirect the gateway.
        self.assertTrue(
            captured["url"].startswith("http://192.168.1.50:8080"),
            f"expected pinned IP, got {captured['url']!r}",
        )

    async def test_test_url_probe_does_not_follow_redirects(self) -> None:
        from aiohttp import web as _web

        leaked = {"hit": False}

        async def models(_request: _web.Request) -> _web.Response:
            raise _web.HTTPFound("/leaked")

        async def leaked_handler(_request: _web.Request) -> _web.Response:
            leaked["hit"] = True
            return _web.json_response({"data": [{"id": "LEAKED"}]})

        malicious = _web.Application()
        malicious.router.add_get("/v1/models", models)
        malicious.router.add_get("/models", models)
        malicious.router.add_get("/leaked", leaked_handler)
        backend = TestServer(malicious)
        await backend.start_server()
        try:
            resp = await self.client.post(
                "/api/test-url", json={"url": f"http://127.0.0.1:{backend.port}"}
            )
            body = await resp.json()
        finally:
            await backend.close()
        # A redirect from the probed server must NOT be followed — otherwise the
        # IP-pinning is defeated by a 302 to a public/metadata host.
        self.assertFalse(leaked["hit"], "probe followed a redirect to a second endpoint")
        self.assertNotIn("LEAKED", body.get("models", []))

    async def test_ws_rejects_cross_origin_handshake(self) -> None:
        with self.assertRaises(WSServerHandshakeError) as ctx:
            await self.client.ws_connect("/ws", headers={"Origin": "http://evil.example"})
        self.assertEqual(ctx.exception.status, 403)

    async def test_configure_rejects_cross_origin_post(self) -> None:
        resp = await self.client.post(
            "/api/configure",
            json={"type": "mock"},
            headers={"Origin": "http://evil.example"},
        )
        self.assertEqual(resp.status, 403)

    async def test_configure_allows_same_origin_post(self) -> None:
        base = self.client.make_url("")
        origin = f"{base.scheme}://{base.host}:{base.port}"
        with patch(
            "gateway.transport_spike.http_api.unload_previous_model", new_callable=AsyncMock
        ):
            resp = await self.client.post(
                "/api/configure",
                json={"type": "mock"},
                headers={"Origin": origin},
            )
        self.assertEqual(resp.status, 200)

    async def test_configure_rejects_same_hostname_on_different_port(self) -> None:
        base = self.client.make_url("")
        origin = f"{base.scheme}://{base.host}:{base.port + 1}"
        resp = await self.client.post(
            "/api/configure",
            json={"type": "mock"},
            headers={"Origin": origin},
        )
        self.assertEqual(resp.status, 403)

    async def test_explicit_origin_allowlist_supports_cors_preflight_and_post(self) -> None:
        await self._restart_client(
            {"QANTARA_ALLOWED_ORIGINS": "https://dashboard.lan"}
        )
        preflight = await self.client.options(
            "/api/configure",
            headers={
                "Origin": "https://dashboard.lan",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(preflight.status, 204)
        self.assertEqual(
            preflight.headers["Access-Control-Allow-Origin"],
            "https://dashboard.lan",
        )

        with patch(
            "gateway.transport_spike.http_api.unload_previous_model",
            new_callable=AsyncMock,
        ):
            response = await self.client.post(
                "/api/configure",
                json={"type": "mock"},
                headers={"Origin": "https://dashboard.lan"},
            )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "https://dashboard.lan",
        )

    async def test_ws_rejects_same_hostname_on_different_port(self) -> None:
        base = self.client.make_url("")
        origin = f"{base.scheme}://{base.host}:{base.port + 1}"
        with self.assertRaises(WSServerHandshakeError) as ctx:
            await self.client.ws_connect("/ws", headers={"Origin": origin})
        self.assertEqual(ctx.exception.status, 403)

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

    async def test_state_changing_endpoints_reject_non_object_json(self) -> None:
        for path in (
            "/api/configure",
            "/api/test-url",
            "/api/test-mcp",
            "/api/translation_mode",
        ):
            with self.subTest(path=path):
                resp = await self.client.post(path, json=[])
                self.assertEqual(resp.status, 400)

    async def test_configure_rejects_missing_required_url_before_unload(self) -> None:
        with patch("gateway.transport_spike.http_api.unload_previous_model", new_callable=AsyncMock) as unload:
            resp = await self.client.post(
                "/api/configure",
                json={"type": "custom"},
            )
        body = await resp.json()
        self.assertEqual(resp.status, 400)
        self.assertEqual(body["error"], "custom type requires 'url'")
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

        non_object = await self.client.post("/api/auth/login", json=[])
        self.assertEqual(non_object.status, 400)
        non_string = await self.client.post(
            "/api/auth/login", json={"token": ["not", "a", "token"]}
        )
        self.assertEqual(non_string.status, 400)

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

    async def test_websocket_connection_count_is_bounded(self) -> None:
        self.runtime.max_websocket_connections = 1
        first = await self.client.ws_connect("/ws")
        try:
            with self.assertRaises(WSServerHandshakeError) as context:
                await self.client.ws_connect("/ws")
            self.assertEqual(context.exception.status, 503)
        finally:
            await first.close()

    async def test_websocket_rejects_non_object_control_without_disconnect(self) -> None:
        ws = await self.client.ws_connect("/ws")
        await ws.send_str("[]")
        await ws.send_json({"type": "session_init", "client_session_id": "object-check"})
        ready = await ws.receive_json()
        self.assertEqual(ready["type"], "session_ready")
        await ws.close()

    async def test_websocket_closes_oversized_audio_frame(self) -> None:
        ws = await self.client.ws_connect("/ws")
        await ws.send_bytes(bytes([0x01]) + bytes(64 * 1024 + 2))
        message = await ws.receive()
        self.assertEqual(message.type, WSMsgType.CLOSE)
        self.assertEqual(ws.close_code, WSCloseCode.MESSAGE_TOO_BIG)

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

    async def test_websocket_binary_frame_decodes_to_stt(self) -> None:
        # End-to-end binary transport: a PCM_KIND-prefixed int16-LE frame must
        # decode into recent_pcm and reach STT with the exact sample count.
        self.runtime.stt = _CountingSTT()
        ws = await self.client.ws_connect("/ws")
        await ws.send_json({"type": "session_init", "client_session_id": "bin-audio-client"})
        await ws.receive_json()
        await ws.receive_json()
        samples = [100, -100, 32767, -32768]
        frame = bytes([0x01]) + b"".join(int(s).to_bytes(2, "little", signed=True) for s in samples)
        await ws.send_bytes(frame)
        await ws.send_json({"type": "transcribe_recent_audio", "submit_turn": False})
        transcript = None
        for _ in range(12):
            msg = await ws.receive_json()
            if msg.get("type") == "transcript_result":
                transcript = msg
                break
        self.assertIsNotNone(transcript, "expected a transcript_result")
        self.assertEqual(transcript["text"], str(len(samples)),
                         "server must decode exactly the samples the client framed")
        await ws.close()

    async def test_websocket_unprefixed_binary_frame_is_rejected(self) -> None:
        # Guards the B1 contract: a frame WITHOUT the leading PCM_KIND byte (the
        # bug the /translate client had) must be rejected, never entering the PCM
        # buffer — so transcription sees no audio.
        self.runtime.stt = _CountingSTT()
        ws = await self.client.ws_connect("/ws")
        await ws.send_json({"type": "session_init", "client_session_id": "bad-bin-client"})
        await ws.receive_json()
        await ws.receive_json()
        bad_frame = bytes([0x02]) + b"".join(int(s).to_bytes(2, "little", signed=True) for s in [1, 2, 3])
        await ws.send_bytes(bad_frame)
        await ws.send_json({"type": "transcribe_recent_audio", "submit_turn": False})
        result = None
        for _ in range(12):
            msg = await ws.receive_json()
            if msg.get("type") == "transcript_result":
                result = msg
                break
        self.assertIsNotNone(result, "expected a transcript_result")
        self.assertEqual(result["text"], "", "rejected frame must not enter the PCM buffer")
        self.assertEqual(result["engine"], "none")
        await ws.close()

    async def test_websocket_odd_pcm_payload_is_rejected(self) -> None:
        self.runtime.stt = _CountingSTT()
        ws = await self.client.ws_connect("/ws")
        await ws.send_json({"type": "session_init", "client_session_id": "odd-pcm-client"})
        await ws.receive_json()
        await ws.receive_json()
        await ws.send_bytes(bytes([0x01, 0x01]))
        await ws.send_json({"type": "transcribe_recent_audio", "submit_turn": False})
        result = None
        for _ in range(12):
            msg = await ws.receive_json()
            if msg.get("type") == "transcript_result":
                result = msg
                break
        self.assertIsNotNone(result)
        self.assertEqual(result["engine"], "none")
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
