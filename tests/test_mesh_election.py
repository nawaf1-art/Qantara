from __future__ import annotations

import unittest

from gateway.mesh.election import ElectionInput, ElectionOutcome, decide_claim


class ElectionTests(unittest.TestCase):
    def test_lone_node_claims(self) -> None:
        outcome = decide_claim(ElectionInput(
            local_node_id="a",
            local_role="full",
            local_rms=0.5,
            session_id="s1",
            peer_rms={},
        ))
        self.assertEqual(outcome, ElectionOutcome(should_claim=True, winner_node_id="a"))

    def test_higher_local_rms_claims(self) -> None:
        outcome = decide_claim(ElectionInput(
            local_node_id="a",
            local_role="full",
            local_rms=0.8,
            session_id="s1",
            peer_rms={"b": 0.4, "c": 0.6},
        ))
        self.assertTrue(outcome.should_claim)
        self.assertEqual(outcome.winner_node_id, "a")

    def test_lower_local_rms_yields(self) -> None:
        outcome = decide_claim(ElectionInput(
            local_node_id="a",
            local_role="full",
            local_rms=0.3,
            session_id="s1",
            peer_rms={"b": 0.9},
        ))
        self.assertFalse(outcome.should_claim)
        self.assertEqual(outcome.winner_node_id, "b")

    def test_tie_breaks_by_lexicographic_node_id(self) -> None:
        # local=b, peer=a, equal RMS — a wins because a < b lexicographically
        outcome = decide_claim(ElectionInput(
            local_node_id="b",
            local_role="full",
            local_rms=0.5,
            session_id="s1",
            peer_rms={"a": 0.5},
        ))
        self.assertFalse(outcome.should_claim)
        self.assertEqual(outcome.winner_node_id, "a")

    def test_mic_only_role_always_yields_when_any_full_peer_exists(self) -> None:
        # a is mic-only; it should defer the response to any full peer regardless of RMS
        outcome = decide_claim(ElectionInput(
            local_node_id="a",
            local_role="mic-only",
            local_rms=0.99,
            session_id="s1",
            peer_rms={"b": 0.1},
            peer_roles={"b": "full"},
        ))
        self.assertFalse(outcome.should_claim)
        self.assertEqual(outcome.winner_node_id, "b")

    def test_mic_only_still_claims_if_no_full_peer(self) -> None:
        # no full peer present — mic-only node has to handle it itself
        outcome = decide_claim(ElectionInput(
            local_node_id="a",
            local_role="mic-only",
            local_rms=0.5,
            session_id="s1",
            peer_rms={"b": 0.4},
            peer_roles={"b": "mic-only"},
        ))
        self.assertTrue(outcome.should_claim)
        self.assertEqual(outcome.winner_node_id, "a")

    def test_speaker_only_peer_is_ignored_as_responder(self) -> None:
        # speaker-only peers can't run STT so they're never election winners
        outcome = decide_claim(ElectionInput(
            local_node_id="a",
            local_role="full",
            local_rms=0.3,
            session_id="s1",
            peer_rms={"b": 0.9},
            peer_roles={"b": "speaker-only"},
        ))
        self.assertTrue(outcome.should_claim)
        self.assertEqual(outcome.winner_node_id, "a")


if __name__ == "__main__":
    unittest.main()
