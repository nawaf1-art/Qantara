from __future__ import annotations

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ar": "Arabic",
    "es": "Spanish",
    "fr": "French",
    "ja": "Japanese",
}


def _name(code: str | None) -> str:
    if code is None:
        return "the user's language"
    return LANGUAGE_NAMES.get(code, code)


def build_translation_directive(
    mode: str | None,
    source: str | None,
    target: str | None,
    detected_language: str | None,
) -> str:
    """Translation directive to append to the adapter's system prompt.

    Returns an empty string when no directive is needed (the adapter's
    normal system prompt applies unchanged).
    """
    if mode is None:
        return ""
    if mode == "assistant":
        lang = _name(detected_language)
        return (
            f"Respond in the same language the user is speaking. "
            f"The user's current language appears to be {lang}. "
            f"Do not switch languages mid-response."
        )
    if mode == "directional":
        if not source or not target:
            raise ValueError("directional mode requires both source and target")
        return (
            f"The user is speaking in {_name(source)}. "
            f"Respond only in {_name(target)}. "
            f"Do not add commentary or explanations — answer in {_name(target)} as if that is your native language."
        )
    if mode == "live":
        if not source or not target:
            raise ValueError("live mode requires both source and target")
        return (
            f"Translate the user's message from {_name(source)} to {_name(target)}. "
            f"Output only the translation. "
            f"No commentary, no explanations, no acknowledgements, no quotes around the output."
        )
    raise ValueError(f"unknown translation mode: {mode}")
