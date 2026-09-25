from __future__ import annotations

import importlib.util
import os

from providers.stt.base import STTProvider
from providers.tts.base import TTSProvider

AUTO_TTS_KINDS = frozenset({"", "auto"})
ROUTED_TTS_KINDS = frozenset({"routed", "routing", "composite"})


def create_stt_provider(kind: str | None = None) -> STTProvider:
    provider_kind = (kind or os.environ.get("QANTARA_STT_PROVIDER", "faster_whisper")).strip().lower()

    if provider_kind in {"faster_whisper", "faster-whisper", "whisper"}:
        from providers.stt.faster_whisper import FasterWhisperSTTProvider
        return FasterWhisperSTTProvider()

    raise ValueError(f"unsupported STT provider: {provider_kind}")


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _create_routed_provider() -> TTSProvider:
    from providers.tts.kokoro import KokoroTTSProvider
    from providers.tts.piper import PiperTTSProvider
    from providers.tts.routing import RoutedTTSProvider

    return RoutedTTSProvider([KokoroTTSProvider(), PiperTTSProvider()])


def _create_auto_provider() -> TTSProvider:
    """Pick the best TTS for this install when QANTARA_TTS_PROVIDER is unset.

    Kokoro and usable Piper voices -> routed (Kokoro for en/es/fr, Piper for
    Arabic and anything Kokoro lacks). Only one of them -> that one. Neither
    -> an unavailable Piper provider, so the gateway plays its synthetic
    tone and reports that no TTS is configured.
    """
    from providers.tts.piper import PiperTTSProvider

    piper = PiperTTSProvider()
    kokoro = None
    if _module_available("kokoro"):
        from providers.tts.kokoro import KokoroTTSProvider

        kokoro = KokoroTTSProvider()
    if kokoro is not None and piper.available:
        from providers.tts.routing import RoutedTTSProvider

        return RoutedTTSProvider([kokoro, piper])
    if kokoro is not None:
        return kokoro
    return piper


def create_tts_provider(kind: str | None = None) -> TTSProvider:
    provider_kind = (kind or os.environ.get("QANTARA_TTS_PROVIDER", "auto")).strip().lower()

    if provider_kind in AUTO_TTS_KINDS:
        return _create_auto_provider()
    if provider_kind in ROUTED_TTS_KINDS:
        return _create_routed_provider()
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
