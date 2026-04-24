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


if __name__ == "__main__":
    unittest.main()
