from __future__ import annotations

import unittest
from unittest.mock import patch

from gateway.transport_spike.http_api import _safe_outbound_url, is_safe_url


class UrlSafetyTests(unittest.TestCase):
    """Direct unit tests for the gateway's primary network-security boundary.

    The /api/configure, /api/test-url and /api/test-mcp handlers all gate
    outbound requests through is_safe_url(); a regression here silently turns
    the gateway into an SSRF proxy, so the guard deserves explicit coverage.
    """

    def test_allows_loopback_and_rfc1918(self) -> None:
        self.assertTrue(is_safe_url("http://127.0.0.1:11434"))
        self.assertTrue(is_safe_url("http://192.168.1.10:8080"))
        self.assertTrue(is_safe_url("http://10.0.0.5"))
        self.assertTrue(is_safe_url("http://172.16.3.4:1234"))
        self.assertTrue(is_safe_url("http://[::1]:8000"))

    def test_rejects_public(self) -> None:
        self.assertFalse(is_safe_url("http://8.8.8.8"))
        self.assertFalse(is_safe_url("https://example.com"))

    def test_rejects_embedded_credentials(self) -> None:
        self.assertFalse(is_safe_url("http://user:password@127.0.0.1:11434"))
        self.assertFalse(is_safe_url("http://token@192.168.1.10:8080"))

    def test_rejects_link_local_cloud_metadata(self) -> None:
        # 169.254.169.254 is the cloud instance-metadata endpoint. Python's
        # ipaddress reports is_private == True for the whole 169.254.0.0/16
        # link-local range, so the guard must reject it explicitly or it leaks
        # IAM credentials on any VPS deployment.
        self.assertFalse(is_safe_url("http://169.254.169.254"))
        self.assertFalse(is_safe_url("http://169.254.1.1:80"))

    def test_rejects_unspecified(self) -> None:
        # 0.0.0.0 / :: are is_private == True but route to localhost on Linux.
        self.assertFalse(is_safe_url("http://0.0.0.0:8080"))
        self.assertFalse(is_safe_url("http://[::]:8080"))

    def test_rejects_ipv4_mapped_link_local(self) -> None:
        # ::ffff:169.254.169.254 must not smuggle the metadata IP past the guard.
        self.assertFalse(is_safe_url("http://[::ffff:169.254.169.254]"))

    def test_rejects_ipv6_link_local(self) -> None:
        self.assertFalse(is_safe_url("http://[fe80::1]"))

    def test_hostname_pin_prefers_private_ipv4_for_dual_stack_backends(self) -> None:
        addresses = [
            (10, 1, 6, "", ("::1", 11434, 0, 0)),
            (2, 1, 6, "", ("127.0.0.1", 11434)),
        ]
        with patch(
            "gateway.transport_spike.http_api._sock.getaddrinfo",
            return_value=addresses,
        ):
            target = _safe_outbound_url("http://localhost:11434")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.url, "http://127.0.0.1:11434")
        self.assertEqual(target.host_header, "localhost:11434")
        self.assertEqual(target.server_hostname, "localhost")


if __name__ == "__main__":
    unittest.main()
