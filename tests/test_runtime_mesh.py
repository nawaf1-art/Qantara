from __future__ import annotations

import os
import unittest
import unittest.mock

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS

# Start every test from a mesh-free environment so a developer's shell
# settings cannot leak in.
_BASE_ENV = {k: v for k, v in os.environ.items() if not k.startswith("QANTARA_MESH_")}


def _runtime() -> GatewayRuntime:
    return GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
    )


class GatewayRuntimeMeshLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_mesh_disabled_by_default(self) -> None:
        runtime = _runtime()
        with unittest.mock.patch.dict(os.environ, _BASE_ENV, clear=True):
            await runtime.start_mesh()
        self.assertIsNone(runtime.mesh_controller)
        await runtime.close()

    async def test_mesh_starts_when_role_is_set(self) -> None:
        # Port 0 and the loopback default: no fixed port, and no mDNS.
        env = {**_BASE_ENV, "QANTARA_MESH_ROLE": "full", "QANTARA_MESH_PORT": "0"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            runtime = _runtime()
            await runtime.start_mesh()
            try:
                self.assertIsNotNone(runtime.mesh_controller)
                self.assertEqual(runtime.mesh_controller.config.role, "full")
                self.assertEqual(runtime.mesh_controller.config.mesh_port, 0)
                self.assertEqual(runtime.mesh_controller.config.mesh_host, "127.0.0.1")
                self.assertFalse(runtime.mesh_controller.mdns_enabled)
            finally:
                await runtime.close()

    async def test_mesh_host_must_be_explicit_for_lan(self) -> None:
        from gateway.mesh import controller as controller_mod

        env = {
            **_BASE_ENV,
            "QANTARA_MESH_ROLE": "full",
            "QANTARA_MESH_HOST": "0.0.0.0",
            "QANTARA_MESH_PORT": "19912",
            "QANTARA_MESH_TOKEN": "a-shared-mesh-token-of-24+chars",
        }
        fake = unittest.mock.MagicMock()
        fake.start = unittest.mock.AsyncMock()
        fake.stop = unittest.mock.AsyncMock()
        # The controller is mocked: this test must not bind a LAN socket.
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(controller_mod, "MeshController", return_value=fake) as ctor:
            runtime = _runtime()
            await runtime.start_mesh()
            try:
                cfg = ctor.call_args.args[0]
                self.assertEqual(cfg.mesh_host, "0.0.0.0")
                self.assertEqual(cfg.mesh_port, 19912)
            finally:
                await runtime.close()

    async def test_mesh_token_env_reaches_controller_config(self) -> None:
        env = {
            **_BASE_ENV,
            "QANTARA_MESH_ROLE": "full",
            "QANTARA_MESH_PORT": "0",
            "QANTARA_MESH_TOKEN": "sekrit-mesh-token-0123456789",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            runtime = _runtime()
            await runtime.start_mesh()
            try:
                self.assertIsNotNone(runtime.mesh_controller)
                self.assertEqual(runtime.mesh_controller.config.mesh_token, "sekrit-mesh-token-0123456789")
            finally:
                await runtime.close()

    async def test_mesh_disabled_role_noop(self) -> None:
        env = {**_BASE_ENV, "QANTARA_MESH_ROLE": "disabled"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            runtime = _runtime()
            await runtime.start_mesh()
            self.assertIsNone(runtime.mesh_controller)
            await runtime.close()


if __name__ == "__main__":
    unittest.main()
