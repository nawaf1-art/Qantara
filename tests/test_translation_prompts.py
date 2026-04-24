from __future__ import annotations

import unittest

from gateway.transport_spike.prompts import LANGUAGE_NAMES, build_translation_directive


class TranslationPromptTests(unittest.TestCase):
    def test_assistant_mode_mentions_same_language(self) -> None:
        directive = build_translation_directive(mode="assistant", source=None, target=None, detected_language="es")
        self.assertIn("same language", directive.lower())
        self.assertIn("spanish", directive.lower())

    def test_directional_mode_substitutes_source_and_target(self) -> None:
        directive = build_translation_directive(mode="directional", source="en", target="ar", detected_language="en")
        self.assertIn("english", directive.lower())
        self.assertIn("arabic", directive.lower())
        self.assertIn("respond only in", directive.lower())

    def test_live_mode_is_pure_translator(self) -> None:
        directive = build_translation_directive(mode="live", source="en", target="ja", detected_language="en")
        self.assertIn("translate", directive.lower())
        self.assertIn("japanese", directive.lower())
        self.assertIn("no commentary", directive.lower())

    def test_none_mode_returns_empty(self) -> None:
        self.assertEqual(
            build_translation_directive(mode=None, source=None, target=None, detected_language="en"), ""
        )

    def test_directional_raises_without_pair(self) -> None:
        with self.assertRaises(ValueError):
            build_translation_directive(mode="directional", source=None, target="ar", detected_language="en")

    def test_live_raises_without_pair(self) -> None:
        with self.assertRaises(ValueError):
            build_translation_directive(mode="live", source="en", target=None, detected_language="en")

    def test_unknown_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_translation_directive(mode="impossible", source=None, target=None, detected_language=None)

    def test_language_names_cover_launch_five(self) -> None:
        for iso in ("en", "ar", "es", "fr", "ja"):
            self.assertIn(iso, LANGUAGE_NAMES)


if __name__ == "__main__":
    unittest.main()
