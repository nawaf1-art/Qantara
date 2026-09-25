"""Audit 2026-09-24 TTS fixes: Q-06a/b/d, V-3 (Piper), V-5 (Kokoro), SP-13, R-4.

All engines are fakes: no model is loaded and nothing is downloaded.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import numpy as np

from providers.tts.base import TTSProvider, VoiceSpec
from providers.tts.kokoro import KokoroTTSProvider
from providers.tts.piper import PiperTTSProvider, decode_pcm16le
from providers.tts.routing import (
    NO_VOICE_FOR_LANGUAGE,
    NoVoiceForLanguage,
    RoutedTTSProvider,
    ensure_voice_for_text,
    has_voice_for_language,
    languages_with_voices,
)
from providers.voice_registry import (
    VoiceRegistryError,
    load_voice_registry,
    validate_voice_entry,
    validate_voice_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_REGISTRY = REPO_ROOT / "identity" / "voice-registry" / "voices.json"
ARABIC_TEXT = "مرحبا، كيف حالك اليوم؟"
ENGLISH_TEXT = "Hello there, how are you today?"


def _entry(voice_id: str, engine: str, locale: str, model_path: str | None, **extra) -> dict:
    entry = {
        "voice_id": voice_id,
        "label": voice_id,
        "engine": engine,
        "locale": locale,
        "model_path": model_path,
        "base_sample_rate": 22050 if engine == "piper" else 24000,
        "defaults": {"rate": 1.0, "pitch": 0, "tone": "neutral"},
        "allowed_transforms": ["rate"],
    }
    entry.update(extra)
    return entry


class _TempRegistry:
    """A temp repo layout with a registry and placeholder Piper model files."""

    def __init__(self, entries: list[dict], model_files: list[str]) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        registry_dir = self.root / "identity" / "voice-registry"
        registry_dir.mkdir(parents=True)
        model_dir = self.root / "models" / "piper"
        model_dir.mkdir(parents=True)
        for name in model_files:
            (model_dir / name).write_text("placeholder", encoding="utf-8")
        self.path = registry_dir / "voices.json"
        self.path.write_text(json.dumps({"schema_version": "1.0", "voices": entries}), encoding="utf-8")

    def cleanup(self) -> None:
        self._tmp.cleanup()


def _piper_registry(*, with_english: bool = True, with_arabic: bool = True) -> _TempRegistry:
    entries = []
    files = []
    if with_english:
        entries.append(_entry("lessac", "piper", "en-US", "models/piper/en_US-lessac-medium.onnx"))
        files.append("en_US-lessac-medium.onnx")
    if with_arabic:
        entries.append(_entry("ar_JO-kareem-medium", "piper", "ar-JO", "models/piper/ar_JO-kareem-medium.onnx"))
        files.append("ar_JO-kareem-medium.onnx")
    return _TempRegistry(entries, files)


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeKModel:
    pass


class FakeKPipelineFactory:
    """Stands in for kokoro.KPipeline; records how it was constructed."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.built_on_event_loop: list[bool] = []
        self.thread_names: list[str] = []
        self.lock = threading.Lock()

    def __call__(self, **kwargs):
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        with self.lock:
            self.calls.append(kwargs)
            self.built_on_event_loop.append(on_loop)
            self.thread_names.append(threading.current_thread().name)
        model = kwargs.get("model", True)
        return _FakePipeline(model if isinstance(model, FakeKModel) else FakeKModel(), kwargs["lang_code"])


class _FakePipeline:
    def __init__(self, model: FakeKModel, lang_code: str) -> None:
        self.model = model
        self.lang_code = lang_code
        self.requests: list[tuple[str, str, float]] = []

    def __call__(self, text, voice, speed, split_pattern):
        self.requests.append((text, voice, speed))
        audio = np.concatenate([np.zeros(100, dtype=np.float32), np.full(2400, 0.5, dtype=np.float32)])
        yield ("g", "p", audio)


class FakeChunk:
    def __init__(self, samples: list[int], sample_rate: int = 22050) -> None:
        self.sample_rate = sample_rate
        self.audio_int16_bytes = np.asarray(samples, dtype="<i2").tobytes()


