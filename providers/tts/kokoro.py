from __future__ import annotations

import os

import numpy as np

from providers.tts.base import TTSProvider, VoiceSpec
from providers.voice_registry import default_registry_path, filter_registry_voices

KOKORO_SAMPLE_RATE = 24000
KOKORO_DEFAULT_VOICE = os.environ.get("QANTARA_KOKORO_VOICE", "af_heart")
KOKORO_DEFAULT_REPO_ID = os.environ.get("QANTARA_KOKORO_REPO_ID", "hexgrad/Kokoro-82M")
KOKORO_DEFAULT_DEVICE = os.environ.get("QANTARA_KOKORO_DEVICE", "cpu")
KOKORO_DEFAULTS: dict[str, tuple[str, str]] = {
    "af_heart": ("Heart", "en-US"),
    "af_bella": ("Bella", "en-US"),
    "af_sarah": ("Sarah", "en-US"),
    "am_adam": ("Adam", "en-US"),
    "am_michael": ("Michael", "en-US"),
    "bf_emma": ("Emma", "en-GB"),
    "bf_isabella": ("Isabella", "en-GB"),
    "bm_george": ("George", "en-GB"),
    "bm_lewis": ("Lewis", "en-GB"),
    "af_nicole": ("Nicole", "en-US"),
    "af_sky": ("Sky", "en-US"),
}


class KokoroTTSProvider(TTSProvider):
    kind = "kokoro"

    def __init__(
        self,
        voice_id: str | None = None,
        repo_id: str | None = None,
        device: str | None = None,
    ) -> None:
        self._default_voice_id = voice_id or KOKORO_DEFAULT_VOICE
        self.repo_id = repo_id or KOKORO_DEFAULT_REPO_ID
        self.device = device or KOKORO_DEFAULT_DEVICE
        self.registry_path = os.environ.get("QANTARA_VOICE_REGISTRY") or default_registry_path()
        self._import_error: Exception | None = None
        self._pipelines: dict[str, object] = {}
        self._registry_entries = {
            entry.voice_id: entry for entry in filter_registry_voices("kokoro", self.registry_path)
        }
        self._registry_voices = self._load_registry_voices()
        try:
            from kokoro import KPipeline  # type: ignore

            self._KPipeline = KPipeline
        except Exception as exc:
            self._KPipeline = None
            self._import_error = exc

    @property
    def available(self) -> bool:
        return self._KPipeline is not None

    @property
    def default_voice_id(self) -> str | None:
        if self._default_voice_id in self._registry_voices:
            return self._default_voice_id
        if self._registry_voices:
            return next(iter(self._registry_voices))
        return self._default_voice_id

    def list_available_voices(self) -> list[dict]:
        source = self._registry_voices or {
            voice_id: VoiceSpec(
                voice_id=voice_id,
                label=label,
                sample_rate=KOKORO_SAMPLE_RATE,
                locale=locale,
            )
            for voice_id, (label, locale) in KOKORO_DEFAULTS.items()
        }
        return [
            {
                "voice_id": voice.voice_id,
                "label": voice.label,
                "locale": voice.locale,
                "sample_rate": voice.sample_rate,
                "defaults": dict(voice.defaults or {}),
                "allowed_transforms": list(voice.allowed_transforms or []),
            }
            for voice in source.values()
        ]

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        requested = voice_id or self.default_voice_id or KOKORO_DEFAULT_VOICE
        fallback_reason = None
        if requested in self._registry_voices:
            return self._registry_voices[requested], None
        if requested in KOKORO_DEFAULTS:
            label, locale = KOKORO_DEFAULTS[requested]
            return VoiceSpec(
                voice_id=requested,
                label=label,
                sample_rate=KOKORO_SAMPLE_RATE,
                locale=locale,
                defaults={"rate": 1.0, "pitch": 0, "tone": "neutral"},
                allowed_transforms=["rate"],
            ), None

        fallback_target = self.default_voice_id or KOKORO_DEFAULT_VOICE
        fallback_reason = f"requested voice '{requested}' unavailable; using '{fallback_target}'"
        if fallback_target in self._registry_voices:
            return self._registry_voices[fallback_target], fallback_reason
        label, locale = KOKORO_DEFAULTS[fallback_target]
        return VoiceSpec(
            voice_id=fallback_target,
            label=label,
            sample_rate=KOKORO_SAMPLE_RATE,
            locale=locale,
            defaults={"rate": 1.0, "pitch": 0, "tone": "neutral"},
            allowed_transforms=["rate"],
        ), fallback_reason

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
        *,
        expressiveness: float | None = None,  # noqa: ARG002 — not used by Kokoro
    ) -> tuple[list[int], VoiceSpec, str | None]:
        if not self.available:
            raise RuntimeError(f"kokoro unavailable: {self._import_error}")

        voice, fallback_reason = self.resolve_voice(voice_id)
        speed = speech_rate if isinstance(speech_rate, (int, float)) else 1.0
        speed = max(0.85, min(1.30, float(speed)))
        pipeline = self._ensure_pipeline(self._lang_code_for_voice(voice.voice_id))

        # Offload CPU-bound synthesis to a thread so the event loop stays
        # responsive for barge-in, VAD, and WebSocket control messages.
        import asyncio
        samples = await asyncio.to_thread(
            self._synthesize_sync, pipeline, text, voice.voice_id, speed
        )
        return samples, voice, fallback_reason

    def _synthesize_sync(
        self,
        pipeline: object,
        text: str,
        voice_id: str,
        speed: float,
    ) -> list[int]:
        """Run Kokoro synthesis on a thread pool worker."""
        chunks = []
        generator = pipeline(text, voice=voice_id, speed=speed, split_pattern=r"\n+")
        for _, _, audio in generator:
            chunks.append(np.asarray(audio, dtype=np.float32))

        if not chunks:
            return []

        merged = np.concatenate(chunks)

        # Trim leading silence/noise (samples below threshold at the start)
        threshold = 0.01
        start_idx = 0
        for i in range(min(len(merged), KOKORO_SAMPLE_RATE // 4)):  # check first 250ms
            if abs(merged[i]) > threshold:
                start_idx = max(0, i - 20)  # keep 20 samples before first real audio
                break
        if start_idx > 0:
            merged = merged[start_idx:]

        # Apply a short fade-in (2ms) to remove onset click/buzz
        fade_samples = min(48, len(merged))  # 48 samples at 24kHz = 2ms
        if fade_samples > 0:
            fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
            merged[:fade_samples] *= fade

        # Apply a short fade-out (2ms) to remove end click
        if fade_samples > 0 and len(merged) > fade_samples:
            fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
            merged[-fade_samples:] *= fade_out

        clipped = np.clip(merged, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tolist()

    def _ensure_pipeline(self, lang_code: str):
        if lang_code not in self._pipelines:
            self._pipelines[lang_code] = self._KPipeline(
                lang_code=lang_code,
                repo_id=self.repo_id,
                device=self.device,
            )
        return self._pipelines[lang_code]

    @staticmethod
    def _lang_code_for_voice(voice_id: str) -> str:
        return voice_id.split("_", 1)[0][0]

    def _load_registry_voices(self) -> dict[str, VoiceSpec]:
        voices: dict[str, VoiceSpec] = {}
        for entry in filter_registry_voices("kokoro", self.registry_path):
            voices[entry.voice_id] = VoiceSpec(
                voice_id=entry.voice_id,
                label=entry.label,
                sample_rate=entry.sample_rate or KOKORO_SAMPLE_RATE,
                locale=entry.locale,
                defaults=entry.defaults,
                allowed_transforms=entry.allowed_transforms,
            )
        return voices
