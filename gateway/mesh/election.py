from __future__ import annotations

from dataclasses import dataclass, field

ROLES_THAT_CAN_RESPOND = {"full", "mic-only"}


@dataclass(slots=True, frozen=True)
class ElectionInput:
    local_node_id: str
    local_role: str
    local_rms: float
    session_id: str
    peer_rms: dict[str, float]
    peer_roles: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ElectionOutcome:
    should_claim: bool
    winner_node_id: str


def decide_claim(inp: ElectionInput) -> ElectionOutcome:
    """Pure function: given this node's view of the current election
    window, decide whether to claim the turn or yield, and who the
    winner is.

    Rules:
    1. A candidate must have a role that can run the full STT→adapter→TTS
       pipeline. "speaker-only" peers are excluded from the winner pool.
    2. "mic-only" nodes always yield if any "full" peer is present — a
       phone with a mic shouldn't try to speak the reply when a desktop
       could do it.
    3. Otherwise, highest RMS wins.
    4. Ties break by lexicographic node_id (deterministic across nodes).
    """
    candidates: dict[str, float] = {}
    if inp.local_role in ROLES_THAT_CAN_RESPOND:
        candidates[inp.local_node_id] = inp.local_rms
    for node_id, rms in inp.peer_rms.items():
        role = inp.peer_roles.get(node_id, "full")
        if role in ROLES_THAT_CAN_RESPOND:
            candidates[node_id] = rms

    if not candidates:
        # Degenerate case — no eligible responders. Local wins by default
        # so a turn still gets attempted (better than silent no-op).
        return ElectionOutcome(should_claim=True, winner_node_id=inp.local_node_id)

    # mic-only + any full peer => always yield
    if inp.local_role == "mic-only":
        full_peers = {
            n: rms for n, rms in inp.peer_rms.items()
            if inp.peer_roles.get(n, "full") == "full"
        }
        if full_peers:
            winner = max(full_peers.items(), key=lambda kv: (kv[1], -_lex(kv[0])))[0]
            return ElectionOutcome(should_claim=False, winner_node_id=winner)

    # Sort: highest RMS first, then lexicographically smallest node_id on ties
    winner = min(
        candidates.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )[0]
    return ElectionOutcome(
        should_claim=(winner == inp.local_node_id),
        winner_node_id=winner,
    )


def _lex(node_id: str) -> int:
    # Negation helper so we can use max() uniformly; smaller strings should win ties.
    # Returns a stable integer from the string so max picks the lex-smallest.
    return sum(b << (8 * i) for i, b in enumerate(node_id.encode("utf-8")[:8]))
