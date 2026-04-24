from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from providers.tts.base import TTSProvider, VoiceSpec


class ChatterboxBackend(Protocol):
    sample_rate: int

    def generate(
        self,
        text: str,
        *,
        exaggeration: float,
        cfg_weight: float,
        voice_prompt_path: str | None,
    ) -> list[int]: ...


@dataclass(frozen=True, kw_only=True)
class ChatterboxVoiceSpec(VoiceSpec):
    voice_prompt_path: str | None = None


def _clamp(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


class ChatterboxTTSProvider(TTSProvider):
    kind = "chatterbox"

    def __init__(
        self,
        backend: ChatterboxBackend | None = None,
        voices_override: list[dict[str, Any]] | None = None,
    ) -> None:
        self._backend = backend
        self._voices: dict[str, ChatterboxVoiceSpec] = {}
        if voices_override is not None:
            for raw in voices_override:
                voice = ChatterboxVoiceSpec(
                    voice_id=raw["voice_id"],
                    label=raw["label"],
                    locale=raw["locale"],
                    sample_rate=raw["sample_rate"],
                    voice_prompt_path=raw.get("voice_prompt_path"),
                    defaults=raw.get("defaults"),
                    allowed_transforms=raw.get("allowed_transforms"),
                )
                self._voices[voice.voice_id] = voice

    @property
    def available(self) -> bool:
        return self._backend is not None and bool(self._voices)

    @property
    def default_voice_id(self) -> str | None:
        return next(iter(self._voices), None)

    def list_available_voices(self) -> list[dict[str, Any]]:
        return [
            {
                "voice_id": voice.voice_id,
                "label": voice.label,
                "locale": voice.locale,
                "sample_rate": voice.sample_rate,
                "defaults": dict(voice.defaults or {}),
                "allowed_transforms": list(voice.allowed_transforms or []),
            }
            for voice in self._voices.values()
        ]

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        requested = voice_id or self.default_voice_id
        if requested and requested in self._voices:
            return self._voices[requested], None
        fallback = next(iter(self._voices.values()), None)
        if fallback is None:
            raise RuntimeError("chatterbox provider has no voices configured")
        return fallback, f"requested voice '{requested}' unavailable; using '{fallback.voice_id}'"

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,  # noqa: ARG002 — chatterbox rate control TBD
        *,
        expressiveness: float | None = None,
    ) -> tuple[list[int], VoiceSpec, str | None]:
        if self._backend is None:
            raise RuntimeError("chatterbox backend not initialised")
        voice, fallback_reason = self.resolve_voice(voice_id)
        if expressiveness is None:
            default_expr = (voice.defaults or {}).get("expressiveness", 0.5)
            effective_expr = float(default_expr)
        else:
            effective_expr = float(expressiveness)
        effective_expr = _clamp(effective_expr, 0.0, 1.0)
        cfg_weight = 0.5
        samples = await asyncio.to_thread(
            self._backend.generate,
            text,
            exaggeration=effective_expr,
            cfg_weight=cfg_weight,
            voice_prompt_path=getattr(voice, "voice_prompt_path", None),
        )
        return samples, voice, fallback_reason