class FakePiperVoice:
    loads: list[tuple[str, str | None]] = []

    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self.requests: list[tuple[str, float]] = []

    @classmethod
    def load(cls, model_path, config_path=None):
        cls.loads.append((model_path, config_path))
        return cls(model_path)

    def synthesize(self, text, syn_config=None):
        self.requests.append((text, syn_config.length_scale))
        yield FakeChunk([1, -2, 3])
        yield FakeChunk([32767, -32768])


class FakeSynthesisConfig:
    def __init__(self, length_scale=None) -> None:
        self.length_scale = length_scale


def _fake_piper_module():
    FakePiperVoice.loads = []
    return SimpleNamespace(PiperVoice=FakePiperVoice, SynthesisConfig=FakeSynthesisConfig)


class ScriptedTTS(TTSProvider):
    """Minimal engine used to test routing decisions."""

    def __init__(self, kind: str, voices: list[tuple[str, str]], available: bool = True) -> None:
        self.kind = kind
        self._voices = {vid: loc for vid, loc in voices}
        self._available = available
        self.calls: list[tuple[str, str | None]] = []
        self.warmed = False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def default_voice_id(self) -> str | None:
        return next(iter(self._voices), None)

    def list_available_voices(self) -> list[dict]:
        return [{"voice_id": vid, "label": vid, "locale": loc} for vid, loc in self._voices.items()]

    def resolve_voice(self, voice_id):
        vid = voice_id if voice_id in self._voices else self.default_voice_id
        return VoiceSpec(voice_id=vid, label=vid, sample_rate=16000, locale=self._voices[vid]), None

    async def synthesize(self, text, voice_id=None, speech_rate=None, *, expressiveness=None):
        self.calls.append((text, voice_id))
        voice, _ = self.resolve_voice(voice_id)
        return [0], voice, None

    async def warmup(self) -> None:
        self.warmed = True


def _kokoro_like() -> ScriptedTTS:
    return ScriptedTTS("kokoro", [("af_heart", "en-US"), ("ef_dora", "es-ES"), ("ff_siwis", "fr-FR")])


def _piper_like() -> ScriptedTTS:
    return ScriptedTTS("piper", [("lessac", "en-US"), ("ar_JO-kareem-medium", "ar-JO")])


# --------------------------------------------------------------------------
# Registry (Q-06a/d, SP-13)
# --------------------------------------------------------------------------


class ShippedRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
        self.by_id = {v["voice_id"]: v for v in self.payload["voices"]}

    def test_shipped_registry_passes_manual_validation(self) -> None:
        self.assertEqual(validate_voice_registry(self.payload), [])

    def test_kokoro_spanish_and_french_voices_present(self) -> None:
        self.assertEqual(self.by_id["ef_dora"]["engine"], "kokoro")
        self.assertEqual(self.by_id["ef_dora"]["locale"], "es-ES")
        self.assertEqual(self.by_id["ff_siwis"]["engine"], "kokoro")
        self.assertEqual(self.by_id["ff_siwis"]["locale"], "fr-FR")

    def test_arabic_default_rate_leaves_slider_headroom(self) -> None:
        rate = self.by_id["ar_JO-kareem-medium"]["defaults"]["rate"]
        self.assertGreaterEqual(rate, 0.95)
        self.assertLessEqual(rate, 1.1)
        # Session rate 1.15 x voice default must stay below the 1.30 clamp.
        self.assertLess(1.15 * rate, 1.30)

    def test_english_piper_voice_uses_lessac_model(self) -> None:
        self.assertEqual(self.by_id["lessac"]["model_path"], "models/piper/en_US-lessac-medium.onnx")


class RegistryValidationTests(unittest.TestCase):
    def test_invalid_entry_is_skipped_with_warning(self) -> None:
        good = _entry("lessac", "piper", "en-US", "models/piper/x.onnx")
        bad_engine = _entry("weird", "espeak", "en-US", None)
        bad_rate = _entry("fast", "piper", "en-US", None, defaults={"rate": 9, "pitch": 0, "tone": "n"})
        missing = {"voice_id": "nolabel", "engine": "piper", "locale": "en-US"}
        registry = _TempRegistry([good, bad_engine, bad_rate, missing], [])
        self.addCleanup(registry.cleanup)
        with self.assertLogs("providers.voice_registry", level=logging.WARNING) as logs:
            entries = load_voice_registry(str(registry.path))
        self.assertEqual([e.voice_id for e in entries], ["lessac"])
        joined = "\n".join(logs.output)
        self.assertIn("weird", joined)
        self.assertIn("fast", joined)
        self.assertIn("nolabel", joined)

    def test_structurally_invalid_registry_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voices.json"
            path.write_text(json.dumps({"voices": {"not": "a list"}}), encoding="utf-8")
            with self.assertRaises(VoiceRegistryError):
                load_voice_registry(str(path))

    def test_validate_entry_reports_unknown_fields(self) -> None:
        errors = validate_voice_entry(_entry("a", "piper", "en-US", None, surprise=True))
        self.assertTrue(any("unknown fields" in e for e in errors))

    def test_validate_entry_rejects_nan_rate(self) -> None:
        errors = validate_voice_entry(
            _entry("a", "piper", "en-US", None, defaults={"rate": float("nan"), "pitch": 0, "tone": "n"})
        )
        self.assertTrue(any("defaults.rate" in e for e in errors))


