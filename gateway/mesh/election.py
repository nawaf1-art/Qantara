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
    # Empty string when no node is eligible to respond.
    winner_node_id: str


def decide_claim(inp: ElectionInput) -> ElectionOutcome:
    """Pure function: given this node's view of the current election
    window, decide whether to claim the turn or yield, and who the
    winner is.

    Every node applies the same rules to the same candidate set, so every
    node that saw the same RMS values computes the same winner:

    1. Only "full" and "mic-only" nodes are candidates. "speaker-only"
       (and any unknown role) never wins -- not even when it is alone, in
       which case nobody claims. A peer without a known role is treated as
       "full", matching the mDNS default.
    2. If any "full" candidate exists, every "mic-only" candidate is
       dropped -- on every node, so a mic-only phone and a full desktop
       cannot each yield to the other.
    3. Highest RMS wins; ties break by the lexicographically smallest
       full node_id string.
    """
    candidates: dict[str, tuple[float, str]] = {}
    if inp.local_role in ROLES_THAT_CAN_RESPOND:
        candidates[inp.local_node_id] = (inp.local_rms, inp.local_role)
    for node_id, rms in inp.peer_rms.items():
        if node_id == inp.local_node_id:
            continue
        role = inp.peer_roles.get(node_id, "full")
        if role in ROLES_THAT_CAN_RESPOND:
            candidates[node_id] = (rms, role)

    if any(role == "full" for _rms, role in candidates.values()):
        candidates = {n: v for n, v in candidates.items() if v[1] == "full"}

    if not candidates:
        return ElectionOutcome(should_claim=False, winner_node_id="")

    winner = min(candidates.items(), key=lambda kv: (-kv[1][0], kv[0]))[0]
    return ElectionOutcome(
        should_claim=(winner == inp.local_node_id),
        winner_node_id=winner,
    )
