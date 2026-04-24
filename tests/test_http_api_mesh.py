from __future__ import annotations

import unittest

from aiohttp.test_utils import AioHTTPTestCase

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime
from gateway.transport_spike.server import create_app
from tests.test_transport_spike import FakeSTT, FakeTTS


class MeshHttpApiTests(AioHTTPTestCase):
    async def get_application(self):
        self.runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
        )
        return create_app(self.runtime)

    async def test_mesh_peers_returns_empty_when_disabled(self) -> None:
        resp = await self.client.get("/api/mesh/peers")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["enabled"], False)
        self.assertEqual(data["peers"], [])

    async def test_mesh_status_returns_shape(self) -> None:
        resp = await self.client.get("/api/mesh/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("enabled", data)
        self.assertIn("role", data)
        self.assertIn("node_id", data)


if __name__ == "__main__":
    unittest.main()
