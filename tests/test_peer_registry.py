from __future__ import annotations

import time
import unittest

from gateway.mesh.peer_registry import PeerRecord, PeerRegistry


def _now_ms() -> float:
    return time.monotonic() * 1000


class PeerRegistryTests(unittest.TestCase):
    def test_upsert_adds_new_peer(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=8901))
        peers = reg.list_peers()
        self.assertEqual(len(peers), 1)
        self.assertEqual(peers[0].node_id, "a")

    def test_local_node_is_never_listed_as_peer(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        reg.upsert_peer(PeerRecord(node_id="local", role="full", host="127.0.0.1", port=8901))
        self.assertEqual(reg.list_peers(), [])

    def test_record_rms_stores_latest_observation(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=8901))
        reg.record_rms(node_id="a", session_id="s1", rms=0.5, monotonic_ms=_now_ms())
        reg.record_rms(node_id="a", session_id="s1", rms=0.9, monotonic_ms=_now_ms())
        self.assertAlmostEqual(reg.latest_rms(node_id="a", session_id="s1"), 0.9)

    def test_latest_rms_returns_none_for_unknown_peer(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        self.assertIsNone(reg.latest_rms(node_id="ghost", session_id="s1"))

    def test_latest_rms_returns_none_for_different_session(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=8901))
        reg.record_rms(node_id="a", session_id="s1", rms=0.5, monotonic_ms=_now_ms())
        self.assertIsNone(reg.latest_rms(node_id="a", session_id="s2"))

    def test_remove_peer_drops_state(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=8901))
        reg.remove_peer(node_id="a")
        self.assertEqual(reg.list_peers(), [])

    def test_expire_stale_drops_old_rms_entries(self) -> None:
        reg = PeerRegistry(local_node_id="local", rms_ttl_ms=100)
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=8901))
        old = _now_ms() - 500  # way past TTL
        reg.record_rms(node_id="a", session_id="s1", rms=0.5, monotonic_ms=old)
        reg.expire_stale(now_ms=_now_ms())
        self.assertIsNone(reg.latest_rms(node_id="a", session_id="s1"))


if __name__ == "__main__":
    unittest.main()