# --------------------------------------------------------------------------
# Voice/locale guard (Q-06 fix 4)
# --------------------------------------------------------------------------


class VoiceGuardTests(unittest.TestCase):
    VOICES = [
        {"voice_id": "af_heart", "locale": "en-US"},
        {"voice_id": "ef_dora", "locale": "es-ES"},
        {"voice_id": "ar_JO-kareem-medium", "locale": "ar_JO"},
    ]

    def test_matching_voice_is_kept(self) -> None:
        voice, reason = ensure_voice_for_text(self.VOICES[0], self.VOICES, ENGLISH_TEXT)
        self.assertEqual(voice["voice_id"], "af_heart")
        self.assertIsNone(reason)

    def test_arabic_text_switches_to_arabic_voice(self) -> None:
        voice, reason = ensure_voice_for_text(self.VOICES[0], self.VOICES, ARABIC_TEXT)
        self.assertEqual(voice["voice_id"], "ar_JO-kareem-medium")
        self.assertIn("af_heart", reason)

    def test_arabic_text_without_arabic_voice_raises(self) -> None:
        with self.assertRaises(NoVoiceForLanguage) as ctx:
            ensure_voice_for_text(self.VOICES[0], self.VOICES[:2], ARABIC_TEXT, engine="kokoro")
        self.assertEqual(ctx.exception.reason, NO_VOICE_FOR_LANGUAGE)
        self.assertEqual(ctx.exception.language, "ar")
        self.assertIn(NO_VOICE_FOR_LANGUAGE, str(ctx.exception))
        self.assertIsInstance(ctx.exception, RuntimeError)

    def test_english_text_with_arabic_voice_switches_to_english(self) -> None:
        voice, _ = ensure_voice_for_text(self.VOICES[2], self.VOICES, ENGLISH_TEXT)
        self.assertEqual(voice["voice_id"], "af_heart")

    def test_declared_language_selects_language_voice(self) -> None:
        voice, _ = ensure_voice_for_text(self.VOICES[0], self.VOICES, "Hola, ¿qué tal?", "es")
        self.assertEqual(voice["voice_id"], "ef_dora")

    def test_declared_language_without_voice_raises(self) -> None:
        with self.assertRaises(NoVoiceForLanguage) as ctx:
            ensure_voice_for_text(self.VOICES[0], self.VOICES, "Bonjour tout le monde", "fr")
        self.assertEqual(ctx.exception.language, "fr")

    def test_text_script_beats_declared_language(self) -> None:
        # Turn declared Arabic, model answered in English: read it in English.
        voice, _ = ensure_voice_for_text(self.VOICES[2], self.VOICES, ENGLISH_TEXT, "ar")
        self.assertEqual(voice["voice_id"], "af_heart")

    def test_text_without_letters_keeps_voice(self) -> None:
        voice, reason = ensure_voice_for_text(self.VOICES[2], self.VOICES, "12:30 !!")
        self.assertEqual(voice["voice_id"], "ar_JO-kareem-medium")
        self.assertIsNone(reason)

    def test_gulf_code_switch_text_counts_as_arabic(self) -> None:
        voice, _ = ensure_voice_for_text(self.VOICES[0], self.VOICES, "ابغى الـ report بكرة الصبح")
        self.assertEqual(voice["voice_id"], "ar_JO-kareem-medium")

    def test_availability_helpers(self) -> None:
        provider = _kokoro_like()
        self.assertEqual(languages_with_voices(provider), {"en", "es", "fr"})
        self.assertTrue(has_voice_for_language(provider, "es"))
        self.assertTrue(has_voice_for_language(provider, "en-GB"))
        self.assertFalse(has_voice_for_language(provider, "ar"))
        self.assertFalse(has_voice_for_language(provider, "ja"))
        self.assertFalse(has_voice_for_language(None, "en"))
        self.assertFalse(has_voice_for_language(ScriptedTTS("x", [("a", "en-US")], available=False), "en"))


