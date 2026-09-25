"""Audit 2026-09-24 V-6 / LC-13: faster-whisper language, filtering, decode.

Uses a fake WhisperModel; no model is ever loaded.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import threading
import unittest
from unittest.mock import patch

import numpy as np

from providers.stt.base import STTProvider, STTResult
from providers.stt.faster_whisper import (
    FasterWhisperSTTProvider,
    is_known_hallucination,
    pick_restricted_language,
)


class Seg:
    def __init__(self, text, no_speech_prob=0.01, avg_logprob=-0.2, compression_ratio=1.2) -> None:
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob
        self.compression_ratio = compression_ratio


class Info:
    def __init__(self, language="en", language_probability=0.9, duration=3.0, duration_after_vad=2.0) -> None:
        self.language = language
        self.language_probability = language_probability
        self.duration = duration
        self.duration_after_vad = duration_after_vad


class FakeWhisperModel:
    def __init__(self, segments=None, info=None, all_probs=None, detect_error=False) -> None:
        self.segments = segments if segments is not None else [Seg(" hello"), Seg(" world")]
        self.info = info or Info()
        self.all_probs = all_probs or [("en", 0.9), ("ar", 0.05)]
        self.detect_error = detect_error
        self.transcribe_calls: list[dict] = []
        self.detect_calls: list[dict] = []
        self.audio_seen: list[np.ndarray] = []
        self.threads: list[str] = []

    def transcribe(self, audio, **kwargs):
        self.transcribe_calls.append(kwargs)
        self.audio_seen.append(audio)
        self.threads.append(threading.current_thread().name)
        return iter(self.segments), self.info

    def detect_language(self, audio=None, **kwargs):
        self.detect_calls.append(kwargs)
        if self.detect_error:
            raise RuntimeError("detection failed")
        best = max(self.all_probs, key=lambda item: item[1])
        return best[0], best[1], list(self.all_probs)


def _provider(model: FakeWhisperModel, **kwargs) -> FasterWhisperSTTProvider:
    provider = FasterWhisperSTTProvider(**kwargs)
    provider._model = model
    provider._WhisperModel = object  # type: ignore[assignment]
    provider._import_error = None
    return provider


def _clean_env(**overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("QANTARA_STT_LANGUAGES", "QANTARA_WHISPER"))}
    env.update(overrides)
    return env


class TranscribeSignatureTests(unittest.TestCase):
    def test_base_signature_accepts_optional_language(self) -> None:
        params = inspect.signature(STTProvider.transcribe).parameters
        self.assertIn("language", params)
        self.assertIsNone(params["language"].default)
        params = inspect.signature(STTProvider.transcribe_partial).parameters
        self.assertIn("language", params)

    def test_stt_result_has_optional_speech_duration(self) -> None:
        self.assertIsNone(STTResult(text="hi").speech_duration_ms)
        self.assertEqual(STTResult(text="hi", speech_duration_ms=12.0).speech_duration_ms, 12.0)


class FasterWhisperLanguageTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_language_is_passed_to_whisper(self) -> None:
        with patch.dict(os.environ, _clean_env(QANTARA_STT_LANGUAGES="en,ar"), clear=True):
            model = FakeWhisperModel(info=Info(language="ar", language_probability=1.0))
            provider = _provider(model)
            result = await provider.transcribe([0] * 1600, 16000, language="ar")
        self.assertEqual(model.transcribe_calls[0]["language"], "ar")
        self.assertEqual(model.detect_calls, [])
        self.assertEqual(result.language, "ar")

    async def test_no_language_and_no_restriction_autodetects(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            model = FakeWhisperModel()
            result = await _provider(model).transcribe([0] * 1600, 16000)
        self.assertNotIn("language", model.transcribe_calls[0])
        self.assertEqual(model.detect_calls, [])
        self.assertEqual(result.language, "en")

    async def test_restricted_detection_folds_persian_and_urdu_into_arabic(self) -> None:
        probs = [("fa", 0.40), ("ur", 0.15), ("ar", 0.10), ("en", 0.30), ("es", 0.05)]
        with patch.dict(os.environ, _clean_env(QANTARA_STT_LANGUAGES="en,ar"), clear=True):
            model = FakeWhisperModel(all_probs=probs, info=Info(language="ar", language_probability=1.0))
            result = await _provider(model).transcribe([0] * 1600, 16000)
        self.assertEqual(model.transcribe_calls[0]["language"], "ar")
        self.assertEqual(result.language, "ar")
        self.assertAlmostEqual(result.language_probability, 0.65)

    async def test_restricted_detection_picks_english_when_it_wins(self) -> None:
        probs = [("en", 0.55), ("fa", 0.2), ("de", 0.25)]
        with patch.dict(os.environ, _clean_env(QANTARA_STT_LANGUAGES="en, ar"), clear=True):
            model = FakeWhisperModel(all_probs=probs)
            result = await _provider(model).transcribe([0] * 1600, 16000)
        self.assertEqual(model.transcribe_calls[0]["language"], "en")
        self.assertEqual(result.language, "en")
        self.assertAlmostEqual(result.language_probability, 0.55)

    async def test_single_allowed_language_skips_detection(self) -> None:
        with patch.dict(os.environ, _clean_env(QANTARA_STT_LANGUAGES="ar"), clear=True):
            model = FakeWhisperModel()
            await _provider(model).transcribe([0] * 1600, 16000)
        self.assertEqual(model.detect_calls, [])
        self.assertEqual(model.transcribe_calls[0]["language"], "ar")

    async def test_detection_failure_falls_back_to_autodetect(self) -> None:
        with patch.dict(os.environ, _clean_env(QANTARA_STT_LANGUAGES="en,ar"), clear=True):
            model = FakeWhisperModel(detect_error=True)
            result = await _provider(model).transcribe([0] * 1600, 16000)
        self.assertNotIn("language", model.transcribe_calls[0])
        self.assertEqual(result.text, "hello world")

    def test_pick_restricted_language_helper(self) -> None:
        self.assertEqual(pick_restricted_language([("fa", 0.5), ("en", 0.3)], ["en", "ar"]), ("ar", 0.5))
        self.assertEqual(pick_restricted_language([("de", 0.9)], ["en", "ar"]), ("en", 0.0))
        # An explicitly allowed Persian is not folded into Arabic.
        self.assertEqual(pick_restricted_language([("fa", 0.5), ("ar", 0.3)], ["ar", "fa"]), ("fa", 0.5))


class FasterWhisperFilterTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, segments, **env) -> STTResult:
        with patch.dict(os.environ, _clean_env(**env), clear=True):
            return await _provider(FakeWhisperModel(segments=segments)).transcribe([0] * 1600, 16000)

    async def test_drops_no_speech_low_confidence_segment(self) -> None:
        result = await self._run([Seg(" real words"), Seg(" ghost", no_speech_prob=0.8, avg_logprob=-1.5)])
        self.assertEqual(result.text, "real words")

    async def test_keeps_no_speech_segment_with_good_logprob(self) -> None:
        result = await self._run([Seg(" quiet but sure", no_speech_prob=0.8, avg_logprob=-0.3)])
        self.assertEqual(result.text, "quiet but sure")

    async def test_drops_high_compression_ratio(self) -> None:
        result = await self._run([Seg(" ok"), Seg(" la la la la la la", compression_ratio=3.1)])
        self.assertEqual(result.text, "ok")

    async def test_drops_known_hallucinations(self) -> None:
        segments = [
            Seg(" Thank you for watching!"),
            Seg(" ترجمة نانسي قنقر"),
            Seg(" اشتركوا في القناة"),
            Seg(" Subtitles by the Amara.org community"),
        ]
        result = await self._run(segments)
        self.assertEqual(result.text, "")

    def test_hallucination_matcher_ignores_harakat_and_punctuation(self) -> None:
        self.assertTrue(is_known_hallucination("ترجمةُ نانسي قنقر."))
        self.assertTrue(is_known_hallucination("THANKS FOR WATCHING"))
        self.assertFalse(is_known_hallucination("Thank you, see you tomorrow"))
        self.assertFalse(is_known_hallucination("مرحبا"))

    async def test_speech_duration_after_vad_reported(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            model = FakeWhisperModel(info=Info(duration=3.0, duration_after_vad=1.75))
            result = await _provider(model).transcribe([0] * 1600, 16000)
        self.assertEqual(result.speech_duration_ms, 1750.0)
        self.assertTrue(model.transcribe_calls[0]["vad_filter"])


class FasterWhisperDecodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_float32_audio_passed_directly_and_converted_off_loop(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            model = FakeWhisperModel()
            provider = _provider(model)
            with patch.object(provider, "_pcm_to_float32", wraps=provider._pcm_to_float32) as convert:
                await provider.transcribe([0, 16384, -32768, 32767], 16000)
        audio = model.audio_seen[0]
        self.assertIsInstance(audio, np.ndarray)
        self.assertEqual(audio.dtype, np.float32)
        np.testing.assert_allclose(audio, [0.0, 0.5, -1.0, 32767 / 32768], rtol=1e-6)
        self.assertNotEqual(model.threads[0], threading.main_thread().name)
        self.assertEqual(convert.call_count, 1)

    async def test_out_of_range_samples_are_clipped(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            model = FakeWhisperModel()
            await _provider(model).transcribe([40000, -40000], 16000)
        np.testing.assert_allclose(model.audio_seen[0], [32767 / 32768, -1.0], rtol=1e-6)

    async def test_non_16k_audio_is_resampled(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            model = FakeWhisperModel()
            await _provider(model).transcribe([100] * 48000, 48000)
        self.assertEqual(len(model.audio_seen[0]), 16000)

    async def test_buffer_mutation_after_call_does_not_race(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            model = FakeWhisperModel()
            buffer = [1000] * 1600
            task = asyncio.ensure_future(_provider(model).transcribe(buffer, 16000))
            await asyncio.sleep(0)
            buffer.clear()
            await task
        self.assertEqual(len(model.audio_seen[0]), 1600)

    async def test_partial_uses_explicit_language_and_no_vad(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            model = FakeWhisperModel()
            await _provider(model).transcribe_partial([0] * 1600, 16000, language="ar")
        self.assertEqual(model.transcribe_calls[0]["language"], "ar")
        self.assertFalse(model.transcribe_calls[0]["vad_filter"])


class BeamSizeTests(unittest.TestCase):
    def test_default_beam_cpu_is_one(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertEqual(FasterWhisperSTTProvider(device="cpu").beam_size, 1)

    def test_default_beam_cuda_is_five(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertEqual(FasterWhisperSTTProvider(device="cuda").beam_size, 5)

    def test_env_override_and_invalid_value(self) -> None:
        with patch.dict(os.environ, _clean_env(QANTARA_WHISPER_BEAM_SIZE="3"), clear=True):
            self.assertEqual(FasterWhisperSTTProvider(device="cpu").beam_size, 3)
        with patch.dict(os.environ, _clean_env(QANTARA_WHISPER_BEAM_SIZE="lots"), clear=True):
            self.assertEqual(FasterWhisperSTTProvider(device="cpu").beam_size, 1)

    def test_beam_passed_to_transcribe(self) -> None:
        with patch.dict(os.environ, _clean_env(QANTARA_WHISPER_BEAM_SIZE="2"), clear=True):
            model = FakeWhisperModel()
            asyncio.run(_provider(model).transcribe([0] * 160, 16000))
        self.assertEqual(model.transcribe_calls[0]["beam_size"], 2)


if __name__ == "__main__":
    unittest.main()
