from __future__ import annotations

import unittest

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from adapters.base import AdapterConfig
from gateway.transport_spike.http_api import APP_RUNTIME_KEY, mount_static_routes
from gateway.transport_spike.languages_catalog import build_language_catalog
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

    async def test_language_catalog_uses_matching_voice_locale(self) -> None:
        class KokoroEnglishOnly:
            available = True

            def list_available_voices(self) -> list[dict]:
                return [
                    {"voice_id": "af_heart", "label": "Heart", "locale": "en-US"},
                    {"voice_id": "am_adam", "label": "Adam", "locale": "en-US"},
                ]

        catalog = build_language_catalog(KokoroEnglishOnly())
        by_iso = {entry["iso"]: entry for entry in catalog}

        self.assertTrue(by_iso["en"]["tts_available"])
        self.assertEqual(by_iso["en"]["tts_voice_id"], "af_heart")
        self.assertFalse(by_iso["ja"]["tts_available"])
        self.assertIsNone(by_iso["ja"]["tts_voice_id"])


if __name__ == "__main__":
    unittest.main()
