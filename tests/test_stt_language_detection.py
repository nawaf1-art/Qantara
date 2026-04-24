from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock

from providers.stt.faster_whisper import FasterWhisperSTTProvider


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeInfo:
    def __init__(self, language: str, language_probability: float) -> None:
        self.language = language
        self.language_probability = language_probability


class STTLanguageDetectionTests(unittest.TestCase):
    def _make_provider_with_fake(self, language: str, probability: float, words: list[str]) -> FasterWhisperSTTProvider:
        provider = FasterWhisperSTTProvider()
        fake_model = MagicMock()

        def fake_transcribe(*_args, **_kwargs):
            return iter([FakeSegment(w) for w in words]), FakeInfo(language, probability)

        fake_model.transcribe.side_effect = fake_transcribe
        provider._model = fake_model  # type: ignore[attr-defined]
        # Force the ensure_model path to not re-create the model.
        provider._WhisperModel = type("Dummy", (), {})  # type: ignore[attr-defined]
        return provider

    def test_transcribe_returns_language_and_probability(self) -> None:
        provider = self._make_provider_with_fake("es", 0.93, ["hola", " mundo"])
        result = asyncio.run(provider.transcribe([0] * 1600, 16000))

        self.assertEqual(result.text.strip(), "hola mundo")
        self.assertEqual(result.language, "es")
        self.assertAlmostEqual(result.language_probability, 0.93)

    def test_transcribe_result_str_returns_text(self) -> None:
        provider = self._make_provider_with_fake("en", 0.99, ["hello"])
        result = asyncio.run(provider.transcribe([0] * 1600, 16000))
        self.assertEqual(str(result), "hello")


if __name__ == "__main__":
    unittest.main()
