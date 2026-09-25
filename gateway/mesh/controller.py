from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass, field

from discovery.netinfo import is_loopback_host
from gateway.mesh.discovery import DEFAULT_SERVICE_TYPE, MeshAdvertiser, MeshBrowser
from gateway.mesh.election import ElectionInput, ElectionOutcome, decide_claim
from gateway.mesh.peer_registry import (
    DEFAULT_RMS_TTL_MS,
    Clock,
    PeerRecord,
    PeerRegistry,
    monotonic_ms,
)
from gateway.mesh.protocol import (
    Goodbye,
    Hello,
    MeshMessage,
    RmsUpdate,
    TurnClaim,
    TurnYield,
    is_valid_port,
)
from gateway.mesh.transport import DEFAULT_CONNECT_TIMEOUT_S, MeshPeer, MeshServer

LOGGER = logging.getLogger(__name__)

# Overall deadline for one broadcast to every peer (sent concurrently).
DEFAULT_BROADCAST_TIMEOUT_S = 0.5
# Cooldown after consecutive failures to reach a peer (MESH_PROTOCOL.md).
BACKOFF_SCHEDULE_MS = (1000.0, 2000.0, 4000.0, 8000.0)

_WILDCARD_HOSTS = {"", "0.0.0.0", "::"}


@dataclass(slots=True)
class MeshControllerConfig:
    node_id: str
    role: str = "full"
    mesh_port: int = 8901
    mesh_host: str = "127.0.0.1"
    service_type: str = DEFAULT_SERVICE_TYPE
    capabilities: dict = field(default_factory=dict)
    # Shared secret for HMAC frame authentication (QANTARA_MESH_TOKEN).
    # None keeps the legacy plaintext trusted-LAN behavior; the runtime only
    # allows that on loopback or with QANTARA_MESH_ALLOW_INSECURE=1.
    mesh_token: str | None = None
    connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S
    broadcast_timeout_s: float = DEFAULT_BROADCAST_TIMEOUT_S
    rms_ttl_ms: float = DEFAULT_RMS_TTL_MS


@dataclass(slots=True)
class _Backoff:
    failures: int = 0
    retry_at_ms: float = 0.0


