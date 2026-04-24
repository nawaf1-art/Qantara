from __future__ import annotations

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
