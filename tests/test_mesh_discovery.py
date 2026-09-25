from __future__ import annotations

import socket
import unittest
import unittest.mock

from gateway.mesh import discovery
from gateway.mesh.discovery import MeshAdvertiser, MeshBrowser

SERVICE_TYPE = "_qantest._tcp.local."


def _fake_zeroconf() -> unittest.mock.MagicMock:
    aiozc = unittest.mock.MagicMock()
    aiozc.async_register_service = unittest.mock.AsyncMock()
    aiozc.async_unregister_service = unittest.mock.AsyncMock()
    aiozc.async_close = unittest.mock.AsyncMock()
    return aiozc


class MeshDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    """Hermetic: zeroconf is mocked, so nothing is multicast on the LAN."""

    async def test_advertise_and_browse_round_trip(self) -> None:
        node_id = "node-advertise-test"
        aiozc = _fake_zeroconf()
        with unittest.mock.patch.object(discovery, "AsyncZeroconf", return_value=aiozc):
            adv = MeshAdvertiser(
                service_type=SERVICE_TYPE,
                node_id=node_id,
                role="full",
                port=19900,
                capabilities={"stt": True, "tts": True},
                host_ip="192.168.50.5",
            )
            await adv.start()
            await adv.stop()
        aiozc.async_register_service.assert_awaited_once()
        info = aiozc.async_register_service.await_args.args[0]
        self.assertEqual(info.port, 19900)
        self.assertEqual(info.addresses, [socket.inet_aton("192.168.50.5")])
        aiozc.async_unregister_service.assert_awaited_once()

        # Feed the advertised record to a browser as zeroconf would.
        class ResolvedInfo:
            def __init__(self, *_args, **_kwargs) -> None:
                self.properties = info.properties
                self.port = info.port

            async def async_request(self, *_args, **_kwargs) -> bool:
                return True

            def parsed_addresses(self) -> list[str]:
                return ["192.168.50.5"]

        seen: list[dict] = []
        removed: list[str] = []

        async def on_peer(record: dict) -> None:
            seen.append(record)

        async def on_removed(peer_node_id: str) -> None:
            removed.append(peer_node_id)

        browser = MeshBrowser(
            service_type=SERVICE_TYPE,
            local_node_id="observer",
            on_peer_added=on_peer,
            on_peer_removed=on_removed,
        )
        browser._aiozc = unittest.mock.MagicMock()
        name = f"{node_id}.{SERVICE_TYPE}"
        with unittest.mock.patch.object(discovery, "AsyncServiceInfo", ResolvedInfo):
            await browser._handle_change(SERVICE_TYPE, name, discovery.ServiceStateChange.Added)
            await browser._handle_change(SERVICE_TYPE, name, discovery.ServiceStateChange.Removed)

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["node_id"], node_id)
        self.assertEqual(seen[0]["role"], "full")
        self.assertEqual(seen[0]["port"], 19900)
        self.assertEqual(seen[0]["host"], "192.168.50.5")
        self.assertEqual(removed, [node_id])

    async def test_browser_ignores_its_own_advertisement(self) -> None:
        class OwnInfo:
            def __init__(self, *_args, **_kwargs) -> None:
                self.properties = {b"node_id": b"me", b"role": b"full"}
                self.port = 8901

            async def async_request(self, *_args, **_kwargs) -> bool:
                return True

            def parsed_addresses(self) -> list[str]:
                return ["192.168.50.5"]

        seen: list[dict] = []

        async def on_peer(record: dict) -> None:
            seen.append(record)

        async def on_removed(_node_id: str) -> None:
            return None

        browser = MeshBrowser(SERVICE_TYPE, "me", on_peer, on_removed)
        browser._aiozc = unittest.mock.MagicMock()
        with unittest.mock.patch.object(discovery, "AsyncServiceInfo", OwnInfo):
            await browser._handle_change(SERVICE_TYPE, f"me.{SERVICE_TYPE}", discovery.ServiceStateChange.Added)
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
