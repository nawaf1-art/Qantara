"""Audit 2026-09-24 S-d (async DNS resolution) and HS-12 (SSRF allowlist).

DNS is always stubbed; no real hostname is resolved.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import time
import unittest
from unittest.mock import patch

from gateway.transport_spike import http_api
from gateway.transport_spike.http_api import _is_lan_ip, _safe_outbound_url, is_safe_url


def _ip(value: str):
    return ipaddress.ip_address(value)


class SsrfPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"QANTARA_ALLOW_CGNAT": ""})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_explicit_private_allowlist(self) -> None:
        for value in (
            "10.1.2.3",
            "172.16.0.1",
            "172.31.255.254",
            "192.168.50.2",
            "127.0.0.1",
            "127.8.9.10",
            "::1",
            "fc00::1",
            "fd12:3456:789a::1",
            "::ffff:192.168.1.10",
        ):
            with self.subTest(value=value):
                self.assertTrue(_is_lan_ip(_ip(value)))

    def test_denied_ranges(self) -> None:
        for value in (
            "169.254.169.254",
            "169.254.0.1",
            "fe80::1",
            "fd00:ec2::254",
            "2002:a9fe:a9fe::1",
            "2002:c0a8:0101::1",
            "::ffff:169.254.169.254",
            "0.0.0.0",
            "::",
            "224.0.0.1",
            "ff02::1",
            "8.8.8.8",
            "2001:4860:4860::8888",
            "64:ff9b::a9fe:a9fe",
            "198.18.0.1",
            "192.0.0.1",
        ):
            with self.subTest(value=value):
                self.assertFalse(_is_lan_ip(_ip(value)))

    def test_cgnat_requires_opt_in(self) -> None:
        tailscale = _ip("100.101.102.103")
        self.assertFalse(_is_lan_ip(tailscale))
        with patch.dict(os.environ, {"QANTARA_ALLOW_CGNAT": "1"}):
            self.assertTrue(_is_lan_ip(tailscale))
            self.assertFalse(_is_lan_ip(_ip("100.128.0.1")))


class AsyncResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_is_safe_url_is_async(self) -> None:
        self.assertTrue(await is_safe_url("http://127.0.0.1:11434"))
        self.assertFalse(await is_safe_url("http://[fd00:ec2::254]"))

    async def test_resolution_does_not_block_the_event_loop(self) -> None:
        def slow_getaddrinfo(*_args, **_kwargs):
            time.sleep(0.3)
            return [(2, 1, 6, "", ("192.168.1.50", 8080))]

        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        try:
            with patch.object(http_api._sock, "getaddrinfo", side_effect=slow_getaddrinfo):
                target = await _safe_outbound_url("http://printer.local:8080")
        finally:
            task.cancel()
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.url, "http://192.168.1.50:8080")
        self.assertGreater(ticks, 5, "event loop stalled during DNS resolution")

    async def test_resolution_times_out(self) -> None:
        def hanging_getaddrinfo(*_args, **_kwargs):
            time.sleep(0.4)
            return [(2, 1, 6, "", ("192.168.1.50", 8080))]

        started = time.monotonic()
        with patch.object(http_api, "_DNS_RESOLVE_TIMEOUT_S", 0.05), patch.object(
            http_api._sock, "getaddrinfo", side_effect=hanging_getaddrinfo
        ):
            target = await _safe_outbound_url("http://slow.local:8080")
        self.assertIsNone(target)
        self.assertLess(time.monotonic() - started, 0.35)

    async def test_hostname_resolving_to_metadata_is_rejected(self) -> None:
        with patch.object(
            http_api._sock,
            "getaddrinfo",
            return_value=[(10, 1, 6, "", ("fd00:ec2::254", 80, 0, 0))],
        ):
            self.assertIsNone(await _safe_outbound_url("http://metadata.local"))


if __name__ == "__main__":
    unittest.main()