class MeshController:
    """The single per-process object that owns everything mesh-related:
    the mDNS advertiser, the mDNS browser, the JSONL TCP server, and
    the outbound peer-connection pool. Exposes a small API to the rest
    of Qantara: broadcast and run_election.

    On a loopback bind no mDNS advertiser or browser is started: nothing on
    the LAN could reach this node, and advertising 127.0.0.1 makes other
    nodes connect to themselves (audit M-a)."""

    def __init__(self, cfg: MeshControllerConfig, clock: Clock | None = None) -> None:
        self._cfg = cfg
        self._clock = clock or monotonic_ms
        self._registry = PeerRegistry(
            local_node_id=cfg.node_id, rms_ttl_ms=cfg.rms_ttl_ms, clock=self._clock,
        )
        self._server = MeshServer(
            host=cfg.mesh_host, port=cfg.mesh_port, on_message=self._on_message,
            token=cfg.mesh_token,
        )
        self._advertiser: MeshAdvertiser | None = None
        self._browser: MeshBrowser | None = None
        self._peer_connections: dict[str, MeshPeer] = {}
        self._connect_locks: dict[str, asyncio.Lock] = {}
        self._backoff: dict[str, _Backoff] = {}
        self._tasks: set[asyncio.Task] = set()
        self._started = False

    @property
    def registry(self) -> PeerRegistry:
        return self._registry

    @property
    def config(self) -> MeshControllerConfig:
        return self._cfg

    @property
    def mdns_enabled(self) -> bool:
        return self._browser is not None

    @property
    def listening_port(self) -> int:
        sockets = self._server.sockets
        if sockets:
            return sockets[0].getsockname()[1]
        return self._cfg.mesh_port

    async def start(self) -> None:
        if self._started:
            return
        await self._server.start()
        self._started = True
        if is_loopback_host(self._cfg.mesh_host):
            LOGGER.info("mesh: bound to loopback %s; mDNS discovery disabled", self._cfg.mesh_host)
            return
        self._advertiser = MeshAdvertiser(
            service_type=self._cfg.service_type,
            node_id=self._cfg.node_id,
            role=self._cfg.role,
            port=self.listening_port,
            capabilities=self._cfg.capabilities,
            host_ip=None if self._cfg.mesh_host in _WILDCARD_HOSTS else self._cfg.mesh_host,
        )
        self._browser = MeshBrowser(
            service_type=self._cfg.service_type,
            local_node_id=self._cfg.node_id,
            on_peer_added=self._on_peer_discovered,
            on_peer_removed=self._on_peer_lost,
        )
        try:
            await self._advertiser.start()
            await self._browser.start()
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        # Background broadcasts and outbound connections can exist even if
        # start() was never called (broadcast/run_election work without the
        # inbound server), so always clean those up.
        was_started, self._started = self._started, False
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Graceful goodbye to every connected peer, bounded like a broadcast.
        peers = list(self._peer_connections.values())
        self._peer_connections.clear()
        if peers:
            goodbye = Goodbye(node_id=self._cfg.node_id)
            await self._run_bounded([peer.send(goodbye) for peer in peers])
            await asyncio.gather(*(peer.close() for peer in peers), return_exceptions=True)
        if not was_started:
            return
        if self._browser is not None:
            await self._browser.stop()
            self._browser = None
        if self._advertiser is not None:
            await self._advertiser.stop()
            self._advertiser = None
        await self._server.stop()

    async def broadcast(self, msg: MeshMessage) -> None:
        """Send a message to every known peer, concurrently, within
        ``broadcast_timeout_s``. Peers that fail are backed off (1/2/4/8 s)
        and skipped until their cooldown ends; a flaky or blackholed peer
        never delays the others (audit Q-12)."""
        peers = self._registry.list_peers()
        if peers:
            await self._run_bounded([self._send_to(record, msg) for record in peers])

    async def _run_bounded(self, coros: list[Awaitable[None]]) -> None:
        tasks = [asyncio.ensure_future(c) for c in coros]
        try:
            _done, pending = await asyncio.wait(tasks, timeout=self._cfg.broadcast_timeout_s)
        except asyncio.CancelledError:
            pending = set(tasks)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise
        for task in pending:
            task.cancel()
        # Also retrieves exceptions from finished tasks so none go unobserved.
        await asyncio.gather(*tasks, return_exceptions=True)

    def _in_backoff(self, node_id: str) -> bool:
        backoff = self._backoff.get(node_id)
        return backoff is not None and self._clock() < backoff.retry_at_ms

    def _note_failure(self, node_id: str) -> None:
        backoff = self._backoff.setdefault(node_id, _Backoff())
        delay = BACKOFF_SCHEDULE_MS[min(backoff.failures, len(BACKOFF_SCHEDULE_MS) - 1)]
        backoff.failures += 1
        backoff.retry_at_ms = self._clock() + delay

    async def _send_to(self, record: PeerRecord, msg: MeshMessage) -> None:
        if self._in_backoff(record.node_id):
            return
        try:
            conn = await self._ensure_connection(record)
            if conn is None:
                return
            await conn.send(msg)
        except asyncio.CancelledError:
            # Broadcast deadline hit: treat the peer as unreachable.
            self._note_failure(record.node_id)
            self._discard_connection(record.node_id)
            raise
        except Exception:
            LOGGER.debug("mesh: send to %s failed; backing off", record.node_id, exc_info=True)
            self._note_failure(record.node_id)
            self._discard_connection(record.node_id)
        else:
            self._backoff.pop(record.node_id, None)

    async def _ensure_connection(self, record: PeerRecord) -> MeshPeer | None:
        lock = self._connect_locks.setdefault(record.node_id, asyncio.Lock())
        async with lock:
            existing = self._peer_connections.get(record.node_id)
            if existing is not None and existing.is_connected:
                return existing
            peer = MeshPeer(
                host=record.host, port=record.port, token=self._cfg.mesh_token,
                connect_timeout_s=self._cfg.connect_timeout_s,
            )
            try:
                await peer.connect()
                port = self.listening_port
                await peer.send(Hello(
                    node_id=self._cfg.node_id,
                    role=self._cfg.role,
                    capabilities=self._cfg.capabilities,
                    port=port if is_valid_port(port) else None,
                ))
            except asyncio.CancelledError:
                peer.abort()
                raise
            except Exception:
                LOGGER.debug("mesh: could not connect to %s:%d", record.host, record.port, exc_info=True)
                peer.abort()
                self._note_failure(record.node_id)
                return None
            self._peer_connections[record.node_id] = peer
            return peer

    def _discard_connection(self, node_id: str) -> None:
        peer = self._peer_connections.pop(node_id, None)
        if peer is not None:
            peer.abort()

    async def _drop_peer(self, node_id: str) -> None:
        peer = self._peer_connections.pop(node_id, None)
        if peer is not None:
            await peer.close()

    async def _on_peer_discovered(self, record_dict: dict) -> None:
        self._registry.upsert_peer(PeerRecord(
            node_id=record_dict.get("node_id"),  # type: ignore[arg-type]
            role=record_dict.get("role", "full"),
            host=record_dict.get("host", ""),
            port=record_dict.get("port", 0),
        ))

    async def _on_peer_lost(self, node_id: str) -> None:
        self._registry.remove_peer(node_id)
        self._backoff.pop(node_id, None)
        await self._drop_peer(node_id)

    async def _on_message(self, msg: MeshMessage, addr: tuple[str, int]) -> None:
        if isinstance(msg, Hello):
            # TCP-level hello — tells us about an inbound connection's
            # origin node, including its listening port, so we can reach it
            # even if the mDNS browser hasn't caught up (or is disabled).
            self._registry.upsert_peer(PeerRecord(
                node_id=msg.node_id, role=msg.role, host=addr[0], port=msg.port or 0,
                capabilities=msg.capabilities,
            ))
            # The peer is evidently up again.
            self._backoff.pop(msg.node_id, None)
        elif isinstance(msg, Goodbye):
            await self._on_peer_lost(msg.node_id)
        elif isinstance(msg, (RmsUpdate, TurnClaim)):
            # Stamped with OUR clock on receipt; the sender's monotonic_ms
            # counts from the sender's boot and is meaningless here (Q-11).
            # A TurnClaim also refreshes the winner's RMS so a later
            # election on this node yields to it.
            self._registry.record_rms(node_id=msg.node_id, session_id=msg.session_id, rms=msg.rms)
        elif isinstance(msg, TurnYield):
            # Purely informational — log for telemetry.
            LOGGER.debug("mesh: %s yielded session %s to %s",
                         msg.node_id, msg.session_id, msg.winner_node_id)

    def _spawn(self, coro: Awaitable[None]) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def run_election(
        self,
        session_id: str,
        local_rms: float,
        window_ms: float = 150.0,
        now_ms: float | None = None,
    ) -> ElectionOutcome:
        """Broadcast this node's RMS, wait ``window_ms`` for peer RMS
        updates, then compute the claim decision and announce it.

        Returns after about ``window_ms`` no matter how slow the peers are:
        the RMS broadcast runs alongside the window, and the claim/yield
        announcement is sent in the background (each bounded by
        ``broadcast_timeout_s``). ``now_ms`` only stamps the outgoing frame.
        """
        sent_ms = self._clock() if now_ms is None else now_ms
        self._spawn(self.broadcast(RmsUpdate(
            node_id=self._cfg.node_id,
            rms=local_rms,
            session_id=session_id,
            monotonic_ms=sent_ms,
        )))
        # Peers' rms_update frames arrive during this window.
        await asyncio.sleep(window_ms / 1000.0)
        decision_ms = self._clock()
        self._registry.expire_stale(decision_ms)
        peer_rms = {}
        peer_roles = {}
        for peer in self._registry.list_peers():
            rms = self._registry.latest_rms(node_id=peer.node_id, now_ms=decision_ms)
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
            self._spawn(self.broadcast(TurnClaim(
                node_id=self._cfg.node_id,
                session_id=session_id,
                rms=local_rms,
                monotonic_ms=sent_ms,
            )))
        elif outcome.winner_node_id:
            self._spawn(self.broadcast(TurnYield(
                node_id=self._cfg.node_id,
                session_id=session_id,
                winner_node_id=outcome.winner_node_id,
            )))
        return outcome
