from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class STTResult:
    """Structured result from a speech-to-text transcribe call.

    Keeps backward-compat with call sites that treat the result as a plain
    string: `str(result)` and iteration over `result.text` both work, and
    `.text` is accessible on instances.
    """

    text: str
    language: str | None = None
    language_probability: float | None = None

    def __str__(self) -> str:
        return self.text

    def __bool__(self) -> bool:
        return bool(self.text)

    def __len__(self) -> int:
        return len(self.text)

    def strip(self) -> str:
        return self.text.strip()


class STTProvider(ABC):
    kind: str = "unknown"

    @property
    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def transcribe(self, samples: list[int], sample_rate: int) -> STTResult:
        raise NotImplementedError

    async def transcribe_partial(self, samples: list[int], sample_rate: int) -> STTResult:
        raise NotImplementedError("this provider does not support partial transcription")

    @property
    def supports_partial(self) -> bool:
        return type(self).transcribe_partial is not STTProvider.transcribe_partial
