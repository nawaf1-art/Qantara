from __future__ import annotations

from typing import Any

from gateway.transport_spike.prompts import LANGUAGE_NAMES

PREFERRED_VOICE_PER_LANGUAGE: dict[str, str] = {
    "en": "amy",
    "ar": "ar_JO-kareem-medium",
    "es": "es_ES-davefx-medium",
    "fr": "fr_FR-siwis-medium",
    "ja": "af_heart",  # Kokoro; Piper Japanese quality is limited.
}


def build_language_catalog(tts_provider: Any) -> list[dict[str, Any]]:
    available_voice_ids: set[str] = set()
    if tts_provider is not None and tts_provider.available:
        available_voice_ids = {v["voice_id"] for v in tts_provider.list_available_voices()}

    entries: list[dict[str, Any]] = []
    for iso, name in LANGUAGE_NAMES.items():
        preferred = PREFERRED_VOICE_PER_LANGUAGE.get(iso)
        tts_available = bool(preferred and preferred in available_voice_ids)
        entries.append({
            "iso": iso,
            "name": name,
            "tts_voice_id": preferred if tts_available else None,
            "tts_available": tts_available,
        })
    return entries
