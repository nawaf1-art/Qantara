from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AdapterConfig:
    kind: str = "mock"
    name: str = "mock"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdapterHealth:
    status: str
    detail: str | None = None
    degraded: bool = False


# Agent protocol v1 activity vocabulary (see protocols/agent.md). Unknown
# types are coerced to "other" so a misbehaving adapter can't invent UI states.
ACTIVITY_TYPES = ("tool_call", "reading_files", "searching", "thinking", "other")

# Serialized tool-call parameters above this size are dropped rather than
# forwarded to the browser; activity events are a glanceable strip, not a log.
MAX_PARAMETERS_JSON_CHARS = 2048
MAX_ACTIVITY_SUMMARY_CHARS = 4096
MAX_TOOL_NAME_CHARS = 256


def _clamp_unit(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def make_activity_event(
    activity_type: str,
    summary: str,
    progress: float | None = None,
    tool_name: str | None = None,
    parameters: dict[str, Any] | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Build a well-formed assistant_activity event for stream_assistant_output.

    Adapters should use this instead of hand-rolling dicts: it enforces the
    protocol-v1 vocabulary, clamps progress/confidence to 0..1, and drops
    malformed or oversized tool-call metadata.
    """
    event: dict[str, Any] = {
        "type": "assistant_activity",
        "activity_type": activity_type if activity_type in ACTIVITY_TYPES else "other",
        "summary": summary[:MAX_ACTIVITY_SUMMARY_CHARS] if isinstance(summary, str) else "",
    }
    clamped_progress = _clamp_unit(progress)
    if clamped_progress is not None:
        event["progress"] = clamped_progress
    if isinstance(tool_name, str) and tool_name:
        event["tool_name"] = tool_name[:MAX_TOOL_NAME_CHARS]
    if isinstance(parameters, dict):
        try:
            if len(json.dumps(parameters)) <= MAX_PARAMETERS_JSON_CHARS:
                event["parameters"] = parameters
        except (TypeError, ValueError):
            pass
    clamped_confidence = _clamp_unit(confidence)
    if clamped_confidence is not None:
        event["confidence"] = clamped_confidence
    return event


class RuntimeAdapter(ABC):
    def __init__(self, config: AdapterConfig | None = None) -> None:
        self.config = config or AdapterConfig()

    @property
    def adapter_kind(self) -> str:
        return self.config.kind

    @abstractmethod
    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def stream_assistant_output(
        self,
        session_handle: str,
        turn_handle: str,
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def check_health(self) -> AdapterHealth:
        raise NotImplementedError
