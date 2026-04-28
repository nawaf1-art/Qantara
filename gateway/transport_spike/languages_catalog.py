from __future__ import annotations

from typing import Any

from gateway.transport_spike.prompts import LANGUAGE_NAMES

PREFERRED_VOICE_PER_LANGUAGE: dict[str, str] = {
    "en": "amy",
    "ar": "ar_JO-kareem-medium",
    "es": "es_ES-davefx-medium",
    "fr": "fr_FR-siwis-medium",
}


def voice_matches_language(voice: dict[str, Any] | None, language: str) -> bool:
    if not voice:
        return False
    locale = str(voice.get("locale") or "").strip().lower()
    language = language.lower()
    return locale == language or locale.startswith(f"{language}-")


def select_voice_for_language(voices: list[dict[str, Any]], language: str) -> str | None:
    voice_by_id = {
        str(voice.get("voice_id")): voice
        for voice in voices
        if voice.get("voice_id")
    }
    preferred = PREFERRED_VOICE_PER_LANGUAGE.get(language)
    if preferred and voice_matches_language(voice_by_id.get(preferred), language):
        return preferred
    for voice in voices:
        if voice_matches_language(voice, language):
            return str(voice["voice_id"])
    return None


def build_language_catalog(tts_provider: Any) -> list[dict[str, Any]]:
    voices: list[dict[str, Any]] = []
    if tts_provider is not None and tts_provider.available:
        voices = tts_provider.list_available_voices()

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
