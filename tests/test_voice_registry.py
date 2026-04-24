from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_dir = root / "identity" / "voice-registry"
            voice_dir = root / "models" / "piper"
            registry_dir.mkdir(parents=True)
            voice_dir.mkdir(parents=True)
            for filename in [
                "en_US-lessac-medium.onnx",
                "en_US-lessac-medium.onnx.json",
                "ar_JO-kareem-medium.onnx",
                "ar_JO-kareem-medium.onnx.json",
            ]:
                (voice_dir / filename).write_text("fixture", encoding="utf-8")
            registry_path = registry_dir / "voices.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "voices": [
                            {
                                "voice_id": "lessac",
                                "label": "Lessac",
                                "engine": "piper",
                                "locale": "en-US",
                                "model_path": "models/piper/en_US-lessac-medium.onnx",
                                "config_path": "models/piper/en_US-lessac-medium.onnx.json",
                                "base_sample_rate": 22050,
                                "defaults": {"rate": 1.0, "pitch": 0, "tone": "neutral"},
                                "allowed_transforms": ["rate"],
                            },
                            {
                                "voice_id": "ar_JO-kareem-medium",
                                "label": "Kareem (Arabic)",
                                "engine": "piper",
                                "locale": "ar-JO",
                                "model_path": "models/piper/ar_JO-kareem-medium.onnx",
                                "config_path": "models/piper/ar_JO-kareem-medium.onnx.json",
                                "base_sample_rate": 22050,
                                "defaults": {"rate": 1.3, "pitch": 0, "tone": "neutral"},
                                "allowed_transforms": ["rate"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            piper = PiperTTSProvider(registry_path=str(registry_path))
            kokoro = KokoroTTSProvider()

            self.assertTrue(any(v["voice_id"] == "lessac" for v in piper.list_available_voices()))
            self.assertTrue(any(v["voice_id"] == "af_heart" for v in kokoro.list_available_voices()))
            lessac = next(v for v in piper.list_available_voices() if v["voice_id"] == "lessac")
            kareem = next(v for v in piper.list_available_voices() if v["voice_id"] == "ar_JO-kareem-medium")
            heart = next(v for v in kokoro.list_available_voices() if v["voice_id"] == "af_heart")
            self.assertIn("allowed_transforms", lessac)
            self.assertEqual(kareem["defaults"]["rate"], 1.3)
            self.assertIn("defaults", heart)
