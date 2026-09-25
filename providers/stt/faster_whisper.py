from __future__ import annotations

import asyncio
import os
import re
import threading
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

from providers.stt.base import STTProvider, STTResult

DEFAULT_MODEL = "small"
WHISPER_SAMPLE_RATE = 16000

# Segment filters (V-6). A segment is dropped when Whisper itself thinks it
# is probably not speech *and* it is unsure of the words, when the text is
# highly repetitive, or when it is a known hallucination on noise/silence.
NO_SPEECH_PROB_THRESHOLD = 0.6
LOW_AVG_LOGPROB_THRESHOLD = -1.0
COMPRESSION_RATIO_THRESHOLD = 2.4
KNOWN_HALLUCINATIONS: tuple[str, ...] = (
    "thank you for watching",
    "thanks for watching",
    "subtitles by",
    "ترجمة نانسي قنقر",
    "اشتركوا في القناة",
)
# Gulf Arabic is frequently detected as Persian/Urdu/Pashto.
ARABIC_DETECTION_FAMILY = frozenset({"ar", "fa", "ur", "ps"})

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_phrase(text: str) -> str:
    kept = []
    for char in unicodedata.normalize("NFKC", text).lower():
        category = unicodedata.category(char)
        if category.startswith(("M", "P", "S")) or char == "ـ":  # marks, punctuation, tatweel
            kept.append(" " if category.startswith(("P", "S")) else "")
            continue
        kept.append(char)
    return _WHITESPACE_RE.sub(" ", "".join(kept)).strip()


_NORMALIZED_HALLUCINATIONS = tuple(_normalize_phrase(p) for p in KNOWN_HALLUCINATIONS)


def is_known_hallucination(text: str) -> bool:
    normalized = _normalize_phrase(text)
    return bool(normalized) and any(phrase in normalized for phrase in _NORMALIZED_HALLUCINATIONS)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def keep_segment(segment: Any) -> bool:
    text = str(getattr(segment, "text", "") or "")
    if not text.strip():
        return False
    no_speech = _number(getattr(segment, "no_speech_prob", None))
    avg_logprob = _number(getattr(segment, "avg_logprob", None))
    if (
        no_speech is not None
        and avg_logprob is not None
        and no_speech > NO_SPEECH_PROB_THRESHOLD
        and avg_logprob < LOW_AVG_LOGPROB_THRESHOLD
    ):
        return False
    compression = _number(getattr(segment, "compression_ratio", None))
    if compression is not None and compression > COMPRESSION_RATIO_THRESHOLD:
        return False
    return not is_known_hallucination(text)


def parse_language_list(raw: str | None) -> list[str]:
    languages: list[str] = []
    for item in (raw or "").split(","):
        code = item.strip().replace("_", "-").split("-", 1)[0].lower()
        if code and code not in languages:
            languages.append(code)
    return languages


def pick_restricted_language(
    all_language_probs: Iterable[tuple[str, float]],
    allowed: Sequence[str],
) -> tuple[str, float]:
    """Best allowed language and its probability.

    When ``ar`` is allowed, fa/ur/ps probability mass is added to it (unless
    that language is itself explicitly allowed).
    """
    scores = {code: 0.0 for code in allowed}
    fold_into_arabic = "ar" in scores
    for language, probability in all_language_probs:
        code = str(language).lower()
        if code not in scores and fold_into_arabic and code in ARABIC_DETECTION_FAMILY:
            code = "ar"
        if code in scores:
            scores[code] += float(probability)
    best = max(allowed, key=lambda code: scores[code])
    return best, round(scores[best], 6)


def _default_beam_size(device: str) -> int:
    return 5 if device.strip().lower().startswith("cuda") else 1


