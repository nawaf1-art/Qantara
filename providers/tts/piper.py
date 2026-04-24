from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

from providers.tts.base import TTSProvider, VoiceSpec
from providers.voice_registry import (
    default_registry_path,
    filter_registry_voices,
)


@dataclass(frozen=True, kw_only=True)
class PiperVoiceSpec(VoiceSpec):
    model_path: str
    config_path: str | None = None


def _default_model_path() -> str | None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidate = os.path.join(repo_root, "models", "piper", "en_US-lessac-medium.onnx")
    return candidate if os.path.exists(candidate) else None


def _default_config_path(model_path: str | None) -> str | None:
    if not model_path:
        return None
    candidate = f"{model_path}.json"
    return candidate if os.path.exists(candidate) else None


class PiperTTSProvider(TTSProvider):
    kind = "piper"

    def __init__(
        self,
        registry_path: str | None = None,
        voice_path: str | None = None,
        config_path: str | None = None,
        sample_rate: int = 22050,
    ) -> None:
        self.registry_path = registry_path or os.environ.get("QANTARA_VOICE_REGISTRY") or default_registry_path()
        self.sample_rate = sample_rate
        self.command = [sys.executable, "-m", "piper"]
        self.voices = self._load_voices(voice_path=voice_path, config_path=config_path)
        self.voice_entries = {
            entry.voice_id: entry for entry in filter_registry_voices("piper", self.registry_path)
        }
        self._default_voice_id = self._resolve_default_voice_id()

    @property
    def available(self) -> bool:
        return any(os.path.exists(voice.model_path) for voice in self.voices.values())

    @property
    def default_voice_id(self) -> str | None:
        return self._default_voice_id

    def list_available_voices(self) -> list[dict]:
        available = []
        for voice in self.voices.values():
            if os.path.exists(voice.model_path):
                available.append(
                    {
                        "voice_id": voice.voice_id,
                        "label": voice.label,
                        "locale": voice.locale,
                        "sample_rate": voice.sample_rate,
                        "defaults": dict((self.voice_entries.get(voice.voice_id).defaults) or {}),
                        "allowed_transforms": list((self.voice_entries.get(voice.voice_id).allowed_transforms) or []),
                    }
                )
        return available

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        requested = voice_id or self.default_voice_id
        if requested and requested in self.voices:
            voice = self.voices[requested]
            if os.path.exists(voice.model_path):
                return voice, None

        fallback = self._first_available_voice()
        if fallback is None:
            raise RuntimeError("piper is not available")
        if requested and requested != fallback.voice_id:
            return fallback, f"requested voice '{requested}' unavailable; using '{fallback.voice_id}'"
        return fallback, None

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
        *,
        expressiveness: float | None = None,  # noqa: ARG002 — not used by Piper
    ) -> tuple[list[int], VoiceSpec, str | None]:
        voice, fallback_reason = self.resolve_voice(voice_id)
        effective_rate = speech_rate if isinstance(speech_rate, (int, float)) else 1.0
        effective_rate = max(0.85, min(1.30, float(effective_rate)))
        length_scale = 1.0 / effective_rate

        cmd = [
            *self.command,
            "--model",
            voice.model_path,
            "--output-raw",
            "--length-scale",
            f"{length_scale:.4f}",
        ]
        if voice.config_path is not None:
            cmd.extend(["--config", voice.config_path])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate(text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or "piper failed")

        samples = []
        for i in range(0, len(stdout) - 1, 2):
            samples.append(int.from_bytes(stdout[i:i + 2], "little", signed=True))
        return samples, voice, fallback_reason

    def _first_available_voice(self) -> PiperVoiceSpec | None:
        for voice in self.voices.values():
            if os.path.exists(voice.model_path):
                return voice
        return None

    def _load_voices(
        self,
        voice_path: str | None,
        config_path: str | None,
    ) -> dict[str, PiperVoiceSpec]:
        voices: dict[str, PiperVoiceSpec] = {}

        for entry in filter_registry_voices("piper", self.registry_path):
            if not entry.model_path:
                continue
            voice = PiperVoiceSpec(
                voice_id=entry.voice_id,
                label=entry.label,
                model_path=entry.model_path,
                config_path=entry.config_path or _default_config_path(entry.model_path),
                sample_rate=entry.sample_rate or self.sample_rate,
                locale=entry.locale,
                defaults=entry.defaults,
                allowed_transforms=entry.allowed_transforms,
            )
            voices[voice.voice_id] = voice

        if voices:
            return voices

        fallback_voice_path = voice_path or os.environ.get("QANTARA_PIPER_MODEL") or _default_model_path()
        if fallback_voice_path is None:
            return {}

        voices["lessac"] = PiperVoiceSpec(
            voice_id="lessac",
            label="Lessac",
            model_path=fallback_voice_path,
            config_path=config_path or _default_config_path(fallback_voice_path),
            sample_rate=self.sample_rate,
            locale="en-US",
            defaults={"rate": 1.0, "pitch": 0, "tone": "neutral"},
            allowed_transforms=["rate"],
        )
        return voices

    def _resolve_default_voice_id(self) -> str | None:
        env_default = os.environ.get("QANTARA_PIPER_VOICE", "").strip()
        if env_default and env_default in self.voices:
            return env_default
        available = self._first_available_voice()
        if available is not None:
            return available.voice_id
        return next(iter(self.voices), None)
