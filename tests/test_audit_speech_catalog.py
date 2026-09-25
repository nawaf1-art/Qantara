"""Audit 2026-09-24 Q-06d / SP-13: language catalog locale matching."""
from __future__ import annotations

import unittest

from gateway.transport_spike.languages_catalog import (
    build_language_catalog,
    select_voice_for_language,
    voice_matches_language,
)
from providers.tts.routing import RoutedTTSProvider
from tests.test_audit_speech_tts import ScriptedTTS, _kokoro_like, _piper_like


class LocaleNormalizationTests(unittest.TestCase):
    def test_underscore_and_hyphen_locales_match_bare_language(self) -> None:
        self.assertTrue(voice_matches_language({"locale": "ar_JO"}, "ar"))
        self.assertTrue(voice_matches_language({"locale": "ar-JO"}, "ar"))
        self.assertTrue(voice_matches_language({"locale": "AR"}, "ar"))
        self.assertTrue(voice_matches_language({"locale": "ar_JO"}, "ar-JO"))
        self.assertFalse(voice_matches_language({"locale": "arn-CL"}, "ar"))
        self.assertFalse(voice_matches_language({"locale": ""}, "ar"))
        self.assertFalse(voice_matches_language(None, "ar"))

    def test_select_voice_accepts_underscore_locale(self) -> None:
        voices = [{"voice_id": "kareem", "locale": "ar_JO"}]
        self.assertEqual(select_voice_for_language(voices, "ar"), "kareem")


class CatalogAvailabilityTests(unittest.TestCase):
    def test_routed_catalog_prefers_kokoro_and_reports_japanese_unavailable(self) -> None:
        routed = RoutedTTSProvider([_kokoro_like(), _piper_like()])
        by_iso = {e["iso"]: e for e in build_language_catalog(routed)}
        self.assertEqual(by_iso["en"]["tts_voice_id"], "af_heart")
        self.assertEqual(by_iso["es"]["tts_voice_id"], "ef_dora")
        self.assertEqual(by_iso["fr"]["tts_voice_id"], "ff_siwis")
        self.assertEqual(by_iso["ar"]["tts_voice_id"], "ar_JO-kareem-medium")
        self.assertFalse(by_iso["ja"]["tts_available"])
        self.assertIsNone(by_iso["ja"]["tts_voice_id"])

    def test_kokoro_only_catalog_has_no_arabic(self) -> None:
        by_iso = {e["iso"]: e for e in build_language_catalog(_kokoro_like())}
        self.assertFalse(by_iso["ar"]["tts_available"])
        self.assertTrue(by_iso["es"]["tts_available"])

    def test_unavailable_provider_reports_nothing(self) -> None:
        provider = ScriptedTTS("piper", [("lessac", "en-US")], available=False)
        self.assertFalse(any(e["tts_available"] for e in build_language_catalog(provider)))
        self.assertFalse(any(e["tts_available"] for e in build_language_catalog(None)))

    def test_provider_listing_error_is_tolerated(self) -> None:
        class Broken(ScriptedTTS):
            def list_available_voices(self):
                raise RuntimeError("boom")

        catalog = build_language_catalog(Broken("x", [("a", "en-US")]))
        self.assertFalse(any(e["tts_available"] for e in catalog))

    def test_piper_only_catalog_keeps_amy_for_english(self) -> None:
        piper = ScriptedTTS("piper", [("lessac", "en-US"), ("amy", "en-US")])
        by_iso = {e["iso"]: e for e in build_language_catalog(piper)}
        self.assertEqual(by_iso["en"]["tts_voice_id"], "amy")


if __name__ == "__main__":
    unittest.main()