def _resolve_beam_size(device: str) -> int:
    raw = os.environ.get("QANTARA_WHISPER_BEAM_SIZE", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _default_beam_size(device)


class FasterWhisperSTTProvider(STTProvider):
    kind = "faster_whisper"

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        partial_window_sec: float | None = None,
    ) -> None:
        self.model_name = model_name or os.environ.get("QANTARA_WHISPER_MODEL", DEFAULT_MODEL)
        self.device = device or os.environ.get("QANTARA_WHISPER_DEVICE", "cpu")
        self.compute_type = compute_type or os.environ.get("QANTARA_WHISPER_COMPUTE", "int8")
        self.partial_window_sec = partial_window_sec or float(
            os.environ.get("QANTARA_WHISPER_PARTIAL_WINDOW_SEC", "2.0")
        )
        self.beam_size = _resolve_beam_size(self.device)
        self.allowed_languages = parse_language_list(os.environ.get("QANTARA_STT_LANGUAGES"))
        self._model = None
        self._import_error = None
        # _ensure_model runs on worker threads (asyncio.to_thread); the lock
        # prevents two concurrent callers from loading the model twice.
        self._model_init_lock = threading.Lock()

        try:
            from faster_whisper import WhisperModel  # type: ignore

            self._WhisperModel = WhisperModel
        except Exception as exc:
            self._WhisperModel = None
            self._import_error = exc

    @property
    def available(self) -> bool:
        return self._WhisperModel is not None

    def _ensure_model(self):
        if not self.available:
            raise RuntimeError(f"faster-whisper unavailable: {self._import_error}")
        if self._model is None:
            with self._model_init_lock:
                if self._model is None:
                    self._model = self._WhisperModel(
                        self.model_name,
                        device=self.device,
                        compute_type=self.compute_type,
                    )
        return self._model

    @staticmethod
    def _snapshot(samples: Any) -> Any:
        """Cheap C-level copy taken on the event loop.

        The caller's buffer (e.g. ``session.recent_pcm``) keeps receiving
        audio while the worker thread runs, so it must not be read there.
        """
        if isinstance(samples, (bytes, bytearray, memoryview)):
            return bytes(samples)
        if type(samples).__module__ == "numpy" and hasattr(samples, "copy"):
            return samples.copy()
        return list(samples)

    @staticmethod
    def _pcm_to_float32(samples: Any, sample_rate: int):
        """PCM16 -> float32 in [-1, 1] at 16 kHz, vectorized with numpy."""
        import numpy as np

        if isinstance(samples, (bytes, bytearray, memoryview)):
            usable = len(samples) - (len(samples) % 2)
            pcm = np.frombuffer(bytes(samples[:usable]), dtype="<i2")
        else:
            pcm = np.asarray(samples)
            if pcm.dtype != np.int16:
                pcm = np.clip(pcm.astype(np.int64, copy=False), -32768, 32767).astype(np.int16)
        audio = pcm.astype(np.float32) / 32768.0
        if sample_rate and sample_rate != WHISPER_SAMPLE_RATE and audio.size:
            target_len = max(1, int(round(audio.size * WHISPER_SAMPLE_RATE / sample_rate)))
            positions = np.linspace(0.0, audio.size - 1, num=target_len)
            audio = np.interp(positions, np.arange(audio.size), audio).astype(np.float32)
        return audio

    async def transcribe(
        self,
        samples: list[int],
        sample_rate: int,
        language: str | None = None,
    ) -> STTResult:
        snapshot = self._snapshot(samples)
        return await asyncio.to_thread(
            self._transcribe_sync, snapshot, sample_rate, language, True, True
        )

    def _detect_restricted_language(self, model: Any, audio: Any) -> tuple[str | None, float | None]:
        detect = getattr(model, "detect_language", None)
        if detect is None:
            return None, None
        try:
            try:
                _, _, all_probs = detect(audio=audio, vad_filter=True)
            except Exception:
                _, _, all_probs = detect(audio=audio)
        except Exception:
            return None, None
        return pick_restricted_language(all_probs or [], self.allowed_languages)

    def _transcribe_sync(
        self,
        samples: Any,
        sample_rate: int,
        language: str | None,
        vad_filter: bool,
        allow_detection: bool,
    ) -> STTResult:
        audio = self._pcm_to_float32(samples, sample_rate)
        model = self._ensure_model()
        chosen = parse_language_list(language)[0] if language else None
        restricted_probability: float | None = None
        allowed = self.allowed_languages
        if chosen is None and len(allowed) == 1:
            chosen = allowed[0]
        elif chosen is None and len(allowed) > 1 and allow_detection:
            chosen, restricted_probability = self._detect_restricted_language(model, audio)

        kwargs: dict[str, Any] = {"vad_filter": vad_filter, "beam_size": self.beam_size}
        if chosen:
            kwargs["language"] = chosen
        segments, info = model.transcribe(audio, **kwargs)
        text = "".join(str(segment.text) for segment in segments if keep_segment(segment)).strip()

        detected = chosen or getattr(info, "language", None)
        probability = (
            restricted_probability
            if restricted_probability is not None
            else getattr(info, "language_probability", None)
        )
        speech_seconds = _number(getattr(info, "duration_after_vad", None)) if vad_filter else None
        if speech_seconds is None:
            speech_seconds = _number(getattr(info, "duration", None))
        return STTResult(
            text=text,
            language=detected,
            language_probability=probability,
            speech_duration_ms=round(speech_seconds * 1000.0, 3) if speech_seconds is not None else None,
        )

    def _partial_window(self, samples: list[int], sample_rate: int) -> list[int]:
        window_samples = int(self.partial_window_sec * sample_rate)
        if len(samples) <= window_samples:
            return samples
        return samples[-window_samples:]

    async def transcribe_partial(
        self,
        samples: list[int],
        sample_rate: int,
        language: str | None = None,
    ) -> STTResult:
        if not samples:
            return STTResult(text="")
        window = self._snapshot(self._partial_window(samples, sample_rate))
        # Partials skip the extra language-detection pass (latency); they use
        # the declared language, or the only allowed one, else auto-detect.
        return await asyncio.to_thread(
            self._transcribe_sync, window, sample_rate, language, False, False
        )
