from __future__ import annotations

import unittest

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from adapters.base import AdapterConfig
from gateway.transport_spike.http_api import APP_RUNTIME_KEY, mount_static_routes
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS


class TranslatePageSmokeTests(AioHTTPTestCase):
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

    async def test_translate_route_redirects_to_index(self) -> None:
        resp = await self.client.get("/translate", allow_redirects=False)
        self.assertIn(resp.status, (302, 301))

    async def test_translate_index_html_served(self) -> None:
        resp = await self.client.get("/translate/index.html")
        self.assertEqual(resp.status, 200)
        body = await resp.text()
        self.assertIn("talk-btn", body)
        self.assertIn("Live Translator", body)

    async def test_translate_page_releases_audio_resources(self) -> None:
        """Regression guard for the audit finding: the translate client must
        fully release mic resources (tracks, source node, AudioContext) and
        hook page teardown, not just disconnect the script processor."""
        resp = await self.client.get("/translate/index.html")
        body = await resp.text()
        self.assertIn("releaseAudioResources", body)
        self.assertIn("pagehide", body)
        self.assertIn("getTracks().forEach", body)

    async def test_voice_page_releases_playback_context(self) -> None:
        """The voice client closes mic resources in stopMic but must also
        release the playback AudioContext on page teardown."""
        resp = await self.client.get("/spike/index.html")
        body = await resp.text()
        self.assertIn("releasePlaybackContext", body)
        self.assertIn("pagehide", body)


if __name__ == "__main__":
    unittest.main()
