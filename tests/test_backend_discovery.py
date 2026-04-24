from __future__ import annotations

import unittest

from gateway.transport_spike.http_api import _assemble_backends


class BackendDiscoveryTests(unittest.TestCase):
    def test_openclaw_is_hidden_when_not_healthy(self) -> None:
        backends = _assemble_backends(
            {"available": False},
            {"available": False, "installed": True, "gateway_running": False, "agents": []},
            {"available": False},
        )

        self.assertNotIn("openclaw", [backend["type"] for backend in backends])
        self.assertEqual(backends[0]["type"], "openai_compatible")

    def test_healthy_openclaw_is_advanced_optional(self) -> None:
        backends = _assemble_backends(
            {"available": False},
            {
                "available": True,
                "installed": True,
                "gateway_running": True,
                "agents": [{"id": "main", "name": "Main", "default": True}],
            },
            {"available": False},
        )

        openclaw = next(backend for backend in backends if backend["type"] == "openclaw")
        self.assertTrue(openclaw["available"])
        self.assertTrue(openclaw["advanced"])
        self.assertTrue(openclaw["optional"])
        self.assertEqual(openclaw["agents"][0]["id"], "main")


if __name__ == "__main__":
    unittest.main()
