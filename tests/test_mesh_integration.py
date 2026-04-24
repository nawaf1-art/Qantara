from __future__ import annotations

import asyncio
import unittest
import uuid

from gateway.mesh.controller import MeshController, MeshControllerConfig


class MeshIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_controllers_discover_each_other(self) -> None:
        service_type = f"_qantest{uuid.uuid4().hex[:8]}._tcp.local."
        a = MeshController(MeshControllerConfig(
            node_id="node-a", role="full", mesh_port=19901,
            service_type=service_type, capabilities={"stt": True},
        ))
        b = MeshController(MeshControllerConfig(
            node_id="node-b", role="full", mesh_port=19902,
            service_type=service_type, capabilities={"stt": True},
        ))
        await a.start()
        await b.start()
        try:
            for _ in range(30):
                a_sees_b = any(p.node_id == "node-b" for p in a.registry.list_peers())
                b_sees_a = any(p.node_id == "node-a" for p in b.registry.list_peers())
                if a_sees_b and b_sees_a:
                    break
                await asyncio.sleep(0.1)
            self.assertTrue(a_sees_b, f"a did not discover b; peers: {a.registry.list_peers()}")
            self.assertTrue(b_sees_a, f"b did not discover a; peers: {b.registry.list_peers()}")
        finally:
            await a.stop()
            await b.stop()


    async def test_two_controllers_elect_single_responder(self) -> None:
        """Two nodes both hear speech start. Both broadcast RMS. After
        the ~150ms window, exactly one should decide to claim."""
        import time

        service_type = f"_qantest{uuid.uuid4().hex[:8]}._tcp.local."
        a = MeshController(MeshControllerConfig(
            node_id="node-a", role="full", mesh_port=19903,
            service_type=service_type,
        ))
        b = MeshController(MeshControllerConfig(
            node_id="node-b", role="full", mesh_port=19904,
            service_type=service_type,
        ))
        await a.start()
        await b.start()
        try:
            # Wait for discovery
            for _ in range(30):
                if (any(p.node_id == "node-b" for p in a.registry.list_peers())
                        and any(p.node_id == "node-a" for p in b.registry.list_peers())):
                    break
                await asyncio.sleep(0.1)

            session_id = "shared-session"
            now_ms = time.monotonic() * 1000
            # a is louder (0.9), b is quieter (0.3). a should win.
            outcome_a, outcome_b = await asyncio.gather(
                a.run_election(session_id=session_id, local_rms=0.9, window_ms=150, now_ms=now_ms),
                b.run_election(session_id=session_id, local_rms=0.3, window_ms=150, now_ms=now_ms),
            )
            # Only one of the two nodes should have claimed
            self.assertEqual(
                sum(1 for o in [outcome_a, outcome_b] if o.should_claim),
                1,
                f"expected exactly one claim, got a={outcome_a}, b={outcome_b}",
            )
            self.assertTrue(outcome_a.should_claim)
            self.assertFalse(outcome_b.should_claim)
        finally:
            await a.stop()
            await b.stop()


if __name__ == "__main__":
    unittest.main()
