from __future__ import annotations

import unittest

from gateway.transport_spike.language_resolution import resolve_effective_language


class LanguageResolutionTests(unittest.TestCase):
    def test_confident_long_utterance_uses_detected(self) -> None:
        self.assertEqual(
            resolve_effective_language(detected="es", probability=0.92, duration_ms=3000, primary_language="en"),
            "es",
        )

    def test_short_utterance_uses_primary(self) -> None:
        self.assertEqual(
            resolve_effective_language(detected="es", probability=0.92, duration_ms=900, primary_language="en"),
            "en",
        )

    def test_low_probability_uses_primary(self) -> None:
        self.assertEqual(
            resolve_effective_language(detected="ja", probability=0.45, duration_ms=4000, primary_language="en"),
            "en",
        )

    def test_none_detected_uses_primary(self) -> None:
        self.assertEqual(
            resolve_effective_language(detected=None, probability=None, duration_ms=4000, primary_language="en"),
            "en",
        )

    def test_boundary_short_duration_uses_primary(self) -> None:
        self.assertEqual(
            resolve_effective_language(detected="fr", probability=0.9, duration_ms=1499, primary_language="en"),
            "en",
        )

    def test_boundary_probability_uses_primary(self) -> None:
        self.assertEqual(
            resolve_effective_language(detected="fr", probability=0.599, duration_ms=5000, primary_language="en"),
            "en",
        )

    def test_arabic_script_overrides_short_utterance_fallback(self) -> None:
        self.assertEqual(
            resolve_effective_language(
                detected="ar",
                probability=0.2,
                duration_ms=600,
                primary_language="en",
                transcript="مرحبا",
            ),
            "ar",
        )

    def test_japanese_kana_overrides_short_utterance_fallback(self) -> None:
        self.assertEqual(
            resolve_effective_language(
                detected="ja",
                probability=0.2,
                duration_ms=600,
                primary_language="en",
                transcript="こんにちは",
            ),
            "ja",
        )


if __name__ == "__main__":
    unittest.main()
