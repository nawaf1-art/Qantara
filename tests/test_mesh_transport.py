from __future__ import annotations

import asyncio
import unittest

from gateway.mesh.protocol import Hello, RmsUpdate
from gateway.mesh.transport import MeshPeer, MeshServer


class MeshTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_receives_hello_and_rms_update_from_client(self) -> None:
        received: list = []

        async def on_message(msg, addr) -> None:
            received.append(msg)

        server = MeshServer(host="127.0.0.1", port=0, on_message=on_message)
        await server.start()
        try:
            addr = server.sockets[0].getsockname()
            peer = MeshPeer(host=addr[0], port=addr[1])
            await peer.connect()
            await peer.send(Hello(node_id="client", role="full"))
            await peer.send(RmsUpdate(node_id="client", rms=0.5, session_id="s1", monotonic_ms=1234.0))
            await asyncio.sleep(0.05)  # let the server drain
            await peer.close()
        finally:
            await server.stop()

        self.assertEqual(len(received), 2)
        self.assertIsInstance(received[0], Hello)
        self.assertIsInstance(received[1], RmsUpdate)
        self.assertAlmostEqual(received[1].rms, 0.5)

    async def test_malformed_frame_is_dropped_not_fatal(self) -> None:
        """A bad JSON line from a buggy peer must not kill the server."""
        received: list = []

        async def on_message(msg, addr) -> None:
            received.append(msg)

        server = MeshServer(host="127.0.0.1", port=0, on_message=on_message)
        await server.start()
        try:
            addr = server.sockets[0].getsockname()
            reader, writer = await asyncio.open_connection(addr[0], addr[1])
            writer.write(b"not valid json\n")
            writer.write(b'{"type":"hello","node_id":"x","role":"full"}\n')
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

        # The bad frame is dropped; the good one arrives.
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].node_id, "x")


class MeshServerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_completes_while_peer_connection_is_open(self) -> None:
        """Found during real-network verification: asyncio's wait_closed()
        waits for connection handlers to finish, and the handler blocks in
        readline() until the peer hangs up — so stop() hung forever while
        any peer was still connected. The server must close its connections
        on stop."""
        async def on_message(msg, addr) -> None:
            pass

        server = MeshServer(host="127.0.0.1", port=0, on_message=on_message)
        await server.start()
        addr = server.sockets[0].getsockname()
        reader, writer = await asyncio.open_connection(addr[0], addr[1])
        try:
            await asyncio.wait_for(server.stop(), timeout=2.0)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