# --------------------------------------------------------------------------
# Routed provider (Q-06 fix 2)
# --------------------------------------------------------------------------


class RoutedProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.kokoro = _kokoro_like()
        self.piper = _piper_like()
        self.routed = RoutedTTSProvider([self.kokoro, self.piper])

    async def test_english_routes_to_kokoro(self) -> None:
        _, voice, reason = await self.routed.synthesize(ENGLISH_TEXT, voice_id="af_heart")
        self.assertEqual(voice.voice_id, "af_heart")
        self.assertEqual(self.kokoro.calls[-1][1], "af_heart")
        self.assertIsNone(reason)

    async def test_arabic_text_routes_to_piper_even_with_english_voice(self) -> None:
        _, voice, reason = await self.routed.synthesize(ARABIC_TEXT, voice_id="af_heart")
        self.assertEqual(voice.voice_id, "ar_JO-kareem-medium")
        self.assertEqual(self.piper.calls[-1][1], "ar_JO-kareem-medium")
        self.assertEqual(self.kokoro.calls, [])
        self.assertIn("ar_JO-kareem-medium", reason)

    async def test_spanish_language_prefers_kokoro_voice(self) -> None:
        _, voice, _ = await self.routed.synthesize("Hola amigo", voice_id="af_heart", language="es")
        self.assertEqual(voice.voice_id, "ef_dora")

    async def test_piper_voice_request_goes_to_piper(self) -> None:
        _, voice, _ = await self.routed.synthesize(ENGLISH_TEXT, voice_id="lessac")
        self.assertEqual(voice.voice_id, "lessac")
        self.assertEqual(self.piper.calls[-1][1], "lessac")

    async def test_no_arabic_voice_anywhere_raises(self) -> None:
        routed = RoutedTTSProvider([self.kokoro, ScriptedTTS("piper", [("lessac", "en-US")])])
        with self.assertRaises(NoVoiceForLanguage):
            await routed.synthesize(ARABIC_TEXT, voice_id="af_heart")

    async def test_unavailable_engine_is_ignored(self) -> None:
        routed = RoutedTTSProvider([self.kokoro, ScriptedTTS("piper", [("ar", "ar-JO")], available=False)])
        self.assertNotIn("ar", {v["voice_id"] for v in routed.list_available_voices()})
        with self.assertRaises(NoVoiceForLanguage):
            await routed.synthesize(ARABIC_TEXT)

    def test_catalog_is_union_with_engine_tags(self) -> None:
        voices = {v["voice_id"]: v for v in self.routed.list_available_voices()}
        self.assertEqual(voices["af_heart"]["engine"], "kokoro")
        self.assertEqual(voices["ar_JO-kareem-medium"]["engine"], "piper")
        self.assertEqual(self.routed.default_voice_id, "af_heart")
        self.assertEqual(self.routed.voice_for_language("ar"), "ar_JO-kareem-medium")
        self.assertEqual(self.routed.voice_for_language("fr"), "ff_siwis")
        self.assertIsNone(self.routed.voice_for_language("ja"))
        self.assertEqual(self.routed.engines, ["kokoro", "piper"])

    def test_resolve_voice_delegates_to_owner(self) -> None:
        voice, _ = self.routed.resolve_voice("ar_JO-kareem-medium")
        self.assertEqual(voice.locale, "ar-JO")

    async def test_warmup_reaches_engines(self) -> None:
        await self.routed.warmup()
        self.assertTrue(self.kokoro.warmed)
        self.assertTrue(self.piper.warmed)


# --------------------------------------------------------------------------
# Kokoro (V-5)
# --------------------------------------------------------------------------


