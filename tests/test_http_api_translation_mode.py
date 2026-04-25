from __future__ import annotations

import json
import unittest

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from adapters.base import AdapterConfig
from gateway.transport_spike.auth import AUTH_TOKEN_KEY
from gateway.transport_spike.http_api import APP_RUNTIME_KEY, mount_static_routes
from gateway.transport_spike.runtime import GatewayRuntime, Session
from tests.test_transport_spike import DummyWebSocket, FakeSTT, FakeTTS


class TranslationModeApiTests(AioHTTPTestCase):
    runtime: GatewayRuntime

    async def get_application(self) -> web.Application:
        app = web.Application()
        self.runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda _r: None,
        )
        app[APP_RUNTIME_KEY] = self.runtime
        mount_static_routes(app)
        return app

    def _register_session(self, cid: str) -> None:
        session = Session(DummyWebSocket(), self.runtime)
        session.client_session_id = cid
        self.runtime.register_session(session)

    async def _start_authed_client(self, token: str) -> tuple[TestClient, GatewayRuntime]:
        app = web.Application()
        runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda _r: None,
        )
        app[APP_RUNTIME_KEY] = runtime
        app[AUTH_TOKEN_KEY] = token
        mount_static_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        return client, runtime

    async def test_assistant_mode_sets_state(self) -> None:
        self._register_session("c1")
        resp = await self.client.post(
            "/api/translation_mode",
            data=json.dumps({"client_session_id": "c1", "mode": "assistant"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["mode"], "assistant")

    async def test_directional_requires_pair(self) -> None:
        self._register_session("c2")
        resp = await self.client.post(
            "/api/translation_mode",
            data=json.dumps({"client_session_id": "c2", "mode": "directional"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    async def test_live_with_pair_persists_snapshot(self) -> None:
        self._register_session("c3")
        resp = await self.client.post(
            "/api/translation_mode",
            data=json.dumps({
                "client_session_id": "c3",
                "mode": "live",
                "source": "en",
                "target": "ja",
            }),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["mode"], "live")
        self.assertEqual(body["source"], "en")
        self.assertEqual(body["target"], "ja")
        snapshot = self.runtime.snapshot_for("c3")
        self.assertEqual(snapshot.translation_mode, "live")
        self.assertEqual(snapshot.translation_source, "en")
        self.assertEqual(snapshot.translation_target, "ja")

    async def test_rejects_unknown_language(self) -> None:
        self._register_session("c4")
        resp = await self.client.post(
            "/api/translation_mode",
            data=json.dumps({
                "client_session_id": "c4",
                "mode": "directional",
                "source": "en",
                "target": "xx",
            }),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    async def test_rejects_unknown_session(self) -> None:
        resp = await self.client.post(
            "/api/translation_mode",
            data=json.dumps({"client_session_id": "ghost", "mode": "assistant"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 404)

    async def test_requires_auth_token_when_configured(self) -> None:
        client, runtime = await self._start_authed_client("voice-secret-token-123456")
        try:
            session = Session(DummyWebSocket(), runtime)
            session.client_session_id = "c5"
            runtime.register_session(session)

            missing = await client.post(
                "/api/translation_mode",
                data=json.dumps({"client_session_id": "c5", "mode": "assistant"}),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(missing.status, 401)

            ok = await client.post(
                "/api/translation_mode",
                data=json.dumps({"client_session_id": "c5", "mode": "assistant"}),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer voice-secret-token-123456",
                },
            )
            self.assertEqual(ok.status, 200)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