class MeshAuthTests(unittest.IsolatedAsyncioTestCase):
    """QANTARA_MESH_TOKEN shared-secret frame authentication. When a token
    is configured, every frame carries an HMAC-SHA256 signature; the server
    drops frames that are unsigned or signed with the wrong token."""

    async def _run_server(self, token: str | None):
        received: list = []

        async def on_message(msg, addr) -> None:
            received.append(msg)

        server = MeshServer(host="127.0.0.1", port=0, on_message=on_message, token=token)
        await server.start()
        return server, received

    async def test_signed_frames_accepted_with_matching_token(self) -> None:
        server, received = await self._run_server(token="sekrit-mesh-token")
        try:
            addr = server.sockets[0].getsockname()
            peer = MeshPeer(host=addr[0], port=addr[1], token="sekrit-mesh-token")
            await peer.connect()
            await peer.send(Hello(node_id="client", role="full"))
            await peer.send(RmsUpdate(node_id="client", rms=0.5, session_id="s1", monotonic_ms=1234.0))
            await asyncio.sleep(0.05)
            await peer.close()
        finally:
            await server.stop()
        self.assertEqual(len(received), 2)
        self.assertIsInstance(received[0], Hello)

    async def test_unsigned_frames_dropped_when_token_configured(self) -> None:
        server, received = await self._run_server(token="sekrit-mesh-token")
        try:
            addr = server.sockets[0].getsockname()
            peer = MeshPeer(host=addr[0], port=addr[1])  # no token: unsigned
            await peer.connect()
            await peer.send(Hello(node_id="intruder", role="full"))
            await asyncio.sleep(0.05)
            await peer.close()
        finally:
            await server.stop()
        self.assertEqual(received, [])

    async def test_frames_with_wrong_token_dropped(self) -> None:
        server, received = await self._run_server(token="sekrit-mesh-token")
        try:
            addr = server.sockets[0].getsockname()
            peer = MeshPeer(host=addr[0], port=addr[1], token="wrong-token")
            await peer.connect()
            await peer.send(Hello(node_id="intruder", role="full"))
            await asyncio.sleep(0.05)
            await peer.close()
        finally:
            await server.stop()
        self.assertEqual(received, [])

    async def test_tampered_signed_frame_dropped(self) -> None:
        import json

        from gateway.mesh.protocol import sign_frame

        server, received = await self._run_server(token="sekrit-mesh-token")
        try:
            addr = server.sockets[0].getsockname()
            reader, writer = await asyncio.open_connection(addr[0], addr[1])
            frame = sign_frame(
                {"type": "rms_update", "node_id": "client", "rms": 0.1, "session_id": "s1", "monotonic_ms": 1.0},
                "sekrit-mesh-token",
            )
            frame["rms"] = 999.0  # tamper after signing
            writer.write((json.dumps(frame) + "\n").encode("utf-8"))
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
        self.assertEqual(received, [])

    async def test_no_token_keeps_legacy_plaintext_behavior(self) -> None:
        server, received = await self._run_server(token=None)
        try:
            addr = server.sockets[0].getsockname()
            peer = MeshPeer(host=addr[0], port=addr[1])
            await peer.connect()
            await peer.send(Hello(node_id="client", role="full"))
            await asyncio.sleep(0.05)
            await peer.close()
        finally:
            await server.stop()
        self.assertEqual(len(received), 1)


class MeshControllerTokenWiringTests(unittest.IsolatedAsyncioTestCase):
    """The controller must pass the configured mesh token down to both the
    inbound server and outbound peer connections."""

    async def _start_token_server(self, token: str | None):
        received: list = []

        async def on_message(msg, addr) -> None:
            received.append(msg)

        server = MeshServer(host="127.0.0.1", port=0, on_message=on_message, token=token)
        await server.start()
        return server, received

    async def test_outbound_hello_is_signed_with_configured_token(self) -> None:
        from gateway.mesh.controller import MeshController, MeshControllerConfig
        from gateway.mesh.peer_registry import PeerRecord

        server, received = await self._start_token_server(token="tok")
        try:
            addr = server.sockets[0].getsockname()
            controller = MeshController(MeshControllerConfig(
                node_id="node-a", role="full", mesh_port=19999, mesh_token="tok",
            ))
            record = PeerRecord(node_id="node-b", role="full", host=addr[0], port=addr[1])
            peer = await controller._ensure_connection(record)
            self.assertIsNotNone(peer)
            await asyncio.sleep(0.05)
            await controller._drop_peer("node-b")
        finally:
            await server.stop()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].node_id, "node-a")

    async def test_outbound_hello_with_missing_token_is_dropped_by_token_server(self) -> None:
        from gateway.mesh.controller import MeshController, MeshControllerConfig
        from gateway.mesh.peer_registry import PeerRecord

        server, received = await self._start_token_server(token="tok")
        try:
            addr = server.sockets[0].getsockname()
            controller = MeshController(MeshControllerConfig(
                node_id="node-a", role="full", mesh_port=19998,
            ))
            record = PeerRecord(node_id="node-b", role="full", host=addr[0], port=addr[1])
            await controller._ensure_connection(record)
            await asyncio.sleep(0.05)
            await controller._drop_peer("node-b")
        finally:
            await server.stop()
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
