from __future__ import annotations

from typing import Any

from gateway.transport_spike.prompts import LANGUAGE_NAMES
from providers.text_script import language_of_locale

# Preferred voices per language, best first. Kokoro voices lead for en/es/fr
# (used when the Kokoro or routed provider is active); Piper voices follow.
PREFERRED_VOICES_PER_LANGUAGE: dict[str, tuple[str, ...]] = {
    "en": ("af_heart", "amy", "lessac"),
    "ar": ("ar_JO-kareem-medium",),
    "es": ("ef_dora", "es_ES-davefx-medium"),
    "fr": ("ff_siwis", "fr_FR-siwis-medium"),
}
# Backwards-compatible single preferred voice per language.
PREFERRED_VOICE_PER_LANGUAGE: dict[str, str] = {
    iso: voices[0] for iso, voices in PREFERRED_VOICES_PER_LANGUAGE.items()
}


def voice_matches_language(voice: dict[str, Any] | None, language: str) -> bool:
    """True when the voice's locale is for ``language``.

    Both sides are normalized, so ``ar_JO``, ``ar-JO`` and ``ar`` all match
    ``ar`` (and ``ar-JO`` as a language matches an ``ar_JO`` voice).
    """
    if not voice:
        return False
    wanted = language_of_locale(language)
    return bool(wanted) and language_of_locale(str(voice.get("locale") or "")) == wanted


def select_voice_for_language(voices: list[dict[str, Any]], language: str) -> str | None:
    voice_by_id = {
        str(voice.get("voice_id")): voice
        for voice in voices
        if voice.get("voice_id")
    }
    for preferred in PREFERRED_VOICES_PER_LANGUAGE.get(language_of_locale(language), ()):
        if voice_matches_language(voice_by_id.get(preferred), language):
            return preferred
    for voice in voices:
        if voice.get("voice_id") and voice_matches_language(voice, language):
            return str(voice["voice_id"])
    return None


def build_language_catalog(tts_provider: Any) -> list[dict[str, Any]]:
    """One entry per advertised language.

    ``tts_available`` is true only when the active TTS provider has a voice
    whose locale matches the language; e.g. Japanese reports false in every
    shipped configuration.
    """
    voices: list[dict[str, Any]] = []
    if tts_provider is not None and getattr(tts_provider, "available", False):
        try:
            voices = list(tts_provider.list_available_voices())
        except Exception:
            voices = []

    entries: list[dict[str, Any]] = []
    for iso, name in LANGUAGE_NAMES.items():
        voice_id = select_voice_for_language(voices, iso)
        entries.append({
            "iso": iso,
            "name": name,
            "tts_voice_id": voice_id,
            "tts_available": voice_id is not None,
        })
    return entries
