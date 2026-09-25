from __future__ import annotations

import asyncio
import importlib.util
import os
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

from providers.tts.base import TTSProvider, VoiceSpec
from providers.tts.routing import ensure_voice_for_text
from providers.voice_registry import default_registry_path, filter_registry_voices

KOKORO_SAMPLE_RATE = 24000
KOKORO_DEFAULT_VOICE = os.environ.get("QANTARA_KOKORO_VOICE", "af_heart")
KOKORO_DEFAULT_REPO_ID = os.environ.get("QANTARA_KOKORO_REPO_ID", "hexgrad/Kokoro-82M")
KOKORO_DEFAULT_DEVICE = os.environ.get("QANTARA_KOKORO_DEVICE", "cpu")
KOKORO_DEFAULTS: dict[str, tuple[str, str]] = {
    "af_heart": ("Heart", "en-US"),
    "af_bella": ("Bella", "en-US"),
    "af_sarah": ("Sarah", "en-US"),
    "am_adam": ("Adam", "en-US"),
    "am_michael": ("Michael", "en-US"),
    "bf_emma": ("Emma", "en-GB"),
    "bf_isabella": ("Isabella", "en-GB"),
    "bm_george": ("George", "en-GB"),
    "bm_lewis": ("Lewis", "en-GB"),
    "af_nicole": ("Nicole", "en-US"),
    "af_sky": ("Sky", "en-US"),
    "ef_dora": ("Dora (Spanish)", "es-ES"),
    "ff_siwis": ("Siwis (French)", "fr-FR"),
}
# misaki's English G2P needs this spaCy model and, when it is missing,
# pip-installs it from GitHub at runtime (spacy.cli.download).
KOKORO_SPACY_MODEL = "en_core_web_sm"
_ENGLISH_LANG_CODES = frozenset({"a", "b"})
_TRUTHY = {"1", "true", "yes", "on"}
WARMUP_TEXT = "Hello."


def _offline_mode() -> bool:
    return any(
        os.environ.get(name, "").strip().lower() in _TRUTHY
        for name in ("QANTARA_OFFLINE", "HF_HUB_OFFLINE")
    )


