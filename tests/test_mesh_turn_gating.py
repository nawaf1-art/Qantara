from __future__ import annotations

import unittest
import unittest.mock

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime, Session
from gateway.transport_spike.speech import maybe_run_election_and_claim
from tests.test_transport_spike import DummyWebSocket, FakeSTT, FakeTTS


class TurnGatingTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_mesh_always_claims(self) -> None:
        runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
        )
        ws = DummyWebSocket()
        session = Session(ws, runtime)
        runtime.register_session(session)
        # No mesh controller configured
        should_claim = await maybe_run_election_and_claim(session, local_rms=0.5)
        self.assertTrue(should_claim)

    async def test_mesh_claim_propagates_outcome(self) -> None:
        """With a MeshController present, the session asks it to run the
        election; the outcome bubbles back up."""
        runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(), tts=FakeTTS(), event_sink=lambda r: None,
        )
        # Stub the mesh controller with a mock that returns a known outcome.
        # Registry is a synchronous Mock so list_peers() returns a real list;
        # run_election is an AsyncMock returning a known outcome.
        fake_controller = unittest.mock.MagicMock()
        fake_controller.registry.list_peers.return_value = []

        class _Outcome:
            should_claim = False
            winner_node_id = "other"

        fake_controller.run_election = unittest.mock.AsyncMock(return_value=_Outcome())
        runtime.mesh_controller = fake_controller

        ws = DummyWebSocket()
        session = Session(ws, runtime)
        runtime.register_session(session)
        should_claim = await maybe_run_election_and_claim(session, local_rms=0.5)
        self.assertFalse(should_claim)
        fake_controller.run_election.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
