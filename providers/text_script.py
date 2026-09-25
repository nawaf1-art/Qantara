"""Dependency-free helpers for reasoning about the writing script of text.

Only Unicode *letters* (general category ``L*``) are counted, so punctuation
(Arabic comma ``،``), digits (``٣``) and combining marks (harakat, ``Mn``)
never tip a decision. Used by the gateway's language resolver and by the
TTS voice/locale guard.
"""
from __future__ import annotations

import unicodedata
from collections import Counter

ARABIC_FAMILY_LANGUAGES = frozenset({"ar", "fa", "ur", "ps"})

_LANGUAGE_SCRIPTS: dict[str, str] = {
    **{code: "arabic" for code in ARABIC_FAMILY_LANGUAGES},
    "ja": "japanese",
    "zh": "han",
    "ru": "cyrillic",
    "uk": "cyrillic",
    "bg": "cyrillic",
    "sr": "cyrillic",
    "be": "cyrillic",
    "kk": "cyrillic",
    "el": "greek",
    "he": "hebrew",
    "yi": "hebrew",
    "hi": "devanagari",
    "mr": "devanagari",
    "ne": "devanagari",
    "ko": "hangul",
    "th": "thai",
}

_NAME_PREFIXES: tuple[tuple[str, str], ...] = (
    ("LATIN", "latin"),
    ("ARABIC", "arabic"),
    ("HIRAGANA", "kana"),
    ("KATAKANA", "kana"),
    ("HALFWIDTH KATAKANA", "kana"),
    ("CJK", "han"),
    ("CYRILLIC", "cyrillic"),
    ("GREEK", "greek"),
    ("HEBREW", "hebrew"),
    ("DEVANAGARI", "devanagari"),
    ("HANGUL", "hangul"),
    ("THAI", "thai"),
)


def _letter_script(char: str) -> str | None:
    if not unicodedata.category(char).startswith("L"):
        return None
    name = unicodedata.name(char, "")
    for prefix, script in _NAME_PREFIXES:
        if name.startswith(prefix):
            return script
    return "other"


def letter_script_counts(text: str | None) -> Counter[str]:
    """Count letters per script. Non-letters are ignored."""
    counts: Counter[str] = Counter()
    if not text:
        return counts
    for char in text:
        script = _letter_script(char)
        if script is not None:
            counts[script] += 1
    return counts


def letter_script_shares(text: str | None) -> tuple[int, float, float]:
    """Return ``(letter_count, arabic_share, japanese_share)``.

    The Japanese share counts kana plus Han ideographs, but only when at
    least one kana letter is present (Han alone is ambiguous with Chinese).
    """
    counts = letter_script_counts(text)
    total = sum(counts.values())
    if total == 0:
        return 0, 0.0, 0.0
    arabic = counts.get("arabic", 0) / total
    kana = counts.get("kana", 0)
    japanese = (kana + counts.get("han", 0)) / total if kana else 0.0
    return total, arabic, japanese


def dominant_script(text: str | None, *, threshold: float = 0.5) -> str | None:
    """Return the script holding at least ``threshold`` of the letters.

    Kana plus Han (when kana is present) is reported as ``"japanese"``.
    Returns ``None`` for text without letters or with no clear majority.
    """
    counts = letter_script_counts(text)
    total = sum(counts.values())
    if total == 0:
        return None
    if counts.get("kana", 0):
        counts["japanese"] = counts.pop("kana") + counts.pop("han", 0)
    script, count = counts.most_common(1)[0]
    if count / total >= threshold:
        return script
    return None


def language_of_locale(locale: str | None) -> str:
    """Normalize a locale/language tag (``ar_JO``, ``ar-JO``, ``AR``) to ``ar``."""
    if not locale:
        return ""
    return str(locale).strip().replace("_", "-").split("-", 1)[0].lower()


def script_for_language(language: str | None) -> str:
    """Writing script conventionally used for a language (default ``latin``)."""
    return _LANGUAGE_SCRIPTS.get(language_of_locale(language), "latin")
