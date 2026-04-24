from __future__ import annotations

import asyncio
import unittest
import uuid

from gateway.mesh.discovery import MeshAdvertiser, MeshBrowser


class MeshDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_advertise_and_browse_round_trip(self) -> None:
        # Use a unique service type per test run so multiple CI invocations
        # don't step on each other and Avahi doesn't cache state.
        service_type = f"_qantest{uuid.uuid4().hex[:8]}._tcp.local."
        node_id = "node-advertise-test"

        adv = MeshAdvertiser(
            service_type=service_type,
            node_id=node_id,
            role="full",
            port=19900,
            capabilities={"stt": True, "tts": True},
        )
        await adv.start()
        try:
            seen: list[dict] = []

            async def on_peer(record: dict) -> None:
                seen.append(record)

            browser = MeshBrowser(
                service_type=service_type,
                local_node_id="observer",
                on_peer_added=on_peer,
                on_peer_removed=lambda _nid: asyncio.sleep(0),
            )
            await browser.start()
            try:
                # mDNS responses typically land within ~1s on localhost
                for _ in range(30):
                    if any(p["node_id"] == node_id for p in seen):
                        break
                    await asyncio.sleep(0.1)
            finally:
                await browser.stop()
        finally:
            await adv.stop()

        matches = [p for p in seen if p["node_id"] == node_id]
        self.assertTrue(matches, f"did not discover advertised node; saw: {seen}")
        self.assertEqual(matches[0]["role"], "full")
        self.assertEqual(matches[0]["port"], 19900)


if __name__ == "__main__":
    unittest.main()
