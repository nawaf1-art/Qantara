from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from gateway.mesh.discovery import DEFAULT_SERVICE_TYPE, MeshAdvertiser, MeshBrowser
from gateway.mesh.election import ElectionInput, ElectionOutcome, decide_claim
from gateway.mesh.peer_registry import PeerRecord, PeerRegistry
from gateway.mesh.protocol import Goodbye, Hello, MeshMessage, RmsUpdate, TurnClaim, TurnYield
from gateway.mesh.transport import MeshPeer, MeshServer

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MeshControllerConfig:
    node_id: str
    role: str = "full"
    mesh_port: int = 8901
    mesh_host: str = "0.0.0.0"
    service_type: str = DEFAULT_SERVICE_TYPE
    capabilities: dict = field(default_factory=dict)


class MeshController:
    """The single per-process object that owns everything mesh-related:
    the mDNS advertiser, the mDNS browser, the JSONL TCP server, and
    the outbound peer-connection pool. Exposes a small API to the rest
    of Qantara: broadcast_rms, broadcast_claim, broadcast_yield."""

    def __init__(self, cfg: MeshControllerConfig) -> None:
        self._cfg = cfg
        self._registry = PeerRegistry(local_node_id=cfg.node_id)
        self._advertiser = MeshAdvertiser(
            service_type=cfg.service_type,
            node_id=cfg.node_id,
            role=cfg.role,
            port=cfg.mesh_port,
            capabilities=cfg.capabilities,
        )
        self._browser = MeshBrowser(
            service_type=cfg.service_type,
            local_node_id=cfg.node_id,
            on_peer_added=self._on_peer_discovered,
            on_peer_removed=self._on_peer_lost,
        )
        self._server = MeshServer(
            host=cfg.mesh_host, port=cfg.mesh_port, on_message=self._on_message,
        )
        self._peer_connections: dict[str, MeshPeer] = {}
        self._started = False

    @property
    def registry(self) -> PeerRegistry:
        return self._registry

    @property
    def config(self) -> MeshControllerConfig:
        return self._cfg

    async def start(self) -> None:
        if self._started:
            return
        await self._server.start()
        await self._advertiser.start()
        await self._browser.start()
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        # Graceful goodbye to every known peer
        for peer in list(self._peer_connections.values()):
            try:
                await peer.send(Goodbye(node_id=self._cfg.node_id))
            except Exception:
                pass
            await peer.close()
        self._peer_connections.clear()
        await self._browser.stop()
        await self._advertiser.stop()
        await self._server.stop()
        self._started = False

    async def broadcast(self, msg: MeshMessage) -> None:
        """Send a message to every known peer. Errors are swallowed and
        logged — a flaky peer never blocks the others."""
        peers = list(self._registry.list_peers())
        for record in peers:
            conn = await self._ensure_connection(record)
            if conn is None:
                continue
            try:
                await conn.send(msg)
            except Exception:
                LOGGER.debug("mesh: send to %s failed; dropping peer", record.node_id, exc_info=True)
                await self._drop_peer(record.node_id)

    async def _ensure_connection(self, record: PeerRecord) -> MeshPeer | None:
        existing = self._peer_connections.get(record.node_id)
        if existing is not None:
            return existing
        peer = MeshPeer(host=record.host, port=record.port)
        try:
            await peer.connect()
            await peer.send(Hello(
                node_id=self._cfg.node_id,
                role=self._cfg.role,
                capabilities=self._cfg.capabilities,
            ))
            self._peer_connections[record.node_id] = peer
            return peer
        except Exception:
            LOGGER.debug("mesh: could not connect to %s:%d", record.host, record.port, exc_info=True)
            return None

    async def _drop_peer(self, node_id: str) -> None:
        peer = self._peer_connections.pop(node_id, None)
        if peer is not None:
            await peer.close()

    async def _on_peer_discovered(self, record_dict: dict) -> None:
        self._registry.upsert_peer(PeerRecord(
            node_id=record_dict["node_id"],
            role=record_dict.get("role", "full"),
            host=record_dict["host"],
            port=record_dict["port"],
        ))

    async def _on_peer_lost(self, node_id: str) -> None:
        self._registry.remove_peer(node_id)
        await self._drop_peer(node_id)

    async def _on_message(self, msg: MeshMessage, addr: tuple[str, int]) -> None:
        if isinstance(msg, Hello):
            # TCP-level hello — tells us about an inbound connection's
            # origin node. We register it in case the mDNS browser
            # hasn't caught up.
            self._registry.upsert_peer(PeerRecord(
                node_id=msg.node_id, role=msg.role, host=addr[0], port=0,
                capabilities=msg.capabilities,
            ))
        elif isinstance(msg, Goodbye):
            await self._on_peer_lost(msg.node_id)
        elif isinstance(msg, RmsUpdate):
            self._registry.record_rms(
                node_id=msg.node_id, session_id=msg.session_id,
                rms=msg.rms, monotonic_ms=msg.monotonic_ms,
            )
        elif isinstance(msg, TurnClaim):
            # Setting an RMS of the winner's value causes later
            # election decisions to correctly yield.
            self._registry.record_rms(
                node_id=msg.node_id, session_id=msg.session_id,
                rms=msg.rms, monotonic_ms=msg.monotonic_ms,
            )
        elif isinstance(msg, TurnYield):
            # Purely informational — log for telemetry.
            LOGGER.debug("mesh: %s yielded session %s to %s",
                         msg.node_id, msg.session_id, msg.winner_node_id)

    async def run_election(
        self,
        session_id: str,
        local_rms: float,
        window_ms: float = 150.0,
        now_ms: float | None = None,
    ) -> ElectionOutcome:
        """Broadcast this node's RMS, wait for peer RMS updates for
        `window_ms`, then compute the claim decision. Emits the claim
        or yield message to peers based on the outcome."""
        if now_ms is None:
            now_ms = time.monotonic() * 1000
        await self.broadcast(RmsUpdate(
            node_id=self._cfg.node_id,
            rms=local_rms,
            session_id=session_id,
            monotonic_ms=now_ms,
        ))
        # Sleep the election window; peers may send us rms_update frames during this time
        await asyncio.sleep(window_ms / 1000.0)
        peer_rms = {}
        peer_roles = {}
        for peer in self._registry.list_peers():
            rms = self._registry.latest_rms(node_id=peer.node_id, session_id=session_id)
            if rms is not None:
                peer_rms[peer.node_id] = rms
                peer_roles[peer.node_id] = peer.role
        outcome = decide_claim(ElectionInput(
            local_node_id=self._cfg.node_id,
            local_role=self._cfg.role,
            local_rms=local_rms,
            session_id=session_id,
            peer_rms=peer_rms,
            peer_roles=peer_roles,
        ))
        if outcome.should_claim:
            await self.broadcast(TurnClaim(
                node_id=self._cfg.node_id,
                session_id=session_id,
                rms=local_rms,
                monotonic_ms=now_ms,
            ))
        else:
            await self.broadcast(TurnYield(
                node_id=self._cfg.node_id,
                session_id=session_id,
                winner_node_id=outcome.winner_node_id,
            ))
        return outcome
