from __future__ import annotations

import asyncio
import unittest

from gateway.mesh.controller import MeshController, MeshControllerConfig


def _announce(to: MeshController, peer: MeshController) -> dict:
    """The record the mDNS browser would hand to ``to`` after resolving
    ``peer``. Real mDNS is not used: tests must not multicast on the LAN,
    and loopback-bound controllers do not start discovery at all."""
    return {
        "node_id": peer.config.node_id,
        "role": peer.config.role,
        "host": "127.0.0.1",
        "port": peer.listening_port,
    }


class MeshIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def _pair(self) -> tuple[MeshController, MeshController]:
        a = MeshController(MeshControllerConfig(
            node_id="node-a", role="full", mesh_port=0, capabilities={"stt": True},
        ))
        b = MeshController(MeshControllerConfig(
            node_id="node-b", role="full", mesh_port=0, capabilities={"stt": True},
        ))
        await a.start()
        self.addAsyncCleanup(a.stop)
        await b.start()
        self.addAsyncCleanup(b.stop)
        await a._on_peer_discovered(_announce(a, b))
        await b._on_peer_discovered(_announce(b, a))
        return a, b

    async def test_two_controllers_discover_each_other(self) -> None:
        a, b = await self._pair()
        self.assertEqual([p.node_id for p in a.registry.list_peers()], ["node-b"])
        self.assertEqual([p.node_id for p in b.registry.list_peers()], ["node-a"])
        self.assertEqual(a.registry.list_peers()[0].port, b.listening_port)

    async def test_two_controllers_elect_single_responder(self) -> None:
        """Two nodes both hear speech start. Both broadcast RMS. After
        the ~150ms window, exactly one should decide to claim."""
        a, b = await self._pair()
        # a is louder (0.9), b is quieter (0.3). a should win.
        outcome_a, outcome_b = await asyncio.gather(
            a.run_election(session_id="session-a", local_rms=0.9, window_ms=150),
            b.run_election(session_id="session-b", local_rms=0.3, window_ms=150),
        )
        self.assertEqual(
            sum(1 for o in [outcome_a, outcome_b] if o.should_claim),
            1,
            f"expected exactly one claim, got a={outcome_a}, b={outcome_b}",
        )
        self.assertTrue(outcome_a.should_claim)
        self.assertFalse(outcome_b.should_claim)


if __name__ == "__main__":
    unittest.main()
