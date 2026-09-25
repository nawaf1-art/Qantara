"""Language-aware voice selection, the voice/locale guard, and a routing
TTS provider that picks an engine per language.

Audit 2026-09-24 Q-06: never synthesize text with a voice whose locale does
not match the text's script (English espeak reading Arabic produces letter
names). Raise :class:`NoVoiceForLanguage` instead, so the gateway reports
``no_voice_for_language`` to the client rather than speaking gibberish.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from typing import Any

from providers.text_script import dominant_script, language_of_locale, script_for_language
from providers.tts.base import TTSProvider, VoiceSpec

NO_VOICE_FOR_LANGUAGE = "no_voice_for_language"

_SCRIPT_DEFAULT_LANGUAGE = {
    "arabic": "ar",
    "japanese": "ja",
    "han": "zh",
    "cyrillic": "ru",
    "greek": "el",
    "hebrew": "he",
    "devanagari": "hi",
    "hangul": "ko",
    "thai": "th",
    "latin": "en",
}
# When only the script is known, prefer voices of these languages first.
_SCRIPT_PREFERRED_LANGUAGE = {"latin": "en", "arabic": "ar"}


class NoVoiceForLanguage(RuntimeError):
    """No configured voice can speak the requested language or script."""

    reason = NO_VOICE_FOR_LANGUAGE

    def __init__(self, language: str | None, script: str | None, engine: str | None = None) -> None:
        self.language = language
        self.script = script
        self.engine = engine
        target = language or script or "unknown"
        where = f"{engine} " if engine else ""
        super().__init__(
            f"{NO_VOICE_FOR_LANGUAGE}: no {where}voice available for '{target}' text"
        )


def _voice_field(voice: Any, name: str) -> str:
    if isinstance(voice, dict):
        return str(voice.get(name) or "")
    return str(getattr(voice, name, "") or "")


def resolve_target(text: str | None, language: str | None = None) -> tuple[str | None, str | None]:
    """Return ``(target_language, target_script)`` for a synthesis request.

    The text's dominant script wins over a declared language written in a
    different script (e.g. the turn was declared Arabic but the model
    replied in English): the voice must be able to read what is written.
    """
    text_script = dominant_script(text)
    target_language = language_of_locale(language) or None
    if target_language:
        language_script = script_for_language(target_language)
        if text_script is not None and text_script != language_script:
            return None, text_script
        return target_language, language_script
    return None, text_script


def voice_can_speak(voice: Any, target_language: str | None, target_script: str | None) -> bool:
    locale = _voice_field(voice, "locale")
    if target_language:
        return language_of_locale(locale) == target_language
    if target_script:
        return script_for_language(locale) == target_script
    return True


def pick_voice_for_target(
    voices: Iterable[Any],
    target_language: str | None,
    target_script: str | None,
) -> Any | None:
    candidates = [v for v in voices if voice_can_speak(v, target_language, target_script)]
    if not candidates:
        return None
    if not target_language and target_script in _SCRIPT_PREFERRED_LANGUAGE:
        preferred = _SCRIPT_PREFERRED_LANGUAGE[target_script]
        for voice in candidates:
            if language_of_locale(_voice_field(voice, "locale")) == preferred:
                return voice
    return candidates[0]


def ensure_voice_for_text(
    current: Any,
    voices: Iterable[Any],
    text: str | None,
    language: str | None = None,
    *,
    engine: str | None = None,
) -> tuple[Any, str | None]:
    """Return ``(voice, reason)`` able to speak ``text``.

    ``current`` is returned unchanged when it fits (or when the text has no
    clear script). Otherwise the first fitting voice from ``voices`` is
    returned with a human-readable reason, or :class:`NoVoiceForLanguage`
    is raised.
    """
    target_language, target_script = resolve_target(text, language)
    if target_language is None and target_script is None:
        return current, None
    if current is not None and voice_can_speak(current, target_language, target_script):
        return current, None
    replacement = pick_voice_for_target(voices, target_language, target_script)
    if replacement is None:
        raise NoVoiceForLanguage(
            target_language or _SCRIPT_DEFAULT_LANGUAGE.get(target_script or ""),
            target_script,
            engine,
        )
    new_id = _voice_field(replacement, "voice_id")
    target = target_language or target_script
    if current is None:
        return replacement, f"using '{new_id}' for '{target}' text"
    current_id = _voice_field(current, "voice_id")
    return replacement, f"voice '{current_id}' cannot speak '{target}' text; using '{new_id}'"


def languages_with_voices(provider: TTSProvider | None) -> set[str]:
    """Normalized language codes (``ar``, ``en``...) the provider can speak."""
    if provider is None or not getattr(provider, "available", False):
        return set()
    try:
        voices = provider.list_available_voices()
    except Exception:
        return set()
    return {
        language_of_locale(str(voice.get("locale") or ""))
        for voice in voices
        if voice.get("locale")
    } - {""}


def has_voice_for_language(provider: TTSProvider | None, language: str | None) -> bool:
    """True when ``provider`` has at least one voice for ``language``.

    Gateway helper: check before accepting a translation target or before
    speaking, and send ``tts_status: no_voice_for_language`` when False.
    """
    code = language_of_locale(language)
    return bool(code) and code in languages_with_voices(provider)


class RoutedTTSProvider(TTSProvider):
    """Route each request to the first engine with a voice for its language.

    ``providers`` is in preference order, e.g. ``[kokoro, piper]``: Kokoro
    speaks en/es/fr, Piper covers Arabic (and anything Kokoro lacks) when a
    matching Piper voice is installed.
    """

    kind = "routed"

    def __init__(self, providers: Sequence[TTSProvider]) -> None:
        self.providers = list(providers)

    def _available_providers(self) -> list[TTSProvider]:
        return [p for p in self.providers if p.available]

    def _catalog(self) -> list[tuple[TTSProvider, dict]]:
        entries: list[tuple[TTSProvider, dict]] = []
        seen: set[str] = set()
        for provider in self._available_providers():
            try:
                voices = provider.list_available_voices()
            except Exception:
                continue
            for voice in voices:
                voice_id = str(voice.get("voice_id") or "")
                if not voice_id or voice_id in seen:
                    continue
                seen.add(voice_id)
                entries.append((provider, voice))
        return entries

    def _owner(self, voice_id: str | None) -> TTSProvider | None:
        if not voice_id:
            return None
        for provider, voice in self._catalog():
            if voice.get("voice_id") == voice_id:
                return provider
        return None

    @property
    def available(self) -> bool:
        return bool(self._available_providers())

    @property
    def engines(self) -> list[str]:
        return [p.kind for p in self._available_providers()]

    @property
    def default_voice_id(self) -> str | None:
        catalog = self._catalog()
        english = pick_voice_for_target([v for _, v in catalog], "en", "latin")
        if english is not None:
            return str(english["voice_id"])
        for provider in self._available_providers():
            if provider.default_voice_id:
                return provider.default_voice_id
        return None

    def list_available_voices(self) -> list[dict]:
        return [{**voice, "engine": provider.kind} for provider, voice in self._catalog()]

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        requested = voice_id or self.default_voice_id
        owner = self._owner(requested)
        if owner is not None:
            return owner.resolve_voice(requested)
        available = self._available_providers()
        if not available:
            raise RuntimeError("no routed TTS engine is available")
        return available[0].resolve_voice(requested)

    def voice_for_language(self, language: str) -> str | None:
        voice = pick_voice_for_target(
            [v for _, v in self._catalog()], language_of_locale(language) or None,
            script_for_language(language),
        )
        return str(voice["voice_id"]) if voice is not None else None

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
        *,
        expressiveness: float | None = None,
        language: str | None = None,
    ) -> tuple[list[int], VoiceSpec, str | None]:
        catalog = self._catalog()
        if not catalog:
            raise RuntimeError("no routed TTS engine is available")
        requested = voice_id or self.default_voice_id
        current = next((v for _, v in catalog if v.get("voice_id") == requested), None)
        chosen, route_reason = ensure_voice_for_text(
            current, [v for _, v in catalog], text, language, engine=self.kind
        )
        if chosen is None:
            # Text has no clear script and the requested voice is unknown:
            # let the preferred engine apply its own fallback.
            owner: TTSProvider = self._available_providers()[0]
            chosen_id = requested
        else:
            chosen_id = str(chosen["voice_id"])
            owner = self._owner(chosen_id) or self._available_providers()[0]
        samples, voice, provider_reason = await owner.synthesize(
            text,
            voice_id=chosen_id,
            speech_rate=speech_rate,
            expressiveness=expressiveness,
        )
        return samples, voice, route_reason or provider_reason

    async def warmup(self) -> None:
        """Warm up every engine that supports it (e.g. Kokoro)."""
        for provider in self._available_providers():
            warmup = getattr(provider, "warmup", None)
            if warmup is not None:
                result = warmup()
                if asyncio.iscoroutine(result):
                    await result
