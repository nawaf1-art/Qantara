from __future__ import annotations

import asyncio
import unittest

from providers.tts.chatterbox import ChatterboxTTSProvider


class FakeChatterboxBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.sample_rate = 24000

    def generate(
        self,
        text: str,
        *,
        exaggeration: float,
        cfg_weight: float,
        voice_prompt_path: str | None,
    ) -> list[int]:
        self.calls.append(
            {
                "text": text,
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
                "voice_prompt_path": voice_prompt_path,
            }
        )
        return [0] * 1200


class ChatterboxProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = FakeChatterboxBackend()
        self.provider = ChatterboxTTSProvider(
            backend=self.backend,
            voices_override=[
                {
                    "voice_id": "warm",
                    "label": "Warm",
                    "locale": "en-US",
                    "sample_rate": 24000,
                    "voice_prompt_path": None,
                    "defaults": {"rate": 1.0, "expressiveness": 0.5},
                    "allowed_transforms": ["rate", "expressiveness"],
                },
            ],
        )

    def test_available_when_backend_present(self) -> None:
        self.assertTrue(self.provider.available)

    def test_default_voice_id_is_first_voice(self) -> None:
        self.assertEqual(self.provider.default_voice_id, "warm")

    def test_list_available_voices_returns_catalog_entries(self) -> None:
        voices = self.provider.list_available_voices()
        self.assertEqual(len(voices), 1)
        self.assertEqual(voices[0]["voice_id"], "warm")
        self.assertIn("expressiveness", voices[0]["allowed_transforms"])

    def test_resolve_voice_returns_requested(self) -> None:
        voice, fallback_reason = self.provider.resolve_voice("warm")
        self.assertEqual(voice.voice_id, "warm")
        self.assertIsNone(fallback_reason)

    def test_resolve_voice_falls_back_when_unknown(self) -> None:
        voice, fallback_reason = self.provider.resolve_voice("does-not-exist")
        self.assertEqual(voice.voice_id, "warm")
        self.assertIsNotNone(fallback_reason)

    def test_synthesize_maps_expressiveness_to_exaggeration(self) -> None:
        samples, voice, fallback_reason = asyncio.run(
            self.provider.synthesize("hello", voice_id="warm", speech_rate=1.0, expressiveness=0.8)
        )
        self.assertEqual(len(samples), 1200)
        self.assertEqual(voice.sample_rate, 24000)
        self.assertIsNone(fallback_reason)
        self.assertEqual(self.backend.calls[0]["exaggeration"], 0.8)

    def test_synthesize_uses_voice_default_when_expressiveness_is_none(self) -> None:
        asyncio.run(self.provider.synthesize("hello", voice_id="warm", speech_rate=1.0, expressiveness=None))
        self.assertEqual(self.backend.calls[0]["exaggeration"], 0.5)

    def test_synthesize_clamps_expressiveness_to_valid_range(self) -> None:
        asyncio.run(self.provider.synthesize("x", voice_id="warm", expressiveness=2.5))
        self.assertEqual(self.backend.calls[-1]["exaggeration"], 1.0)
        asyncio.run(self.provider.synthesize("x", voice_id="warm", expressiveness=-0.3))
        self.assertEqual(self.backend.calls[-1]["exaggeration"], 0.0)

    def test_synthesize_raises_when_no_voices(self) -> None:
        empty = ChatterboxTTSProvider(backend=self.backend, voices_override=[])
        with self.assertRaises(RuntimeError):
            asyncio.run(empty.synthesize("hello"))


if __name__ == "__main__":
    unittest.main()
