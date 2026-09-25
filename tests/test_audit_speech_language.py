"""Audit 2026-09-24 Q-06c / Appendix B: code-switch language resolver.

The old resolver returned "ar" whenever *any* Arabic codepoint appeared
(a lone Arabic comma or digit was enough) and flipped the reply language.
These cases lock the proportion-based, letters-only replacement.
"""
from __future__ import annotations

import unittest

from gateway.transport_spike.language_resolution import (
    resolve_effective_language,
    script_majority_language,
)
from providers.text_script import (
    dominant_script,
    language_of_locale,
    letter_script_shares,
    script_for_language,
)


def _resolve(detected, prob, speech_ms, primary, transcript):
    return resolve_effective_language(
        detected=detected,
        probability=prob,
        duration_ms=speech_ms,
        primary_language=primary,
        transcript=transcript,
    )


class AppendixBCases(unittest.TestCase):
    def test_english_with_one_arabic_word_is_english(self) -> None:
        self.assertEqual(
            _resolve("en", 0.95, 3000, "en", "I need to go to the مكتب tomorrow morning"), "en"
        )

    def test_english_with_arabic_script_name_is_english(self) -> None:
        self.assertEqual(
            _resolve("en", 0.93, 3200, "en", "Please call محمد about the meeting today"), "en"
        )

    def test_english_with_arabic_comma_is_english(self) -> None:
        self.assertEqual(
            _resolve("en", 0.9, 2500, "en", "Hello there، how are you doing today"), "en"
        )

    def test_english_with_arabic_digit_is_english(self) -> None:
        self.assertEqual(_resolve("en", 0.9, 2500, "en", "I have ٣ meetings today"), "en")

    def test_english_with_one_katakana_word_is_english(self) -> None:
        self.assertEqual(
            _resolve("en", 0.9, 3000, "en", "Let's order some ラーメン for dinner tonight please"),
            "en",
        )

    def test_pure_arabic_is_arabic(self) -> None:
        self.assertEqual(_resolve("ar", 0.95, 3000, "en", "مرحبا كيف حالك اليوم"), "ar")

    def test_gulf_code_switch_sentence_is_arabic(self) -> None:
        self.assertEqual(_resolve("ar", 0.8, 2500, "en", "ابغى الـ report بكرة الصبح"), "ar")

    def test_gulf_code_switch_detected_as_english_still_arabic(self) -> None:
        # Overwhelming Arabic script share wins even over a confident "en".
        self.assertEqual(_resolve("en", 0.7, 2500, "en", "ابغى الـ report بكرة الصبح"), "ar")

    def test_gulf_arabic_misdetected_as_persian_maps_to_arabic(self) -> None:
        self.assertEqual(_resolve("fa", 0.70, 2000, "en", "وش تبي نسوي اليوم"), "ar")

    def test_gulf_arabic_misdetected_as_urdu_maps_to_arabic(self) -> None:
        self.assertEqual(_resolve("ur", 0.65, 2000, "en", "وش تبي نسوي اليوم"), "ar")

    def test_short_arabic_thanks_low_prob_is_arabic(self) -> None:
        self.assertEqual(_resolve("ar", 0.2, 600, "en", "شكرا"), "ar")

    def test_short_kana_is_japanese(self) -> None:
        self.assertEqual(_resolve("ja", 0.3, 600, "en", "はい"), "ja")

    def test_short_ok_in_arabic_session_stays_arabic(self) -> None:
        self.assertEqual(_resolve("en", 0.5, 500, "ar", "OK"), "ar")

    def test_confident_spanish_is_spanish(self) -> None:
        self.assertEqual(_resolve("es", 0.9, 3000, "en", "Hola, ¿cómo estás hoy?"), "es")

    def test_low_confidence_english_with_arabic_thanks_is_primary(self) -> None:
        self.assertEqual(_resolve("en", 0.4, 3000, "en", "Thank you so much شكرا"), "en")


class ResolverEdgeCases(unittest.TestCase):
    def test_lone_arabic_comma_short_utterance_is_primary(self) -> None:
        self.assertEqual(_resolve(None, None, 400, "en", "،"), "en")

    def test_single_arabic_letter_is_not_enough(self) -> None:
        # n >= 2 letters required for the script-majority fallback.
        self.assertEqual(_resolve(None, None, 400, "en", "و"), "en")

    def test_harakat_are_ignored(self) -> None:
        # Diacritics (Mn) are not letters and must not tip the balance.
        self.assertEqual(
            _resolve("en", 0.9, 3000, "en", "Hello friend ًٌٍَُِّْ how are you"), "en"
        )

    def test_confident_japanese_with_han_and_kana(self) -> None:
        self.assertEqual(_resolve("ja", 0.9, 3000, "en", "今日は良い天気ですね"), "ja")

    def test_no_transcript_confident_detection(self) -> None:
        self.assertEqual(_resolve("fr", 0.9, 3000, "en", None), "fr")

    def test_script_majority_language_helper(self) -> None:
        self.assertEqual(script_majority_language("مرحبا كيف حالك"), "ar")
        self.assertEqual(script_majority_language("こんにちは"), "ja")
        self.assertIsNone(script_majority_language("Your timer is done."))
        self.assertIsNone(script_majority_language("، ٣"))
        self.assertIsNone(script_majority_language(None))


class TextScriptHelpers(unittest.TestCase):
    def test_letter_shares_ignore_digits_and_punctuation(self) -> None:
        n, ar, ja = letter_script_shares("abc ٣، ١٢")
        self.assertEqual(n, 3)
        self.assertEqual(ar, 0.0)
        self.assertEqual(ja, 0.0)

    def test_han_counts_for_japanese_only_with_kana(self) -> None:
        _, _, ja_han_only = letter_script_shares("中文字")
        _, _, ja_mixed = letter_script_shares("日本語です")
        self.assertEqual(ja_han_only, 0.0)
        self.assertEqual(ja_mixed, 1.0)

    def test_dominant_script(self) -> None:
        self.assertEqual(dominant_script("مرحبا بك"), "arabic")
        self.assertEqual(dominant_script("Hello there"), "latin")
        self.assertEqual(dominant_script("ابغى الـ report بكرة الصبح"), "arabic")
        self.assertEqual(dominant_script("こんにちは"), "japanese")
        self.assertIsNone(dominant_script("12345 !!"))
        self.assertIsNone(dominant_script(""))

    def test_locale_normalization(self) -> None:
        self.assertEqual(language_of_locale("ar_JO"), "ar")
        self.assertEqual(language_of_locale("ar-JO"), "ar")
        self.assertEqual(language_of_locale("EN-us"), "en")
        self.assertEqual(language_of_locale(" fr "), "fr")
        self.assertEqual(language_of_locale(None), "")

    def test_script_for_language(self) -> None:
        self.assertEqual(script_for_language("ar"), "arabic")
        self.assertEqual(script_for_language("ar_JO"), "arabic")
        self.assertEqual(script_for_language("fa"), "arabic")
        self.assertEqual(script_for_language("ja"), "japanese")
        self.assertEqual(script_for_language("en-US"), "latin")
        self.assertEqual(script_for_language("es"), "latin")


if __name__ == "__main__":
    unittest.main()
