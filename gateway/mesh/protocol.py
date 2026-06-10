from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass, field
from typing import Any

# Inbound mesh frames come from untrusted LAN peers; bound identifier lengths
# and RMS magnitude so a hostile peer can't poison elections or exhaust memory.
_MAX_ID_LEN = 256
_MAX_RMS = 1e6


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


def _frame_signature(frame: dict[str, Any], token: str) -> str:
    payload = json.dumps(frame, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(token.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign_frame(frame: dict[str, Any], token: str) -> dict[str, Any]:
    """Return a copy of the frame carrying an HMAC-SHA256 signature over
    its canonical JSON form, keyed by the shared mesh token."""
    return {**frame, "sig": _frame_signature(frame, token)}


def verify_frame(frame: dict[str, Any], token: str) -> dict[str, Any]:
    """Verify a signed frame and return it without the signature field.
    Raises ValueError for missing, malformed, or mismatched signatures so
    the transport drops the frame."""
    signature = frame.get("sig")
    if not isinstance(signature, str):
        raise ValueError("missing mesh auth signature")
    unsigned = {k: v for k, v in frame.items() if k != "sig"}
    expected = _frame_signature(unsigned, token)
    if not hmac.compare_digest(expected, signature):
        raise ValueError("bad mesh auth signature")
    return unsigned


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
        msg = cls(**fields)
    except TypeError as exc:
        raise ValueError(f"malformed {msg_type} message: {exc}") from exc
    _validate_message(msg)
    return msg


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_message(msg: MeshMessage) -> None:
    """Reject malformed/abusive field values from untrusted peers.

    Dataclasses don't type-check at runtime, and json.loads accepts NaN/Infinity,
    so without this a peer could send a string/NaN/negative RMS (to rig an
    election) or a multi-megabyte node_id. Raises ValueError so the transport
    layer drops the frame.
    """
    for attr in ("node_id", "session_id", "role", "winner_node_id"):
        value = getattr(msg, attr, None)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > _MAX_ID_LEN:
            raise ValueError(f"invalid {attr}")
    if not getattr(msg, "node_id", ""):
        raise ValueError("missing node_id")
    rms = getattr(msg, "rms", None)
    if rms is not None and (not _is_finite_number(rms) or rms < 0 or rms > _MAX_RMS):
        raise ValueError("invalid rms")
    monotonic_ms = getattr(msg, "monotonic_ms", None)
    if monotonic_ms is not None and not _is_finite_number(monotonic_ms):
        raise ValueError("invalid monotonic_ms")
    capabilities = getattr(msg, "capabilities", None)
    if capabilities is not None and not isinstance(capabilities, dict):
        raise ValueError("invalid capabilities")