def _spacy_model_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _module_importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class KokoroTTSProvider(TTSProvider):
    kind = "kokoro"

    def __init__(
        self,
        voice_id: str | None = None,
        repo_id: str | None = None,
        device: str | None = None,
        *,
        pipeline_factory: Callable[..., Any] | None = None,
        spacy_model_available: Callable[[str], bool] | None = None,
    ) -> None:
        self._default_voice_id = voice_id or KOKORO_DEFAULT_VOICE
        self.repo_id = repo_id or KOKORO_DEFAULT_REPO_ID
        self.device = device or KOKORO_DEFAULT_DEVICE
        self.registry_path = os.environ.get("QANTARA_VOICE_REGISTRY") or default_registry_path()
        self._import_error: Exception | None = None
        self._pipelines: dict[str, object] = {}
        # One KModel shared across language pipelines (kokoro allows passing
        # model=<KModel> to KPipeline), so es/fr don't reload the weights.
        self._shared_model: object | None = None
        # Pipelines are built on worker threads (never on the event loop);
        # the lock prevents two concurrent first requests building twice.
        self._pipeline_lock = threading.Lock()
        self._spacy_model_available = spacy_model_available or _spacy_model_installed
        self._registry_entries = {
            entry.voice_id: entry for entry in filter_registry_voices("kokoro", self.registry_path)
        }
        self._registry_voices = self._load_registry_voices()
        # Importing kokoro pulls in torch (seconds). Defer the import to the
        # worker thread that builds the first pipeline; only probe here.
        self._KPipeline: Callable[..., Any] | None = pipeline_factory
        self._importable = pipeline_factory is not None or _module_importable("kokoro")
        if not self._importable:
            self._import_error = ModuleNotFoundError("No module named 'kokoro'")

    @property
    def available(self) -> bool:
        return self._importable and self._import_error is None

    @property
    def default_voice_id(self) -> str | None:
        if self._default_voice_id in self._registry_voices:
            return self._default_voice_id
        if self._registry_voices:
            return next(iter(self._registry_voices))
        return self._default_voice_id

    def _voice_catalog(self) -> dict[str, VoiceSpec]:
        return self._registry_voices or {
            voice_id: VoiceSpec(
                voice_id=voice_id,
                label=label,
                sample_rate=KOKORO_SAMPLE_RATE,
                locale=locale,
            )
            for voice_id, (label, locale) in KOKORO_DEFAULTS.items()
        }

    def list_available_voices(self) -> list[dict]:
        return [
            {
                "voice_id": voice.voice_id,
                "label": voice.label,
                "locale": voice.locale,
                "sample_rate": voice.sample_rate,
                "defaults": dict(voice.defaults or {}),
                "allowed_transforms": list(voice.allowed_transforms or []),
            }
            for voice in self._voice_catalog().values()
        ]

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        requested = voice_id or self.default_voice_id or KOKORO_DEFAULT_VOICE
        fallback_reason = None
        if requested in self._registry_voices:
            return self._registry_voices[requested], None
        if requested in KOKORO_DEFAULTS:
            return self._builtin_voice(requested), None

        fallback_target = self.default_voice_id or KOKORO_DEFAULT_VOICE
        fallback_reason = f"requested voice '{requested}' unavailable; using '{fallback_target}'"
        if fallback_target in self._registry_voices:
            return self._registry_voices[fallback_target], fallback_reason
        return self._builtin_voice(fallback_target), fallback_reason

    @staticmethod
    def _builtin_voice(voice_id: str) -> VoiceSpec:
        label, locale = KOKORO_DEFAULTS[voice_id]
        return VoiceSpec(
            voice_id=voice_id,
            label=label,
            sample_rate=KOKORO_SAMPLE_RATE,
            locale=locale,
            defaults={"rate": 1.0, "pitch": 0, "tone": "neutral"},
            allowed_transforms=["rate"],
        )

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
        *,
        expressiveness: float | None = None,  # noqa: ARG002 — not used by Kokoro
        language: str | None = None,
    ) -> tuple[list[int], VoiceSpec, str | None]:
        if not self.available:
            raise RuntimeError(f"kokoro unavailable: {self._import_error}")

        voice, fallback_reason = self.resolve_voice(voice_id)
        catalog = self._voice_catalog()
        chosen, guard_reason = ensure_voice_for_text(
            voice, list(catalog.values()), text, language, engine=self.kind
        )
        if chosen is not voice:
            voice = chosen if chosen.voice_id in self._registry_voices else self.resolve_voice(chosen.voice_id)[0]
            fallback_reason = guard_reason
        speed = speech_rate if isinstance(speech_rate, (int, float)) else 1.0
        speed = max(0.85, min(1.30, float(speed)))

        # Pipeline construction (model load) and synthesis both run on a
        # worker thread so the event loop stays responsive for barge-in,
        # VAD, and WebSocket control messages.
        samples = await asyncio.to_thread(
            self._synthesize_blocking, text, voice.voice_id, speed
        )
        return samples, voice, fallback_reason

    async def warmup(self, voice_id: str | None = None, *, synthesize: bool = True) -> None:
        """Build the pipeline (and load the voice pack) off the event loop.

        Call once at gateway startup so the first real reply does not pay
        the model load. Errors propagate so the caller can log them.
        """
        if not self.available:
            raise RuntimeError(f"kokoro unavailable: {self._import_error}")
        voice, _ = self.resolve_voice(voice_id)
        if synthesize:
            await asyncio.to_thread(self._synthesize_blocking, WARMUP_TEXT, voice.voice_id, 1.0)
        else:
            await asyncio.to_thread(self._ensure_pipeline, self._lang_code_for_voice(voice.voice_id))

    def _synthesize_blocking(self, text: str, voice_id: str, speed: float) -> list[int]:
        pipeline = self._ensure_pipeline(self._lang_code_for_voice(voice_id))
        return self._synthesize_sync(pipeline, text, voice_id, speed)

    def _synthesize_sync(
        self,
        pipeline: object,
        text: str,
        voice_id: str,
        speed: float,
    ) -> list[int]:
        """Run Kokoro synthesis on a thread pool worker."""
        chunks = []
        generator = pipeline(text, voice=voice_id, speed=speed, split_pattern=r"\n+")
        for _, _, audio in generator:
            if audio is None:
                continue
            chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))

        if not chunks:
            return []

        merged = np.concatenate(chunks)

        # Trim leading silence/noise (samples below threshold at the start)
        threshold = 0.01
        head = merged[: KOKORO_SAMPLE_RATE // 4]  # check first 250ms
        loud = np.flatnonzero(np.abs(head) > threshold)
        if loud.size:
            start_idx = max(0, int(loud[0]) - 20)  # keep 20 samples before first real audio
            if start_idx > 0:
                merged = merged[start_idx:]
        merged = np.array(merged, dtype=np.float32, copy=True)

        # Apply a short fade-in (2ms) to remove onset click/buzz
        fade_samples = min(48, len(merged))  # 48 samples at 24kHz = 2ms
        if fade_samples > 0:
            fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
            merged[:fade_samples] *= fade

        # Apply a short fade-out (2ms) to remove end click
        if fade_samples > 0 and len(merged) > fade_samples:
            fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
            merged[-fade_samples:] *= fade_out

        clipped = np.clip(merged, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tolist()

    def _pipeline_factory(self) -> Callable[..., Any]:
        if self._KPipeline is None:
            try:
                from kokoro import KPipeline  # type: ignore
            except Exception as exc:
                self._import_error = exc
                raise RuntimeError(f"kokoro unavailable: {exc}") from exc
            self._KPipeline = KPipeline
        return self._KPipeline

    def _check_offline_prerequisites(self, lang_code: str) -> None:
        if lang_code not in _ENGLISH_LANG_CODES:
            return
        if self._spacy_model_available(KOKORO_SPACY_MODEL):
            return
        if _offline_mode():
            raise RuntimeError(
                f"kokoro English voices need the spaCy model '{KOKORO_SPACY_MODEL}', "
                "which is not installed. Offline mode (QANTARA_OFFLINE/HF_HUB_OFFLINE) "
                "forbids the runtime download misaki would attempt; install it first "
                f"with `python -m spacy download {KOKORO_SPACY_MODEL}`."
            )

    def _ensure_pipeline(self, lang_code: str):
        pipeline = self._pipelines.get(lang_code)
        if pipeline is not None:
            return pipeline
        with self._pipeline_lock:
            pipeline = self._pipelines.get(lang_code)
            if pipeline is not None:
                return pipeline
            self._check_offline_prerequisites(lang_code)
            factory = self._pipeline_factory()
            kwargs: dict[str, Any] = {
                "lang_code": lang_code,
                "repo_id": self.repo_id,
                "device": self.device,
            }
            if self._shared_model is not None:
                kwargs["model"] = self._shared_model
            pipeline = factory(**kwargs)
            model = getattr(pipeline, "model", None)
            if self._shared_model is None and model is not None and not isinstance(model, bool):
                self._shared_model = model
            self._pipelines[lang_code] = pipeline
            return pipeline

    @staticmethod
    def _lang_code_for_voice(voice_id: str) -> str:
        return voice_id.split("_", 1)[0][0]

    def _load_registry_voices(self) -> dict[str, VoiceSpec]:
        voices: dict[str, VoiceSpec] = {}
        for entry in filter_registry_voices("kokoro", self.registry_path):
            voices[entry.voice_id] = VoiceSpec(
                voice_id=entry.voice_id,
                label=entry.label,
                sample_rate=entry.sample_rate or KOKORO_SAMPLE_RATE,
                locale=entry.locale,
                defaults=entry.defaults,
                allowed_transforms=entry.allowed_transforms,
            )
        return voices
