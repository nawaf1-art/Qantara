from __future__ import annotations

import unittest

from providers.tts.kokoro import KokoroTTSProvider
from providers.tts.piper import PiperTTSProvider
from providers.voice_registry import filter_registry_voices, load_voice_registry


class VoiceRegistryTests(unittest.TestCase):
    def test_registry_contains_multi_engine_entries(self) -> None:
        voices = load_voice_registry()
        self.assertTrue(any(v.engine == "piper" for v in voices))
        self.assertTrue(any(v.engine == "kokoro" for v in voices))

    def test_engine_filters_are_shared(self) -> None:
        piper_voices = filter_registry_voices("piper")
        kokoro_voices = filter_registry_voices("kokoro")
        self.assertTrue(any(v.voice_id == "lessac" for v in piper_voices))
        self.assertTrue(any(v.voice_id == "af_heart" for v in kokoro_voices))

    def test_piper_and_kokoro_list_registry_backed_voices(self) -> None:
        piper = PiperTTSProvider()
        kokoro = KokoroTTSProvider()

        self.assertTrue(any(v["voice_id"] == "lessac" for v in piper.list_available_voices()))
        self.assertTrue(any(v["voice_id"] == "af_heart" for v in kokoro.list_available_voices()))
        lessac = next(v for v in piper.list_available_voices() if v["voice_id"] == "lessac")
        kareem = next(v for v in piper.list_available_voices() if v["voice_id"] == "ar_JO-kareem-medium")
        heart = next(v for v in kokoro.list_available_voices() if v["voice_id"] == "af_heart")
        self.assertIn("allowed_transforms", lessac)
        self.assertEqual(kareem["defaults"]["rate"], 1.3)
        self.assertIn("defaults", heart)
