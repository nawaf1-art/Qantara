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
        self.assertAlmostEqual(reg.latest_rms(node_id="a", now_ms=_now_ms()), 0.9)

    def test_latest_rms_returns_none_for_unknown_peer(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        self.assertIsNone(reg.latest_rms(node_id="ghost", now_ms=_now_ms()))

    def test_latest_rms_ignores_session_id_so_cross_node_election_works(self) -> None:
        # Each node generates its OWN per-connection session id, so matching peer
        # RMS by session id always failed -> peer_rms was always empty -> every
        # node claimed every utterance (split-brain). Recency, not session id, is
        # the correct freshness key for a cross-node election.
        reg = PeerRegistry(local_node_id="local", rms_ttl_ms=5000.0)
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=8901))
        now = _now_ms()
        reg.record_rms(node_id="a", session_id="peer-session-xyz", rms=0.7, monotonic_ms=now)
        self.assertAlmostEqual(reg.latest_rms(node_id="a", now_ms=now + 100.0), 0.7)

    def test_latest_rms_expires_after_ttl(self) -> None:
        reg = PeerRegistry(local_node_id="local", rms_ttl_ms=5000.0)
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=8901))
        now = _now_ms()
        reg.record_rms(node_id="a", session_id="s1", rms=0.7, monotonic_ms=now)
        self.assertIsNone(reg.latest_rms(node_id="a", now_ms=now + 6000.0))

    def test_hello_with_zero_port_does_not_clobber_known_port(self) -> None:
        # A TCP-level Hello only knows the inbound socket's ephemeral source
        # port, so it upserts port=0. It must not destroy a good host/port the
        # mDNS browser already resolved, or outbound reconnect breaks forever.
        reg = PeerRegistry(local_node_id="local")
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=8901))
        reg.upsert_peer(PeerRecord(node_id="a", role="mic-only", host="10.0.0.9", port=0))
        peer = next(p for p in reg.list_peers() if p.node_id == "a")
        self.assertEqual(peer.port, 8901)
        self.assertEqual(peer.host, "10.0.0.2")
        self.assertEqual(peer.role, "mic-only")  # role still merges from the Hello

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
        self.assertIsNone(reg.latest_rms(node_id="a", now_ms=_now_ms()))


if __name__ == "__main__":
    unittest.main()
