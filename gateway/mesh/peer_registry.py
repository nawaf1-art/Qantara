from __future__ import annotations

from dataclasses import dataclass, field


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
    monotonic_ms: float


class PeerRegistry:
    """In-memory state of the mesh from this node's point of view. Not
    thread-safe — all mutations happen from the same asyncio event loop
    (the one running the mesh TCP server + discovery browser).

    Observations have a TTL so a peer's RMS from 30 seconds ago isn't
    treated as current during a new election.
    """

    def __init__(self, local_node_id: str, rms_ttl_ms: float = 5000.0) -> None:
        self._local_node_id = local_node_id
        self._rms_ttl_ms = rms_ttl_ms
        self._peers: dict[str, PeerRecord] = {}
        self._rms: dict[str, _RmsObservation] = {}

    @property
    def local_node_id(self) -> str:
        return self._local_node_id

    def upsert_peer(self, record: PeerRecord) -> None:
        if record.node_id == self._local_node_id:
            return
        self._peers[record.node_id] = record

    def remove_peer(self, node_id: str) -> None:
        self._peers.pop(node_id, None)
        self._rms.pop(node_id, None)

    def list_peers(self) -> list[PeerRecord]:
        return list(self._peers.values())

    def record_rms(self, node_id: str, session_id: str, rms: float, monotonic_ms: float) -> None:
        if node_id == self._local_node_id:
            return
        self._rms[node_id] = _RmsObservation(
            session_id=session_id, rms=rms, monotonic_ms=monotonic_ms
        )

    def latest_rms(self, node_id: str, session_id: str) -> float | None:
        obs = self._rms.get(node_id)
        if obs is None or obs.session_id != session_id:
            return None
        return obs.rms

    def expire_stale(self, now_ms: float) -> None:
        cutoff = now_ms - self._rms_ttl_ms
        stale = [n for n, obs in self._rms.items() if obs.monotonic_ms < cutoff]
        for n in stale:
            self._rms.pop(n, None)