class KokoroProviderTests(unittest.IsolatedAsyncioTestCase):
    def _provider(self, **kwargs) -> tuple[KokoroTTSProvider, FakeKPipelineFactory]:
        factory = FakeKPipelineFactory()
        env = {"QANTARA_VOICE_REGISTRY": str(SHIPPED_REGISTRY)}
        with patch.dict(os.environ, env):
            provider = KokoroTTSProvider(pipeline_factory=factory, spacy_model_available=lambda _n: True, **kwargs)
        return provider, factory

    async def test_pipeline_built_off_event_loop(self) -> None:
        provider, factory = self._provider()
        samples, voice, _ = await provider.synthesize(ENGLISH_TEXT, voice_id="af_heart")
        self.assertEqual(factory.built_on_event_loop, [False])
        self.assertEqual(factory.calls[0]["lang_code"], "a")
        self.assertEqual(voice.voice_id, "af_heart")
        self.assertTrue(samples)

    async def test_model_shared_across_language_pipelines(self) -> None:
        provider, factory = self._provider()
        await provider.synthesize(ENGLISH_TEXT, voice_id="af_heart")
        await provider.synthesize("Hola, ¿cómo estás?", voice_id="ef_dora")
        await provider.synthesize("Bonjour à tous", voice_id="ff_siwis")
        self.assertEqual([c["lang_code"] for c in factory.calls], ["a", "e", "f"])
        self.assertNotIn("model", factory.calls[0])
        first_model = provider._pipelines["a"].model
        self.assertIs(factory.calls[1]["model"], first_model)
        self.assertIs(factory.calls[2]["model"], first_model)

    async def test_concurrent_first_requests_build_one_pipeline(self) -> None:
        provider, factory = self._provider()
        await asyncio.gather(*[provider.synthesize(ENGLISH_TEXT, voice_id="af_heart") for _ in range(4)])
        self.assertEqual(len(factory.calls), 1)

    async def test_warmup_builds_pipeline_and_runs_short_synthesis(self) -> None:
        provider, factory = self._provider()
        await provider.warmup()
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(factory.built_on_event_loop, [False])
        pipeline = provider._pipelines["a"]
        self.assertEqual(len(pipeline.requests), 1)
        await provider.synthesize(ENGLISH_TEXT)
        self.assertEqual(len(factory.calls), 1)

    async def test_arabic_text_raises_no_voice_for_language(self) -> None:
        provider, factory = self._provider()
        with self.assertRaises(NoVoiceForLanguage) as ctx:
            await provider.synthesize(ARABIC_TEXT, voice_id="af_heart")
        self.assertEqual(ctx.exception.reason, "no_voice_for_language")
        self.assertEqual(factory.calls, [])

    async def test_spanish_language_hint_switches_voice(self) -> None:
        provider, factory = self._provider()
        _, voice, reason = await provider.synthesize("Hola amigo", voice_id="af_heart", language="es")
        self.assertEqual(voice.voice_id, "ef_dora")
        self.assertEqual(factory.calls[0]["lang_code"], "e")
        self.assertIsNotNone(reason)

    async def test_offline_without_spacy_model_fails_clearly(self) -> None:
        factory = FakeKPipelineFactory()
        with patch.dict(os.environ, {"QANTARA_OFFLINE": "1", "QANTARA_VOICE_REGISTRY": str(SHIPPED_REGISTRY)}):
            provider = KokoroTTSProvider(pipeline_factory=factory, spacy_model_available=lambda _n: False)
            with self.assertRaisesRegex(RuntimeError, "en_core_web_sm"):
                await provider.synthesize(ENGLISH_TEXT, voice_id="af_heart")
            # Non-English pipelines don't need spaCy.
            await provider.synthesize("Hola amigo", voice_id="ef_dora")
        self.assertEqual([c["lang_code"] for c in factory.calls], ["e"])

    async def test_online_without_spacy_model_still_builds(self) -> None:
        factory = FakeKPipelineFactory()
        env = {"QANTARA_OFFLINE": "", "HF_HUB_OFFLINE": "", "QANTARA_VOICE_REGISTRY": str(SHIPPED_REGISTRY)}
        with patch.dict(os.environ, env):
            provider = KokoroTTSProvider(pipeline_factory=factory, spacy_model_available=lambda _n: False)
            await provider.synthesize(ENGLISH_TEXT, voice_id="af_heart")
        self.assertEqual(len(factory.calls), 1)

    def test_builtin_catalog_includes_spanish_and_french(self) -> None:
        with patch.dict(os.environ, {"QANTARA_VOICE_REGISTRY": "/nonexistent/voices.json"}):
            provider = KokoroTTSProvider(pipeline_factory=FakeKPipelineFactory())
        locales = {v["voice_id"]: v["locale"] for v in provider.list_available_voices()}
        self.assertEqual(locales["ef_dora"], "es-ES")
        self.assertEqual(locales["ff_siwis"], "fr-FR")

    async def test_leading_silence_trimmed(self) -> None:
        provider, _ = self._provider()
        samples, _, _ = await provider.synthesize(ENGLISH_TEXT, voice_id="af_heart")
        # 100 leading zeros minus the 20-sample lead-in are trimmed.
        self.assertEqual(len(samples), 2400 + 20)


