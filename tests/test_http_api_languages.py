from __future__ import annotations

import unittest

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from adapters.base import AdapterConfig
from gateway.transport_spike.http_api import APP_RUNTIME_KEY, mount_static_routes
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS


class LanguagesApiTests(AioHTTPTestCase):
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

    async def test_languages_endpoint_returns_five_launch_languages(self) -> None:
        resp = await self.client.get("/api/languages")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        iso_codes = [entry["iso"] for entry in body["languages"]]
        self.assertEqual(sorted(iso_codes), sorted(["en", "ar", "es", "fr", "ja"]))
        for entry in body["languages"]:
            self.assertIn("name", entry)
            self.assertIn("tts_voice_id", entry)
            self.assertIn("tts_available", entry)


if __name__ == "__main__":
    unittest.main()
