"""Regression tests for the 2026-09-24 audit mesh findings.

Q-11 (ME-1, ME-2) election correctness, Q-12 (ME-4) unreachable peers,
Q-09 server side (ME-3) identifier validation, M-a (ME-7) loopback mDNS,
M-e (ME-K1) token policy, ME-10 malformed frames, ME-11 role parsing and
Q-13 Wyoming removal.

Everything here is hermetic: TCP only on 127.0.0.1 with port 0, no mDNS
on the real network (zeroconf is mocked), and "unreachable" peers are
simulated with a fake connect that never completes -- no packet is ever
sent to a LAN address.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import time
import unittest
import unittest.mock
from pathlib import Path

from adapters.base import AdapterConfig
from gateway.mesh import transport as mesh_transport
from gateway.mesh.controller import MeshController, MeshControllerConfig
from gateway.mesh.election import ElectionInput, decide_claim
from gateway.mesh.peer_registry import DEFAULT_RMS_TTL_MS, PeerRecord, PeerRegistry
from gateway.mesh.protocol import (
    Hello,
    RmsUpdate,
    TurnClaim,
    decode_message,
    is_valid_node_id,
    verify_frame,
)
from gateway.mesh.transport import MeshPeer, MeshServer
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS

REPO_ROOT = Path(__file__).resolve().parents[1]

# A documentation-range address (TEST-NET-3). The fake opener below
# intercepts it, so nothing is ever sent to it.
BLACKHOLE_HOST = "203.0.113.7"


class FakeClock:
    """Millisecond clock with an arbitrary base that advances with real
    time, so asyncio sleeps still line up, plus a manual offset."""

    def __init__(self, base_ms: float) -> None:
        self._base = base_ms
        self._start = time.monotonic()
        self.extra_ms = 0.0

    def __call__(self) -> float:
        return self._base + (time.monotonic() - self._start) * 1000.0 + self.extra_ms

    def advance(self, ms: float) -> None:
        self.extra_ms += ms


def _election(local_id, local_role, local_rms, peers):
    """peers: {node_id: (role, rms)}"""
    return decide_claim(ElectionInput(
        local_node_id=local_id,
        local_role=local_role,
        local_rms=local_rms,
        session_id="s",
        peer_rms={n: rms for n, (_role, rms) in peers.items()},
        peer_roles={n: role for n, (role, _rms) in peers.items()},
    ))


def _all_views(nodes):
    """nodes: {node_id: (role, rms)} -> {node_id: outcome as seen by that node}"""
    views = {}
    for node_id, (role, rms) in nodes.items():
        others = {n: v for n, v in nodes.items() if n != node_id}
        views[node_id] = _election(node_id, role, rms, others)
    return views


class ElectionConsistencyTests(unittest.TestCase):
    def test_full_node_claims_over_louder_mic_only_peer(self) -> None:
        # The docs' phone (mic-only) + desk (full) example deadlocked: the
        # mic-only phone yielded to the desk, and the desk yielded to the
        # louder phone. The full node must win everywhere.
        views = _all_views({"phone": ("mic-only", 0.9), "desk": ("full", 0.2)})
        self.assertFalse(views["phone"].should_claim)
        self.assertTrue(views["desk"].should_claim)
        self.assertEqual({v.winner_node_id for v in views.values()}, {"desk"})

    def test_every_node_agrees_on_exactly_one_winner(self) -> None:
        scenarios = [
            {"a": ("full", 0.5), "b": ("full", 0.5)},
            {"a": ("mic-only", 0.9), "b": ("full", 0.1), "c": ("full", 0.3)},
            {"a": ("mic-only", 0.9), "b": ("mic-only", 0.4)},
            {"a": ("speaker-only", 0.9), "b": ("full", 0.1), "c": ("mic-only", 0.8)},
            {"qantara-bbbb": ("full", 0.5), "qantara-aaaa": ("full", 0.5), "m": ("mic-only", 0.9)},
        ]
        for nodes in scenarios:
            with self.subTest(nodes=nodes):
                views = _all_views(nodes)
                claimers = [n for n, o in views.items() if o.should_claim]
                self.assertEqual(len(claimers), 1, views)
                self.assertEqual({o.winner_node_id for o in views.values()}, {claimers[0]})

    def test_mic_only_tie_break_uses_full_node_id(self) -> None:
        # Default node ids share the 8-byte "qantara-" prefix, which the old
        # _lex() helper truncated to -- ties then depended on dict order.
        for order in (("qantara-bbbb", "qantara-aaaa"), ("qantara-aaaa", "qantara-bbbb")):
            peers = {n: ("full", 0.5) for n in order}
            outcome = _election("phone", "mic-only", 0.9, peers)
            self.assertFalse(outcome.should_claim)
            self.assertEqual(outcome.winner_node_id, "qantara-aaaa")

    def test_lone_speaker_only_node_never_claims(self) -> None:
        outcome = _election("tablet", "speaker-only", 0.9, {})
        self.assertFalse(outcome.should_claim)

    def test_unknown_local_role_never_claims(self) -> None:
        outcome = _election("x", "admin", 0.9, {})
        self.assertFalse(outcome.should_claim)

    def test_unknown_peer_role_is_not_a_candidate(self) -> None:
        outcome = _election("a", "full", 0.1, {"b": ("admin", 0.9)})
        self.assertTrue(outcome.should_claim)
        self.assertEqual(outcome.winner_node_id, "a")


class PeerRegistryClockTests(unittest.TestCase):
    def test_default_rms_ttl_is_about_one_second(self) -> None:
        self.assertLessEqual(DEFAULT_RMS_TTL_MS, 1500)
        self.assertGreaterEqual(DEFAULT_RMS_TTL_MS, 500)

    def test_observation_is_stamped_with_receiver_clock(self) -> None:
        clock = FakeClock(base_ms=10_000.0)
        reg = PeerRegistry(local_node_id="local", clock=clock)
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="127.0.0.1", port=9))
        reg.record_rms(node_id="a", session_id="s", rms=0.7)
        self.assertAlmostEqual(reg.latest_rms("a"), 0.7)
        clock.advance(DEFAULT_RMS_TTL_MS + 500)
        self.assertIsNone(reg.latest_rms("a"))

    def test_rms_update_monotonic_ms_from_remote_clock_is_ignored(self) -> None:
        # The remote node booted an hour earlier; its monotonic stamp must not
        # make the observation look stale (or eternally fresh) locally.
        async def run() -> None:
            clock = FakeClock(base_ms=5_000.0)
            ctrl = MeshController(
                MeshControllerConfig(node_id="local", role="full", mesh_port=0),
                clock=clock,
            )
            ctrl.registry.upsert_peer(PeerRecord(node_id="a", role="full", host="127.0.0.1", port=9))
            await ctrl._on_message(
                RmsUpdate(node_id="a", rms=0.4, session_id="s", monotonic_ms=3_600_000.0 + 5_000.0),
                ("127.0.0.1", 5555),
            )
            self.assertAlmostEqual(ctrl.registry.latest_rms("a"), 0.4)
            await ctrl._on_message(
                TurnClaim(node_id="a", session_id="s", rms=0.6, monotonic_ms=1.0),
                ("127.0.0.1", 5555),
            )
            self.assertAlmostEqual(ctrl.registry.latest_rms("a"), 0.6)

        asyncio.run(run())


class IdentifierValidationTests(unittest.TestCase):
    BAD_IDS = ("", "a b", "<img src=x onerror=alert(1)>", "x" * 65, "node/1", "né", None, 5)

    def test_node_id_pattern(self) -> None:
        for good in ("a", "qantara-1a2b3c4d", "Node_1.local", "x" * 64):
            self.assertTrue(is_valid_node_id(good), good)
        for bad in self.BAD_IDS:
            self.assertFalse(is_valid_node_id(bad), repr(bad))

    def test_registry_drops_invalid_node_ids_and_roles(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        for bad in self.BAD_IDS:
            self.assertFalse(reg.upsert_peer(PeerRecord(node_id=bad, role="full", host="10.0.0.2", port=8901)))
        for bad_role in ("admin", "<b>x</b>", "", "FULL "):
            self.assertFalse(reg.upsert_peer(PeerRecord(node_id="ok", role=bad_role, host="10.0.0.2", port=8901)))
        self.assertEqual(reg.list_peers(), [])
        self.assertTrue(reg.upsert_peer(PeerRecord(node_id="ok", role="mic-only", host="10.0.0.2", port=8901)))

    def test_registry_does_not_store_unreachable_port_zero_record(self) -> None:
        reg = PeerRegistry(local_node_id="local")
        reg.upsert_peer(PeerRecord(node_id="a", role="full", host="10.0.0.2", port=0))
        self.assertEqual(reg.list_peers(), [])

    def test_hello_rejects_bad_node_id_and_role(self) -> None:
        for frame in (
            {"type": "hello", "node_id": "<img src=x onerror=alert(1)>", "role": "full"},
            {"type": "hello", "node_id": "a", "role": "<script>"},
            {"type": "hello", "node_id": "a", "role": "full", "port": 70000},
            {"type": "hello", "node_id": "a", "role": "full", "port": "8901"},
            {"type": "hello", "node_id": "a", "role": "full", "port": True},
            {"type": "rms_update", "node_id": "a b", "rms": 0.1, "session_id": "s", "monotonic_ms": 1.0},
            {"type": "turn_yield", "node_id": "a", "session_id": "s", "winner_node_id": "<x>"},
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_message(frame)

    def test_hello_carries_listening_port(self) -> None:
        msg = decode_message(Hello(node_id="a", role="full", port=8901).to_dict())
        self.assertEqual(msg.port, 8901)
        # Older peers omit the port; that must still decode.
        legacy = decode_message({"type": "hello", "node_id": "a", "role": "full"})
        self.assertIsNone(legacy.port)

    def test_decode_rejects_non_object_and_bad_type_field(self) -> None:
        for raw in ([1], "hello", 3, None, {"type": [1], "node_id": "a"}, {"type": {"x": 1}}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_message(raw)  # type: ignore[arg-type]

    def test_verify_frame_rejects_non_object(self) -> None:
        for raw in ([1], "x", 3, None):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                verify_frame(raw, "t" * 32)  # type: ignore[arg-type]


class MalformedFrameTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_frames_close_connection_without_errors(self) -> None:
        loop_errors: list = []
        asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: loop_errors.append(ctx))
        received: list = []

        async def on_message(msg, addr) -> None:
            received.append(msg)

        for token in (None, "t" * 32):
            server = MeshServer("127.0.0.1", 0, on_message, token=token)
            await server.start()
            port = server.sockets[0].getsockname()[1]
            try:
                blobs = {
                    "json array": b"[1]\n",
                    "json string": b'"hello"\n',
                    "unhashable type": b'{"type":[1],"node_id":"a"}\n',
                    "oversized line": b'{"type":"hello","node_id":"' + b"a" * 70000 + b'"}\n',
                    "not json": b"garbage\n",
                }
                for name, blob in blobs.items():
                    with self.subTest(token=bool(token), frame=name):
                        with self.assertNoLogs("gateway.mesh", level="WARNING"):
                            reader, writer = await asyncio.open_connection("127.0.0.1", port)
                            writer.write(blob)
                            await writer.drain()
                            # The server closes this connection.
                            data = await asyncio.wait_for(reader.read(), timeout=2.0)
                            self.assertEqual(data, b"")
                            writer.close()
                            await asyncio.sleep(0.02)
                        self.assertEqual(loop_errors, [])
                # The server still serves well-formed peers afterwards.
                peer = MeshPeer("127.0.0.1", port, token=token)
                await peer.connect()
                await peer.send(Hello(node_id="after", role="full"))
                await asyncio.sleep(0.05)
                await peer.close()
            finally:
                await server.stop()
        self.assertEqual([m.node_id for m in received], ["after", "after"])


class _BlackholeOpener:
    """Stand-in for asyncio.open_connection: connections to BLACKHOLE_HOST
    never complete (a sleeping or firewalled peer); everything else goes to
    the real loopback socket."""

    def __init__(self) -> None:
        self.blackhole_attempts = 0
        self._real = asyncio.open_connection

    async def __call__(self, host, port, **kwargs):
        if host == BLACKHOLE_HOST:
            self.blackhole_attempts += 1
            await asyncio.Event().wait()
        return await self._real(host, port, **kwargs)


class UnreachablePeerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.opener = _BlackholeOpener()
        patcher = unittest.mock.patch.object(mesh_transport, "_open_connection", self.opener)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_peer_connect_times_out(self) -> None:
        peer = MeshPeer(BLACKHOLE_HOST, 8901, connect_timeout_s=0.2)
        start = time.monotonic()
        with self.assertRaises((TimeoutError, asyncio.TimeoutError)):
            await peer.connect()
        self.assertLess(time.monotonic() - start, 1.0)

    async def test_default_connect_timeout_is_half_a_second(self) -> None:
        self.assertEqual(mesh_transport.DEFAULT_CONNECT_TIMEOUT_S, 0.5)

    async def _start_sink(self):
        received: list = []

        async def on_message(msg, addr) -> None:
            received.append(msg)

        server = MeshServer("127.0.0.1", 0, on_message)
        await server.start()
        self.addAsyncCleanup(server.stop)
        return server.sockets[0].getsockname()[1], received

    async def test_broadcast_is_concurrent_and_bounded(self) -> None:
        port, received = await self._start_sink()
        ctrl = MeshController(MeshControllerConfig(node_id="me", role="full", mesh_port=0))
        self.addAsyncCleanup(ctrl.stop)
        # Blackholed peer sorts first so a sequential loop would hit it first.
        ctrl.registry.upsert_peer(PeerRecord(node_id="a-dead", role="full", host=BLACKHOLE_HOST, port=8901))
        ctrl.registry.upsert_peer(PeerRecord(node_id="b-live", role="full", host="127.0.0.1", port=port))
        start = time.monotonic()
        await asyncio.wait_for(ctrl.broadcast(RmsUpdate(node_id="me", rms=0.5, session_id="s", monotonic_ms=1.0)), 3.0)
        self.assertLess(time.monotonic() - start, 0.9)
        await asyncio.sleep(0.05)
        self.assertTrue(any(isinstance(m, RmsUpdate) for m in received), received)

    async def test_failed_peer_is_backed_off(self) -> None:
        clock = FakeClock(base_ms=0.0)
        ctrl = MeshController(MeshControllerConfig(node_id="me", role="full", mesh_port=0), clock=clock)
        self.addAsyncCleanup(ctrl.stop)
        ctrl.registry.upsert_peer(PeerRecord(node_id="dead", role="full", host=BLACKHOLE_HOST, port=8901))
        msg = RmsUpdate(node_id="me", rms=0.5, session_id="s", monotonic_ms=1.0)

        await ctrl.broadcast(msg)
        self.assertEqual(self.opener.blackhole_attempts, 1)
        # Inside the 1 s cooldown: no new attempt, and broadcast returns at once.
        start = time.monotonic()
        await ctrl.broadcast(msg)
        self.assertLess(time.monotonic() - start, 0.1)
        self.assertEqual(self.opener.blackhole_attempts, 1)
        # After 1 s: retry, fail again -> 2 s cooldown.
        clock.advance(1100)
        await ctrl.broadcast(msg)
        self.assertEqual(self.opener.blackhole_attempts, 2)
        clock.advance(1100)
        await ctrl.broadcast(msg)
        self.assertEqual(self.opener.blackhole_attempts, 2)
        clock.advance(1100)
        await ctrl.broadcast(msg)
        self.assertEqual(self.opener.blackhole_attempts, 3)

    async def test_run_election_returns_within_window_with_blackholed_peer(self) -> None:
        ctrl = MeshController(MeshControllerConfig(node_id="me", role="full", mesh_port=0))
        self.addAsyncCleanup(ctrl.stop)
        ctrl.registry.upsert_peer(PeerRecord(node_id="dead", role="full", host=BLACKHOLE_HOST, port=8901))
        start = time.monotonic()
        outcome = await asyncio.wait_for(ctrl.run_election(session_id="s", local_rms=0.5, window_ms=150), 5.0)
        elapsed = time.monotonic() - start
        self.assertTrue(outcome.should_claim)
        self.assertLess(elapsed, 0.15 + 0.2)


class TwoNodeElectionTests(unittest.IsolatedAsyncioTestCase):
    """Two controllers on loopback with monotonic clocks an hour apart --
    the situation of two real machines that booted at different times."""

    async def _pair(self, role_a="full", role_b="full"):
        a = MeshController(
            MeshControllerConfig(node_id="node-a", role=role_a, mesh_port=0),
            clock=FakeClock(base_ms=1_000.0),
        )
        b = MeshController(
            MeshControllerConfig(node_id="node-b", role=role_b, mesh_port=0),
            clock=FakeClock(base_ms=3_600_000.0),
        )
        await a.start()
        self.addAsyncCleanup(a.stop)
        await b.start()
        self.addAsyncCleanup(b.stop)
        a.registry.upsert_peer(PeerRecord(node_id="node-b", role=role_b, host="127.0.0.1", port=b.listening_port))
        b.registry.upsert_peer(PeerRecord(node_id="node-a", role=role_a, host="127.0.0.1", port=a.listening_port))
        return a, b

    async def _elect(self, a, b, rms_a, rms_b):
        return await asyncio.gather(
            a.run_election(session_id="sa", local_rms=rms_a, window_ms=150),
            b.run_election(session_id="sb", local_rms=rms_b, window_ms=150),
        )

    async def test_exactly_one_claims_despite_clock_skew(self) -> None:
        a, b = await self._pair()
        for rms_a, rms_b, winner in ((0.9, 0.3, "node-a"), (0.2, 0.8, "node-b")):
            with self.subTest(rms_a=rms_a, rms_b=rms_b):
                out_a, out_b = await self._elect(a, b, rms_a, rms_b)
                self.assertEqual([out_a.should_claim, out_b.should_claim].count(True), 1, (out_a, out_b))
                self.assertEqual(out_a.winner_node_id, winner)
                self.assertEqual(out_b.winner_node_id, winner)
                await asyncio.sleep(DEFAULT_RMS_TTL_MS / 1000.0 + 0.1)

    async def test_mic_only_and_full_pair_does_not_deadlock(self) -> None:
        a, b = await self._pair(role_a="mic-only", role_b="full")
        out_a, out_b = await self._elect(a, b, 0.9, 0.2)
        self.assertFalse(out_a.should_claim)
        self.assertTrue(out_b.should_claim)

    async def test_peer_learned_from_hello_is_reachable(self) -> None:
        a = MeshController(MeshControllerConfig(node_id="node-a", role="full", mesh_port=0))
        b = MeshController(MeshControllerConfig(node_id="node-b", role="full", mesh_port=0))
        await a.start()
        self.addAsyncCleanup(a.stop)
        await b.start()
        self.addAsyncCleanup(b.stop)
        # Only b knows about a; a learns b from b's Hello.
        b.registry.upsert_peer(PeerRecord(node_id="node-a", role="full", host="127.0.0.1", port=a.listening_port))
        await b.broadcast(RmsUpdate(node_id="node-b", rms=0.1, session_id="s", monotonic_ms=1.0))
        await asyncio.sleep(0.05)
        learned = {p.node_id: p for p in a.registry.list_peers()}
        self.assertIn("node-b", learned)
        self.assertEqual(learned["node-b"].port, b.listening_port)
        self.assertNotEqual(learned["node-b"].port, 0)


class LoopbackDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_loopback_bind_does_not_start_mdns(self) -> None:
        with unittest.mock.patch("gateway.mesh.discovery.AsyncZeroconf") as zc:
            for host in ("127.0.0.1", "localhost", "::1"):
                ctrl = MeshController(MeshControllerConfig(node_id="me", role="full", mesh_port=0, mesh_host=host))
                try:
                    await ctrl.start()
                except OSError:
                    continue  # no IPv6 loopback on this host
                try:
                    self.assertFalse(ctrl.mdns_enabled)
                finally:
                    await ctrl.stop()
            zc.assert_not_called()

    async def test_advertiser_never_advertises_loopback(self) -> None:
        from gateway.mesh import discovery

        with unittest.mock.patch.object(discovery, "AsyncZeroconf") as zc, \
                unittest.mock.patch.object(discovery, "_resolve_local_ipv4", return_value="127.0.0.1"):
            adv = discovery.MeshAdvertiser(
                service_type="_qantest._tcp.local.", node_id="me", role="full", port=8901, capabilities={},
            )
            with self.assertLogs("gateway.mesh.discovery", level="WARNING"):
                await adv.start()
            await adv.stop()
            zc.assert_not_called()

    async def test_non_loopback_bind_starts_discovery(self) -> None:
        from gateway.mesh import controller as controller_mod

        adv = unittest.mock.MagicMock()
        adv.start = unittest.mock.AsyncMock()
        adv.stop = unittest.mock.AsyncMock()
        browser = unittest.mock.MagicMock()
        browser.start = unittest.mock.AsyncMock()
        browser.stop = unittest.mock.AsyncMock()
        server = unittest.mock.MagicMock()
        server.start = unittest.mock.AsyncMock()
        server.stop = unittest.mock.AsyncMock()
        server.sockets = []
        with unittest.mock.patch.object(controller_mod, "MeshAdvertiser", return_value=adv), \
                unittest.mock.patch.object(controller_mod, "MeshBrowser", return_value=browser), \
                unittest.mock.patch.object(controller_mod, "MeshServer", return_value=server):
            ctrl = MeshController(MeshControllerConfig(
                node_id="me", role="full", mesh_port=8901, mesh_host="192.168.50.5", mesh_token="t" * 32,
            ))
            await ctrl.start()
            self.assertTrue(ctrl.mdns_enabled)
            await ctrl.stop()
        adv.start.assert_awaited_once()
        browser.start.assert_awaited_once()

    async def test_discovered_records_with_bad_identity_are_dropped(self) -> None:
        ctrl = MeshController(MeshControllerConfig(node_id="me", role="full", mesh_port=0))
        await ctrl._on_peer_discovered(
            {"node_id": "<img src=x onerror=alert(1)>", "role": "full", "host": "10.0.0.5", "port": 8901},
        )
        await ctrl._on_peer_discovered({"node_id": "ok", "role": "<b>", "host": "10.0.0.5", "port": 8901})
        await ctrl._on_peer_discovered({"node_id": "ok", "role": "full", "host": "10.0.0.5", "port": 0})
        self.assertEqual(ctrl.registry.list_peers(), [])
        await ctrl._on_peer_discovered({"node_id": "ok", "role": "full", "host": "10.0.0.5", "port": 8901})
        self.assertEqual([p.node_id for p in ctrl.registry.list_peers()], ["ok"])

    async def test_browser_drops_invalid_txt_records(self) -> None:
        from gateway.mesh import discovery

        seen: list[dict] = []

        async def on_added(record):
            seen.append(record)

        async def on_removed(_node_id):
            return None

        class FakeInfo:
            props: dict = {}

            def __init__(self, *_a, **_kw):
                self.properties = FakeInfo.props
                self.port = 8901

            async def async_request(self, *_a, **_kw):
                return True

            def parsed_addresses(self):
                return ["10.0.0.9"]

        browser = discovery.MeshBrowser("_qantest._tcp.local.", "me", on_added, on_removed)
        browser._aiozc = unittest.mock.MagicMock()
        with unittest.mock.patch.object(discovery, "AsyncServiceInfo", FakeInfo):
            for props in (
                {b"node_id": b"<img src=x onerror=alert(1)>", b"role": b"full"},
                {b"node_id": b"peer1", b"role": b"<script>"},
            ):
                FakeInfo.props = props
                await browser._handle_change("_qantest._tcp.local.", "x._qantest._tcp.local.",
                                             discovery.ServiceStateChange.Added)
            self.assertEqual(seen, [])
            FakeInfo.props = {b"node_id": b"peer1", b"role": b"mic-only"}
            await browser._handle_change("_qantest._tcp.local.", "x._qantest._tcp.local.",
                                         discovery.ServiceStateChange.Added)
        self.assertEqual([(r["node_id"], r["role"], r["port"]) for r in seen], [("peer1", "mic-only", 8901)])


def _runtime() -> GatewayRuntime:
    return GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
    )


_CLEAN_MESH_ENV = {
    k: v for k, v in os.environ.items()
    if not k.startswith(("QANTARA_MESH_", "QANTARA_WYOMING_"))
}


class RuntimeMeshConfigTests(unittest.IsolatedAsyncioTestCase):
    async def _start(self, env: dict[str, str]) -> GatewayRuntime:
        runtime = _runtime()
        self.addAsyncCleanup(runtime.close)
        with unittest.mock.patch.dict(os.environ, {**_CLEAN_MESH_ENV, **env}, clear=True):
            await runtime.start_mesh()
        return runtime

    async def test_disabled_spellings_keep_mesh_off(self) -> None:
        for value in ("disabled", "off", "false", "0", "no", "none", "", "  OFF "):
            with self.subTest(value=value):
                runtime = await self._start({"QANTARA_MESH_ROLE": value, "QANTARA_MESH_PORT": "0"})
                self.assertIsNone(runtime.mesh_controller)

    async def test_invalid_role_is_a_config_error(self) -> None:
        for value in ("bogus", "speaker", "fulll", "on", "true"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "QANTARA_MESH_ROLE"):
                    await self._start({"QANTARA_MESH_ROLE": value, "QANTARA_MESH_PORT": "0"})

    async def test_invalid_node_id_is_a_config_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "QANTARA_MESH_NODE_ID"):
            await self._start({
                "QANTARA_MESH_ROLE": "full", "QANTARA_MESH_PORT": "0",
                "QANTARA_MESH_NODE_ID": "<img src=x>",
            })

    async def test_short_mesh_token_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "QANTARA_MESH_TOKEN"):
            await self._start({
                "QANTARA_MESH_ROLE": "full", "QANTARA_MESH_PORT": "0",
                "QANTARA_MESH_TOKEN": "short-token",
            })

    async def test_non_loopback_bind_without_token_is_refused(self) -> None:
        from gateway.mesh import controller as controller_mod

        with unittest.mock.patch.object(controller_mod, "MeshController") as fake:
            for host in ("0.0.0.0", "192.168.50.5", "::"):
                with self.subTest(host=host):
                    with self.assertRaisesRegex(RuntimeError, "QANTARA_MESH_TOKEN"):
                        await self._start({"QANTARA_MESH_ROLE": "full", "QANTARA_MESH_HOST": host})
            fake.assert_not_called()

    async def test_non_loopback_bind_allowed_with_token_or_insecure_opt_in(self) -> None:
        from gateway.mesh import controller as controller_mod

        instance = unittest.mock.MagicMock()
        instance.start = unittest.mock.AsyncMock()
        instance.stop = unittest.mock.AsyncMock()
        for extra in ({"QANTARA_MESH_TOKEN": "t" * 24}, {"QANTARA_MESH_ALLOW_INSECURE": "1"}):
            with self.subTest(extra=list(extra)):
                with unittest.mock.patch.object(controller_mod, "MeshController", return_value=instance) as fake, \
                        unittest.mock.patch("gateway.transport_spike.runtime.LOGGER") as logger:
                    runtime = await self._start({
                        "QANTARA_MESH_ROLE": "full", "QANTARA_MESH_HOST": "0.0.0.0", **extra,
                    })
                    fake.assert_called_once()
                    # The insecure opt-in is loud; a token is silent.
                    self.assertEqual(logger.warning.called, "QANTARA_MESH_ALLOW_INSECURE" in extra)
                    self.assertIs(runtime.mesh_controller, instance)
                    cfg = fake.call_args.args[0]
                    self.assertEqual(cfg.mesh_token, extra.get("QANTARA_MESH_TOKEN"))

    async def test_valid_token_reaches_controller(self) -> None:
        runtime = await self._start({
            "QANTARA_MESH_ROLE": "mic-only", "QANTARA_MESH_PORT": "0",
            "QANTARA_MESH_TOKEN": "m" * 30,
        })
        self.assertIsNotNone(runtime.mesh_controller)
        self.assertEqual(runtime.mesh_controller.config.mesh_token, "m" * 30)
        self.assertEqual(runtime.mesh_controller.config.role, "mic-only")


class WyomingRemovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_module_is_gone(self) -> None:
        self.assertIsNone(importlib.util.find_spec("gateway.mesh.wyoming_bridge"))

    async def test_wyoming_env_is_ignored(self) -> None:
        runtime = _runtime()
        self.addAsyncCleanup(runtime.close)
        self.assertFalse(hasattr(runtime, "wyoming_bridge"))
        env = {**_CLEAN_MESH_ENV, "QANTARA_WYOMING_ENABLED": "true"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("gateway.transport_spike.runtime", level="WARNING") as logs:
                runtime.warn_removed_settings()
        self.assertIn("removed", "\n".join(logs.output))

    async def test_server_imports_without_wyoming_package(self) -> None:
        code = (
            "import sys\n"
            "sys.modules['wyoming'] = None\n"
            "import gateway.transport_spike.server\n"
            "import gateway.mesh.controller\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
