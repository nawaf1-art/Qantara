from __future__ import annotations

import unittest


class MeshDependencyImportTests(unittest.TestCase):
    def test_wyoming_importable(self) -> None:
        import wyoming  # noqa: F401
        from wyoming.event import Event  # noqa: F401
        from wyoming.info import Info, Satellite  # noqa: F401
        from wyoming.server import AsyncEventHandler, AsyncServer  # noqa: F401

    def test_zeroconf_async_importable(self) -> None:
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf  # noqa: F401


class MeshMessageTests(unittest.TestCase):
    def test_rms_update_round_trips_to_dict_and_back(self) -> None:
        from gateway.mesh.protocol import RmsUpdate, decode_message

        msg = RmsUpdate(node_id="node-a", rms=0.82, session_id="s-1", monotonic_ms=1234.5)
        d = msg.to_dict()
        self.assertEqual(d["type"], "rms_update")
        self.assertEqual(d["node_id"], "node-a")
        self.assertAlmostEqual(d["rms"], 0.82)

        decoded = decode_message(d)
        self.assertIsInstance(decoded, RmsUpdate)
        self.assertEqual(decoded.node_id, "node-a")
        self.assertAlmostEqual(decoded.rms, 0.82)
        self.assertEqual(decoded.session_id, "s-1")

    def test_turn_claim_round_trip(self) -> None:
        from gateway.mesh.protocol import TurnClaim, decode_message

        msg = TurnClaim(node_id="node-a", session_id="s-1", rms=0.82, monotonic_ms=1234.5)
        d = msg.to_dict()
        self.assertEqual(d["type"], "turn_claim")

        decoded = decode_message(d)
        self.assertIsInstance(decoded, TurnClaim)
        self.assertEqual(decoded.node_id, "node-a")

    def test_turn_yield_round_trip(self) -> None:
        from gateway.mesh.protocol import TurnYield, decode_message

        msg = TurnYield(node_id="node-b", session_id="s-1", winner_node_id="node-a")
        d = msg.to_dict()
        self.assertEqual(d["type"], "turn_yield")
        decoded = decode_message(d)
        self.assertIsInstance(decoded, TurnYield)
        self.assertEqual(decoded.winner_node_id, "node-a")

    def test_hello_and_goodbye_round_trip(self) -> None:
        from gateway.mesh.protocol import Goodbye, Hello, decode_message

        hello = Hello(node_id="node-a", role="full", capabilities={"stt": True, "tts": True})
        self.assertEqual(hello.to_dict()["type"], "hello")
        self.assertIsInstance(decode_message(hello.to_dict()), Hello)

        bye = Goodbye(node_id="node-a")
        self.assertEqual(bye.to_dict()["type"], "goodbye")
        self.assertIsInstance(decode_message(bye.to_dict()), Goodbye)

    def test_decode_rejects_unknown_type(self) -> None:
        from gateway.mesh.protocol import decode_message

        with self.assertRaises(ValueError):
            decode_message({"type": "ping_of_death"})


if __name__ == "__main__":
    unittest.main()
