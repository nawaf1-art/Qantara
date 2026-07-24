"""Tests for discovery/scanner.py — the LAN backend scanner reachable via
/api/discovery/scan. Pins the "never scans public IPs" RFC-1918 safety
invariant (previously untested) and the fingerprint/port parsing helpers."""

from __future__ import annotations

import ipaddress
import unittest

from discovery.scanner import (
    KNOWN_PORTS,
    DiscoveredBackend,
    DiscoveredModel,
    _extract_ollama_models,
    _extract_openai_models,
    get_local_ip,
    get_subnet_hosts,
    is_private_ip,
    serialize_backend,
)


class IsPrivateIpTests(unittest.TestCase):
    def test_rfc1918_ranges_are_private(self) -> None:
        for ip in ("10.0.0.1", "10.255.255.254", "172.16.0.1", "172.31.255.254", "192.168.0.1", "192.168.1.50"):
            self.assertTrue(is_private_ip(ip), ip)

    def test_public_and_boundary_ips_are_not_private(self) -> None:
        # 172.15/172.32 sit just outside the 172.16/12 block; cloud-metadata and
        # loopback must also be classified non-private by this helper.
        for ip in ("8.8.8.8", "1.1.1.1", "172.15.255.255", "172.32.0.1", "169.254.169.254", "127.0.0.1", "0.0.0.0"):
            self.assertFalse(is_private_ip(ip), ip)

    def test_garbage_is_not_private(self) -> None:
        for ip in ("not-an-ip", "", "999.1.1.1", "192.168.1"):
            self.assertFalse(is_private_ip(ip), ip)


class SubnetSafetyInvariantTests(unittest.TestCase):
    def test_subnet_of_private_ip_is_254_usable_hosts(self) -> None:
        hosts = get_subnet_hosts("192.168.1.50")
        self.assertEqual(len(hosts), 254)
        self.assertIn("192.168.1.1", hosts)
        self.assertIn("192.168.1.254", hosts)
        self.assertNotIn("192.168.1.0", hosts)    # network address excluded
        self.assertNotIn("192.168.1.255", hosts)  # broadcast excluded

    def test_subnet_never_yields_globally_routable_hosts(self) -> None:
        # The scanner's core safety promise (module docstring): "Never scans
        # public IPs." get_local_ip only ever returns a private or loopback
        # address, so every host the scanner would probe must be non-global.
        for local_ip in ("10.1.2.3", "172.20.5.5", "192.168.0.10", "127.0.0.1"):
            for host in get_subnet_hosts(local_ip):
                self.assertFalse(
                    ipaddress.ip_address(host).is_global,
                    f"scanner would probe public IP {host} derived from local {local_ip}",
                )

    def test_get_local_ip_is_never_public(self) -> None:
        # By construction get_local_ip returns a private IP or the 127.0.0.1
        # fallback — never a globally routable address handed to scan_lan.
        ip = get_local_ip()
        self.assertIsNotNone(ip)
        self.assertFalse(ipaddress.ip_address(ip).is_global, f"get_local_ip returned public address {ip}")

    def test_invalid_local_ip_yields_no_hosts(self) -> None:
        self.assertEqual(get_subnet_hosts("not-an-ip"), [])


class FingerprintParsingTests(unittest.TestCase):
    def test_known_ports_map_expected_types(self) -> None:
        self.assertEqual(KNOWN_PORTS[11434], "ollama")
        self.assertEqual(KNOWN_PORTS[1234], "lmstudio")
        self.assertEqual(KNOWN_PORTS[18789], "openclaw")

    def test_extract_ollama_models(self) -> None:
        body = {"models": [
            {"name": "qwen2.5:3b", "size": 2 * 1024 ** 3, "details": {"parameter_size": "3B", "family": "qwen2"}},
            {"name": ""},  # nameless entry is skipped
        ]}
        models = _extract_ollama_models(body)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "qwen2.5:3b")
        self.assertEqual(models[0].size_gb, 2.0)
        self.assertEqual(models[0].param_size, "3B")

    def test_extract_ollama_models_handles_garbage(self) -> None:
        self.assertEqual(_extract_ollama_models(None), [])
        self.assertEqual(_extract_ollama_models("nope"), [])

    def test_extract_ollama_models_accepts_current_model_field(self) -> None:
        body = {"models": [{"model": "qwen3.5:2b", "size": 123}]}
        self.assertEqual(_extract_ollama_models(body)[0].name, "qwen3.5:2b")

    def test_extract_openai_models_skips_idless_entries(self) -> None:
        body = {"data": [{"id": "gpt-x"}, {"id": ""}, {"nomodel": 1}]}
        self.assertEqual([m.name for m in _extract_openai_models(body)], ["gpt-x"])

    def test_serialize_backend_is_json_safe(self) -> None:
        backend = DiscoveredBackend(
            server_type="ollama", url="http://192.168.1.5:11434", ip="192.168.1.5", port=11434,
            models=[DiscoveredModel(name="m")],
        )
        serialized = serialize_backend(backend)
        self.assertEqual(serialized["models"][0]["name"], "m")
        self.assertEqual(serialized["server_type"], "ollama")


if __name__ == "__main__":
    unittest.main()