# --------------------------------------------------------------------------
# Piper (V-3, SP-13, Q-06b)
# --------------------------------------------------------------------------


class PiperProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        env = patch.dict(os.environ, {"QANTARA_PIPER_MODEL": "", "QANTARA_PIPER_VOICE": ""})
        env.start()
        self.addCleanup(env.stop)

    async def test_in_process_voice_loaded_once_and_decoded(self) -> None:
        registry = _piper_registry()
        self.addCleanup(registry.cleanup)
        module = _fake_piper_module()
        provider = PiperTTSProvider(registry_path=str(registry.path), piper_module=module)
        self.assertTrue(provider.in_process)
        with patch("providers.tts.piper.asyncio.create_subprocess_exec") as spawn:
            first, voice, _ = await provider.synthesize("Hello there.", voice_id="lessac", speech_rate=1.25)
            second, _, _ = await provider.synthesize("Second sentence.", voice_id="lessac")
        spawn.assert_not_called()
        self.assertEqual(first, [1, -2, 3, 32767, -32768])
        self.assertEqual(second, first)
        self.assertEqual(len(FakePiperVoice.loads), 1)
        self.assertEqual(voice.voice_id, "lessac")

    async def test_in_process_passes_length_scale(self) -> None:
        registry = _piper_registry()
        self.addCleanup(registry.cleanup)
        provider = PiperTTSProvider(registry_path=str(registry.path), piper_module=_fake_piper_module())
        await provider.synthesize("Hello.", voice_id="lessac", speech_rate=1.25)
        loaded = provider._loaded_voices[provider.voices["lessac"].model_path]
        self.assertAlmostEqual(loaded.requests[-1][1], 0.8)

    async def test_subprocess_fallback_when_in_process_disabled(self) -> None:
        registry = _piper_registry()
        self.addCleanup(registry.cleanup)
        provider = PiperTTSProvider(
            registry_path=str(registry.path), piper_module=_fake_piper_module(), in_process=False
        )

        class Proc:
            returncode = 0

            async def communicate(self, _input=None):
                return np.asarray([5, -6], dtype="<i2").tobytes() + b"\x01", b""

        with patch("providers.tts.piper.asyncio.create_subprocess_exec", return_value=Proc()) as spawn:
            samples, _, _ = await provider.synthesize("Hello.", voice_id="lessac")
        spawn.assert_called_once()
        self.assertEqual(samples, [5, -6])

    async def test_arabic_text_with_english_voice_switches_to_arabic(self) -> None:
        registry = _piper_registry()
        self.addCleanup(registry.cleanup)
        provider = PiperTTSProvider(registry_path=str(registry.path), piper_module=_fake_piper_module())
        _, voice, reason = await provider.synthesize(ARABIC_TEXT, voice_id="lessac")
        self.assertEqual(voice.voice_id, "ar_JO-kareem-medium")
        self.assertIn("lessac", reason)

    async def test_english_text_with_only_arabic_voice_raises(self) -> None:
        registry = _piper_registry(with_english=False)
        self.addCleanup(registry.cleanup)
        provider = PiperTTSProvider(registry_path=str(registry.path), piper_module=_fake_piper_module())
        with self.assertRaises(NoVoiceForLanguage):
            await provider.synthesize(ENGLISH_TEXT)

    def test_single_voice_fallback_lists_voices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "en_US-lessac-medium.onnx"
            model.write_text("placeholder", encoding="utf-8")
            provider = PiperTTSProvider(
                registry_path=str(Path(tmp) / "missing.json"),
                voice_path=str(model),
                piper_module=_fake_piper_module(),
            )
            voices = provider.list_available_voices()
        self.assertEqual([v["voice_id"] for v in voices], ["lessac"])
        self.assertEqual(voices[0]["defaults"]["rate"], 1.0)
        self.assertEqual(voices[0]["allowed_transforms"], ["rate"])

    def test_piper_model_env_honored_with_registry(self) -> None:
        registry = _piper_registry()
        self.addCleanup(registry.cleanup)
        extra = registry.root / "models" / "piper" / "es_ES-davefx-medium.onnx"
        extra.write_text("placeholder", encoding="utf-8")
        with patch.dict(os.environ, {"QANTARA_PIPER_MODEL": str(extra)}):
            provider = PiperTTSProvider(registry_path=str(registry.path), piper_module=_fake_piper_module())
        self.assertEqual(provider.default_voice_id, "es_ES-davefx-medium")
        voice, _ = provider.resolve_voice(None)
        self.assertEqual(voice.locale, "es-ES")
        ids = [v["voice_id"] for v in provider.list_available_voices()]
        self.assertIn("lessac", ids)
        self.assertIn("ar_JO-kareem-medium", ids)

    def test_piper_model_env_matching_registry_entry_selects_it(self) -> None:
        registry = _piper_registry()
        self.addCleanup(registry.cleanup)
        arabic = registry.root / "models" / "piper" / "ar_JO-kareem-medium.onnx"
        with patch.dict(os.environ, {"QANTARA_PIPER_MODEL": str(arabic)}):
            provider = PiperTTSProvider(registry_path=str(registry.path), piper_module=_fake_piper_module())
        self.assertEqual(provider.default_voice_id, "ar_JO-kareem-medium")
        self.assertEqual(len(provider.voices), 2)

    def test_unavailable_without_piper_package(self) -> None:
        registry = _piper_registry()
        self.addCleanup(registry.cleanup)
        with patch("providers.tts.piper._module_importable", return_value=False):
            provider = PiperTTSProvider(registry_path=str(registry.path))
        self.assertFalse(provider.available)
        self.assertFalse(provider.in_process)

    def test_decode_pcm16le(self) -> None:
        self.assertEqual(decode_pcm16le(b"\x01\x00\xff\xff\x00"), [1, -1])
        self.assertEqual(decode_pcm16le(b""), [])


