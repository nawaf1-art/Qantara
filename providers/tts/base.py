from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceSpec:
    voice_id: str
    label: str
    sample_rate: int
    locale: str
    defaults: dict[str, float | int | str] | None = None
    allowed_transforms: list[str] | None = None


class TTSProvider(ABC):
    kind: str = "unknown"

    @property
    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def default_voice_id(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def list_available_voices(self) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        raise NotImplementedError

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
        *,
        expressiveness: float | None = None,
    ) -> tuple[list[int], VoiceSpec, str | None]:
        raise NotImplementedError
