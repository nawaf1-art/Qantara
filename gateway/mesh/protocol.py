from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Hello:
    """Sent by a node when it opens a new peer TCP connection. Publishes
    the node's identity, role, and capability summary so the receiving
    node can update its peer registry."""

    node_id: str
    role: str
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "hello",
            "node_id": self.node_id,
            "role": self.role,
            "capabilities": self.capabilities,
        }


@dataclass(slots=True)
class Goodbye:
    """Graceful disconnect. Peers remove the node from their registry."""

    node_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": "goodbye", "node_id": self.node_id}


@dataclass(slots=True)
class RmsUpdate:
    """Broadcast on VAD speech_start_detected. Carries the node's
    current audio RMS so peers can decide whether to defer."""

    node_id: str
    rms: float
    session_id: str
    monotonic_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "rms_update",
            "node_id": self.node_id,
            "rms": self.rms,
            "session_id": self.session_id,
            "monotonic_ms": self.monotonic_ms,
        }


@dataclass(slots=True)
class TurnClaim:
    """Sent by the node that has decided to claim the spoken turn after
    the election race window closes. Other nodes must mute themselves
    for this session."""

    node_id: str
    session_id: str
    rms: float
    monotonic_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "turn_claim",
            "node_id": self.node_id,
            "session_id": self.session_id,
            "rms": self.rms,
            "monotonic_ms": self.monotonic_ms,
        }


@dataclass(slots=True)
class TurnYield:
    """Sent by a node that heard the same speech start but lost the
    election. Acknowledges the winner; useful for telemetry and the
    setup-page peer panel."""

    node_id: str
    session_id: str
    winner_node_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "turn_yield",
            "node_id": self.node_id,
            "session_id": self.session_id,
            "winner_node_id": self.winner_node_id,
        }


MeshMessage = Hello | Goodbye | RmsUpdate | TurnClaim | TurnYield


_DECODERS: dict[str, type] = {
    "hello": Hello,
    "goodbye": Goodbye,
    "rms_update": RmsUpdate,
    "turn_claim": TurnClaim,
    "turn_yield": TurnYield,
}


def decode_message(raw: dict[str, Any]) -> MeshMessage:
    """Turn a plain dict (from JSON) into the matching dataclass. Raises
    ValueError on unknown or malformed types — caller should log and
    drop the offending frame, not crash the connection."""
    msg_type = raw.get("type")
    if msg_type not in _DECODERS:
        raise ValueError(f"unknown mesh message type: {msg_type!r}")
    cls = _DECODERS[msg_type]
    fields = {k: v for k, v in raw.items() if k != "type"}
    try:
        return cls(**fields)
    except TypeError as exc:
        raise ValueError(f"malformed {msg_type} message: {exc}") from exc
