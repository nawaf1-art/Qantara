from __future__ import annotations

import unittest

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from adapters.base import AdapterConfig
from gateway.transport_spike.http_api import APP_RUNTIME_KEY, mount_static_routes
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS


class TTSApiTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        app = web.Application()
        app[APP_RUNTIME_KEY] = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda _r: None,
        )
        mount_static_routes(app)
        return app

    async def test_get_api_tts_returns_current_and_engines(self) -> None:
        resp = await self.client.get("/api/tts")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("current", body)
        self.assertIn("engines", body)
        self.assertIn("chatterbox", body["engines"])
        self.assertIn("piper", body["engines"])
        self.assertIn("kokoro", body["engines"])


if __name__ == "__main__":
    unittest.main()
