from __future__ import annotations

import os
import unittest
import unittest.mock

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS


class GatewayRuntimeMeshLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_mesh_disabled_by_default(self) -> None:
        runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
        )
        self.assertIsNone(runtime.mesh_controller)

    async def test_mesh_starts_when_role_is_set(self) -> None:
        env = {"QANTARA_MESH_ROLE": "full", "QANTARA_MESH_PORT": "19911"}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            runtime = GatewayRuntime(
                adapter_config=AdapterConfig(kind="mock", name="mock"),
                stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
            )
            await runtime.start_mesh()
            try:
                self.assertIsNotNone(runtime.mesh_controller)
                self.assertEqual(runtime.mesh_controller.config.role, "full")
                self.assertEqual(runtime.mesh_controller.config.mesh_port, 19911)
                self.assertEqual(runtime.mesh_controller.config.mesh_host, "127.0.0.1")
            finally:
                await runtime.close()

    async def test_mesh_host_must_be_explicit_for_lan(self) -> None:
        env = {
            "QANTARA_MESH_ROLE": "full",
            "QANTARA_MESH_HOST": "0.0.0.0",
            "QANTARA_MESH_PORT": "19912",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            runtime = GatewayRuntime(
                adapter_config=AdapterConfig(kind="mock", name="mock"),
                stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
            )
            await runtime.start_mesh()
            try:
                self.assertIsNotNone(runtime.mesh_controller)
                self.assertEqual(runtime.mesh_controller.config.mesh_host, "0.0.0.0")
            finally:
                await runtime.close()

    async def test_mesh_disabled_role_noop(self) -> None:
        env = {"QANTARA_MESH_ROLE": "disabled"}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            runtime = GatewayRuntime(
                adapter_config=AdapterConfig(kind="mock", name="mock"),
                stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
            )
            await runtime.start_mesh()
            self.assertIsNone(runtime.mesh_controller)
            await runtime.close()


if __name__ == "__main__":
    unittest.main()
