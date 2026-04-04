from __future__ import annotations

from abc import ABC, abstractmethod


class STTProvider(ABC):
    kind: str = "unknown"

    @property
    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def transcribe(self, samples: list[int], sample_rate: int) -> str:
        raise NotImplementedError
