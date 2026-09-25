"""Regression tests for the 2026-09-24 audit LAN scanner findings (M-b:
ME-8, ME-9). Hermetic: only loopback aiohttp servers on port 0; the LAN
address and interface netmask lookups are mocked."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import unittest
import unittest.mock

from aiohttp import web

import discovery.scanner as sc
from discovery import netinfo


async def _serve(app: web.Application):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]


class LocalAddressTests(unittest.TestCase):
    def test_source_address_trick_beats_debian_hostname_mapping(self) -> None:
        # Debian/Ubuntu map the hostname to 127.0.1.1; the scan must still
        # find the LAN address.
        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.1.1", 0))]
        with unittest.mock.patch.object(sc.socket, "getaddrinfo", return_value=fake_infos), \
                unittest.mock.patch.object(sc, "resolve_source_ipv4", return_value="192.168.68.20"):
            self.assertEqual(sc.get_local_ip(), "192.168.68.20")

    def test_public_source_address_is_never_used(self) -> None:
        with unittest.mock.patch.object(sc, "resolve_source_ipv4", return_value="203.0.113.10"), \
                unittest.mock.patch.object(sc.socket, "getaddrinfo", return_value=[]):
            ip = sc.get_local_ip()
        self.assertFalse(ipaddress.ip_address(ip).is_global)
        self.assertEqual(ip, "127.0.0.1")

    def test_resolve_source_ipv4_uses_udp_connect_without_sending(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.getsockname.return_value = ("10.1.2.3", 40000)
        with unittest.mock.patch.object(netinfo.socket, "socket", return_value=fake):
            self.assertEqual(netinfo.resolve_source_ipv4(), "10.1.2.3")
        fake.connect.assert_called_once()
        fake.send.assert_not_called()
        fake.sendto.assert_not_called()
        fake.close.assert_called_once()

    def test_resolve_source_ipv4_returns_none_on_error(self) -> None:
        with unittest.mock.patch.object(netinfo.socket, "socket", side_effect=OSError("no network")):
            self.assertIsNone(netinfo.resolve_source_ipv4())


class SubnetSelectionTests(unittest.TestCase):
    def test_wide_prefix_is_capped_at_24(self) -> None:
        hosts = sc.get_subnet_hosts("192.168.68.20", prefixlen=22)
        self.assertEqual(len(hosts), 254)
        self.assertEqual(hosts[0], "192.168.68.1")
        self.assertEqual(hosts[-1], "192.168.68.254")

    def test_narrow_prefix_is_respected(self) -> None:
        hosts = sc.get_subnet_hosts("192.168.1.70", prefixlen=26)
        self.assertEqual(len(hosts), 62)
        self.assertEqual(hosts[0], "192.168.1.65")

    def test_unknown_prefix_defaults_to_24(self) -> None:
        self.assertEqual(len(sc.get_subnet_hosts("10.0.5.9", prefixlen=None)), 254)

    def test_loopback_fallback_scans_only_localhost(self) -> None:
        self.assertEqual(sc.get_subnet_hosts("127.0.0.1"), ["127.0.0.1"])
        self.assertEqual(sc.get_subnet_hosts("127.0.1.1"), ["127.0.0.1"])

    def test_public_address_is_never_scanned(self) -> None:
        for ip in ("8.8.8.8", "203.0.113.10", "169.254.169.254", "100.64.0.1"):
            for prefixlen in (None, 16, 24, 30):
                self.assertEqual(sc.get_subnet_hosts(ip, prefixlen=prefixlen), [], (ip, prefixlen))

    def test_every_scanned_host_is_private_or_loopback(self) -> None:
        for ip in ("10.1.2.3", "172.20.5.5", "192.168.0.10", "127.0.0.1"):
            for prefixlen in (None, 8, 16, 22, 24, 28):
                for host in sc.get_subnet_hosts(ip, prefixlen=prefixlen):
                    addr = ipaddress.ip_address(host)
                    self.assertTrue(sc.is_private_ip(host) or addr.is_loopback, host)


class FingerprintTypeGuardTests(unittest.TestCase):
    def test_ollama_helper_survives_odd_shapes(self) -> None:
        for body in (
            {"models": [{"name": "m", "details": "x"}]},
            {"models": [{"name": "m", "size": "12"}]},
            {"models": "nope"},
            {"models": [{"name": 5}]},
            {"models": [{"name": "m", "size": float("nan")}]},
        ):
            with self.subTest(body=body):
                sc._extract_ollama_models(body)
        models = sc._extract_ollama_models({"models": [{"name": "m", "details": "x", "size": "12"}]})
        self.assertEqual([m.name for m in models], ["m"])
        self.assertIsNone(models[0].size_gb)

    def test_openai_helper_survives_odd_shapes(self) -> None:
        for body in ({"data": "abc"}, {"data": ["x", 1, None]}, {"data": [{"id": 5}]}, {"data": None}):
            with self.subTest(body=body):
                self.assertEqual(sc._extract_openai_models(body), [])


class ScanLanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        patches = [
            unittest.mock.patch.object(sc, "get_local_ip", return_value="127.0.0.1"),
            unittest.mock.patch.object(sc, "get_local_prefixlen", return_value=None),
            unittest.mock.patch.object(sc, "get_subnet_hosts", return_value=["127.0.0.1"]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_one_odd_device_does_not_abort_the_scan(self) -> None:
        def reply(body):
            async def handler(_request):
                return web.json_response(body)
            return handler

        weird = web.Application()
        weird.router.add_get("/v1/models", reply({"data": ["not-an-object"]}))
        weird.router.add_get("/api/v0/models", reply({"data": "abc"}))
        weird_ps = web.Application()
        weird_ps.router.add_get("/api/tags", reply({"models": [{"name": "m", "details": "x"}]}))
        weird_ps.router.add_get("/api/ps", reply({"models": ["x"]}))
        weird_ps.router.add_get("/api/version", reply({"version": 7}))

        async def tags(_r):
            await asyncio.sleep(0.2)
            return web.json_response({"models": [{"name": "qwen3:4b"}]})

        good = web.Application()
        good.router.add_get("/api/tags", tags)
        runners = []
        ports = {}
        for name, app in (("weird", weird), ("weird_ps", weird_ps), ("good", good)):
            runner, port = await _serve(app)
            runners.append(runner)
            ports[name] = port
        try:
            with unittest.mock.patch.object(sc, "KNOWN_PORTS", {
                ports["weird"]: "generic", ports["weird_ps"]: "ollama", ports["good"]: "ollama",
            }):
                events: list[str] = []

                async def cb(kind, _data):
                    events.append(kind)

                results = await sc.scan_lan(progress_callback=cb)
        finally:
            for runner in runners:
                await runner.cleanup()
        found = {(b.server_type, b.port) for b in results}
        self.assertIn(("ollama", ports["good"]), found)
        self.assertIn("done", events)
        self.assertNotIn("error", events)

    async def test_per_host_exception_is_contained(self) -> None:
        async def always_open(_host, _port):
            return True

        calls = {"n": 0}

        async def flaky(session, ip, port, local_ip):
            calls["n"] += 1
            if port == 1111:
                raise RuntimeError("fingerprint bug")
            return sc.DiscoveredBackend(server_type="ollama", url=f"http://{ip}:{port}", ip=ip, port=port)

        with unittest.mock.patch.object(sc, "KNOWN_PORTS", {1111: "generic", 2222: "ollama"}), \
                unittest.mock.patch.object(sc, "tcp_probe", always_open), \
                unittest.mock.patch.object(sc, "fingerprint_host", flaky):
            results = await sc.scan_lan()
        self.assertEqual([b.port for b in results], [2222])
        self.assertEqual(calls["n"], 2)

    async def test_progress_is_emitted_once_per_step(self) -> None:
        async def closed(_host, _port):
            return False

        percents: list[int] = []

        async def cb(kind, data):
            if kind == "progress" and "percent" in data:
                percents.append(data["percent"])

        hosts = [f"127.0.0.{i}" for i in range(1, 51)]
        with unittest.mock.patch.object(sc, "get_subnet_hosts", return_value=hosts), \
                unittest.mock.patch.object(sc, "KNOWN_PORTS", {1: "a", 2: "b", 3: "c", 4: "d"}), \
                unittest.mock.patch.object(sc, "tcp_probe", closed):
            await sc.scan_lan(progress_callback=cb)
        self.assertEqual(percents, sorted(set(percents)))
        self.assertLessEqual(len(percents), 11)
        self.assertEqual(percents[-1], 100)

    async def test_scan_is_single_flight(self) -> None:
        release = asyncio.Event()

        async def slow(_host, _port):
            await release.wait()
            return False

        second_events: list[tuple[str, dict]] = []

        async def cb2(kind, data):
            second_events.append((kind, data))

        with unittest.mock.patch.object(sc, "KNOWN_PORTS", {1: "a"}), \
                unittest.mock.patch.object(sc, "tcp_probe", slow):
            first = asyncio.create_task(sc.scan_lan())
            await asyncio.sleep(0.05)
            second = await asyncio.wait_for(sc.scan_lan(progress_callback=cb2), 1.0)
            release.set()
            await asyncio.wait_for(first, 2.0)
            self.assertEqual(second, [])
            self.assertEqual(second_events[0][0], "error")
            self.assertIn("already", second_events[0][1]["message"])
            # After the first scan finishes a new one may start.
            release.set()
            await asyncio.wait_for(sc.scan_lan(), 2.0)


if __name__ == "__main__":
    unittest.main()
