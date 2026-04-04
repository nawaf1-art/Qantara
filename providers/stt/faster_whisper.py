from __future__ import annotations

import asyncio
import io
import os
import wave

from providers.stt.base import STTProvider


class FasterWhisperSTTProvider(STTProvider):
    kind = "faster_whisper"

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        self.model_name = model_name or os.environ.get("QANTARA_WHISPER_MODEL", "base.en")
        self.device = device or os.environ.get("QANTARA_WHISPER_DEVICE", "cpu")
        self.compute_type = compute_type or os.environ.get("QANTARA_WHISPER_COMPUTE", "int8")
        self._model = None
        self._import_error = None

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
            self._model = self._WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    @staticmethod
    def _pcm_to_wav_bytes(samples: list[int], sample_rate: int) -> bytes:
        with io.BytesIO() as buf:
            with wave.open(buf, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                raw = bytearray()
                for sample in samples:
                    raw.extend(int(sample).to_bytes(2, "little", signed=True))
                wav_file.writeframes(bytes(raw))
            return buf.getvalue()

    async def transcribe(self, samples: list[int], sample_rate: int) -> str:
        wav_bytes = self._pcm_to_wav_bytes(samples, sample_rate)
        return await asyncio.to_thread(self._transcribe_sync, wav_bytes)

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        model = self._ensure_model()
        segments, _ = model.transcribe(io.BytesIO(wav_bytes), vad_filter=True)
        return "".join(segment.text for segment in segments).strip()
