from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from gateway.mesh.protocol import is_valid_node_id, is_valid_port, is_valid_role

LOGGER = logging.getLogger(__name__)

# How long a peer's RMS observation counts as "the same utterance". Peers
# hear the same speech start within a few hundred ms of each other; anything
# older belongs to an earlier turn.
DEFAULT_RMS_TTL_MS = 1000.0

Clock = Callable[[], float]


def monotonic_ms() -> float:
    return time.monotonic() * 1000.0


@dataclass(slots=True)
class PeerRecord:
    node_id: str
    role: str
    host: str
    port: int
    capabilities: dict = field(default_factory=dict)


@dataclass(slots=True)
class _RmsObservation:
    session_id: str
    rms: float
    received_ms: float


class PeerRegistry:
    """In-memory state of the mesh from this node's point of view. Not
    thread-safe — all mutations happen from the same asyncio event loop
    (the one running the mesh TCP server + discovery browser).

    RMS observations are stamped with THIS node's monotonic clock when they
    are received. A peer's own ``monotonic_ms`` counts from that peer's boot,
    so comparing it with the local clock would make a peer permanently
    fresh or permanently stale (audit Q-11).
    """

    def __init__(
        self,
        local_node_id: str,
        rms_ttl_ms: float = DEFAULT_RMS_TTL_MS,
        clock: Clock | None = None,
    ) -> None:
        self._local_node_id = local_node_id
        self._rms_ttl_ms = rms_ttl_ms
        self._clock = clock or monotonic_ms
        self._peers: dict[str, PeerRecord] = {}
        self._rms: dict[str, _RmsObservation] = {}

    @property
    def local_node_id(self) -> str:
        return self._local_node_id

    def now_ms(self) -> float:
        return self._clock()

    def upsert_peer(self, record: PeerRecord) -> bool:
        """Add or update a peer. Returns False (and stores nothing) for the
        local node, malformed identities, or a record with no reachable
        port and no earlier record to borrow one from."""
        if not is_valid_node_id(record.node_id) or not is_valid_role(record.role):
            LOGGER.debug("mesh: dropping peer record with invalid identity")
            return False
        if record.node_id == self._local_node_id:
            return False
        if not is_valid_port(record.port):
            # An older peer's Hello carries no listening port. Keep the
            # host/port the mDNS browser already resolved, if any; never store
            # an unreachable port=0 entry.
            existing = self._peers.get(record.node_id)
            if existing is None:
                return False
            record = replace(record, host=existing.host, port=existing.port)
        if not isinstance(record.host, str) or not record.host:
            return False
        self._peers[record.node_id] = record
        return True

    def remove_peer(self, node_id: str) -> None:
        self._peers.pop(node_id, None)
        self._rms.pop(node_id, None)

    def list_peers(self) -> list[PeerRecord]:
        return list(self._peers.values())

    def record_rms(
        self,
        node_id: str,
        session_id: str,
        rms: float,
        received_ms: float | None = None,
    ) -> None:
        if node_id == self._local_node_id:
            return
        self._rms[node_id] = _RmsObservation(
            session_id=session_id,
            rms=rms,
            received_ms=self._clock() if received_ms is None else received_ms,
        )

    def latest_rms(self, node_id: str, now_ms: float | None = None) -> float | None:
        """Return the peer's most recent RMS if it is still fresh.

        Freshness is by recency (TTL) on the local clock, NOT by session id:
        every node uses its own per-connection session id, so a session-id
        match never succeeds across nodes.
        """
        obs = self._rms.get(node_id)
        now = self._clock() if now_ms is None else now_ms
        if obs is None or (now - obs.received_ms) > self._rms_ttl_ms:
            return None
        return obs.rms

    def expire_stale(self, now_ms: float | None = None) -> None:
        now = self._clock() if now_ms is None else now_ms
        cutoff = now - self._rms_ttl_ms
        stale = [n for n, obs in self._rms.items() if obs.received_ms < cutoff]
        for n in stale:
            self._rms.pop(n, None)
