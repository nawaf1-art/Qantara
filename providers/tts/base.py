from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PiperVoiceSpec:
    voice_id: str
    label: str
    model_path: str
    config_path: str | None
    sample_rate: int
    locale: str = "en-US"


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
    def resolve_voice(self, voice_id: str | None) -> tuple[PiperVoiceSpec, str | None]:
        raise NotImplementedError

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
    ) -> tuple[list[int], PiperVoiceSpec, str | None]:
        raise NotImplementedError
