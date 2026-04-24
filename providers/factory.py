from __future__ import annotations

import os

from providers.stt.base import STTProvider
from providers.tts.base import TTSProvider


def create_stt_provider(kind: str | None = None) -> STTProvider:
    provider_kind = (kind or os.environ.get("QANTARA_STT_PROVIDER", "faster_whisper")).strip().lower()

    if provider_kind in {"faster_whisper", "faster-whisper", "whisper"}:
        from providers.stt.faster_whisper import FasterWhisperSTTProvider
        return FasterWhisperSTTProvider()

    raise ValueError(f"unsupported STT provider: {provider_kind}")


def create_tts_provider(kind: str | None = None) -> TTSProvider:
    provider_kind = (kind or os.environ.get("QANTARA_TTS_PROVIDER", "piper")).strip().lower()

    if provider_kind == "piper":
        from providers.tts.piper import PiperTTSProvider
        return PiperTTSProvider()
    if provider_kind == "kokoro":
        from providers.tts.kokoro import KokoroTTSProvider
        return KokoroTTSProvider()
    if provider_kind == "chatterbox":
        from providers.tts.chatterbox import ChatterboxTTSProvider
        from providers.voice_registry import filter_registry_voices

        try:
            from providers.tts.chatterbox_runtime import load_backend
            backend = load_backend()
        except Exception:
            backend = None
        voices = [
            {
                **entry.as_catalog_entry(),
                "voice_prompt_path": entry.model_path,
            }
            for entry in filter_registry_voices("chatterbox")
        ]
        return ChatterboxTTSProvider(backend=backend, voices_override=voices)

    raise ValueError(f"unsupported TTS provider: {provider_kind}")