# --------------------------------------------------------------------------
# Factory default (R-4)
# --------------------------------------------------------------------------


class FactoryDefaultTests(unittest.TestCase):
    def _create(self, *, kokoro: bool, piper_available: bool, env_value: str | None = None):
        from providers import factory

        env = dict(os.environ)
        env.pop("QANTARA_TTS_PROVIDER", None)
        if env_value is not None:
            env["QANTARA_TTS_PROVIDER"] = env_value
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(factory, "_module_available", side_effect=lambda name: kokoro and name == "kokoro"),
            patch("providers.tts.kokoro._module_importable", return_value=kokoro),
            patch.object(PiperTTSProvider, "available", new_callable=PropertyMock, return_value=piper_available),
        ):
            return factory.create_tts_provider()

    def test_unset_with_kokoro_and_piper_is_routed(self) -> None:
        provider = self._create(kokoro=True, piper_available=True)
        self.assertIsInstance(provider, RoutedTTSProvider)
        self.assertEqual([p.kind for p in provider.providers], ["kokoro", "piper"])

    def test_unset_with_only_kokoro_is_kokoro(self) -> None:
        self.assertIsInstance(self._create(kokoro=True, piper_available=False), KokoroTTSProvider)

    def test_unset_with_only_piper_is_piper(self) -> None:
        self.assertIsInstance(self._create(kokoro=False, piper_available=True), PiperTTSProvider)

    def test_unset_with_nothing_is_unavailable_piper(self) -> None:
        provider = self._create(kokoro=False, piper_available=False)
        # `available` is patched only inside _create, so asserting it here would
        # depend on whether this machine has real Piper voices installed.
        self.assertIsInstance(provider, PiperTTSProvider)

    def test_explicit_routed_and_auto(self) -> None:
        self.assertIsInstance(self._create(kokoro=True, piper_available=False, env_value="routed"), RoutedTTSProvider)
        self.assertIsInstance(self._create(kokoro=True, piper_available=False, env_value="auto"), KokoroTTSProvider)

    def test_explicit_piper_still_piper(self) -> None:
        self.assertIsInstance(self._create(kokoro=True, piper_available=True, env_value="piper"), PiperTTSProvider)


if __name__ == "__main__":
    unittest.main()
