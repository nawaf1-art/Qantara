from __future__ import annotations

from providers.text_script import ARABIC_FAMILY_LANGUAGES, letter_script_shares

MIN_CONFIDENT_DURATION_MS = 1500
MIN_CONFIDENT_PROBABILITY = 0.6
# A script share at or above this overrides even a confident detection
# (Whisper really wrote the text in that script).
OVERWHELMING_SCRIPT_SHARE = 0.7
# Share used to fold Gulf Arabic mis-detected as fa/ur/ps into "ar", and
# for the short/low-confidence script-majority fallback.
MAJORITY_SCRIPT_SHARE = 0.5
MIN_SCRIPT_LETTERS = 2


def script_majority_language(text: str | None) -> str | None:
    """Return ``"ar"``/``"ja"`` when that script holds a letter majority.

    Useful for typed turns and control speech, which have no STT detection.
    """
    n, arabic, japanese = letter_script_shares(text)
    if n >= MIN_SCRIPT_LETTERS and arabic >= MAJORITY_SCRIPT_SHARE:
        return "ar"
    if n >= MIN_SCRIPT_LETTERS and japanese >= MAJORITY_SCRIPT_SHARE:
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

    Only letters are counted when looking at the transcript's script, so a
    lone Arabic comma, digit or harakat never flips the language.

    * A confident detection (probability >= 0.6 over >= 1500 ms of speech)
      wins, unless the transcript's script is overwhelming (>= 0.7 Arabic or
      Japanese letters). Gulf Arabic that Whisper labels fa/ur/ps is mapped
      to ``ar`` when at least half the letters are Arabic.
    * Short or low-confidence utterances fall back to the script majority
      (>= 0.5 share with >= 2 letters), else to the user's primary language,
      so "ok" / "hi" don't flip the session language mid-conversation.

    ``duration_ms`` should be the speech duration (after VAD) when known.
    """
    n, arabic, japanese = letter_script_shares(transcript)
    confident = (
        detected is not None
        and probability is not None
        and duration_ms >= MIN_CONFIDENT_DURATION_MS
        and probability >= MIN_CONFIDENT_PROBABILITY
    )
    if confident:
        if detected in ARABIC_FAMILY_LANGUAGES and arabic >= MAJORITY_SCRIPT_SHARE:
            return "ar"
        if arabic >= OVERWHELMING_SCRIPT_SHARE:
            return "ar"
        if japanese >= OVERWHELMING_SCRIPT_SHARE:
            return "ja"
        return str(detected)
    majority = script_majority_language(transcript)
    if majority is not None:
        return majority
    return primary_language
