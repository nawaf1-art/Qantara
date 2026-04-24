from __future__ import annotations

MIN_CONFIDENT_DURATION_MS = 1500
MIN_CONFIDENT_PROBABILITY = 0.6


def _script_language_hint(text: str | None) -> str | None:
    if not text:
        return None
    for char in text:
        codepoint = ord(char)
        if (
            0x0600 <= codepoint <= 0x06FF
            or 0x0750 <= codepoint <= 0x077F
            or 0x08A0 <= codepoint <= 0x08FF
        ):
            return "ar"
        if 0x3040 <= codepoint <= 0x30FF:
            return "ja"
    return None


def resolve_effective_language(
    detected: str | None,
    probability: float | None,
    duration_ms: float,
    primary_language: str,
    transcript: str | None = None,
) -> str:
    """Return the language to treat the utterance as.

    Short or low-confidence utterances fall back to the user's primary
    language so single-syllable responses ("hi", "ok") don't flip the
    session language mid-conversation.
    """
    script_hint = _script_language_hint(transcript)
    if script_hint is not None:
        return script_hint
    if detected is None or probability is None:
        return primary_language
    if duration_ms < MIN_CONFIDENT_DURATION_MS:
        return primary_language
    if probability < MIN_CONFIDENT_PROBABILITY:
        return primary_language
    return detected
