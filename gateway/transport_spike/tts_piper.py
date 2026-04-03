import asyncio
import os
import struct
import sys
import time
from collections.abc import AsyncIterator


STREAM_CHUNK_BYTES = 2560  # 1280 samples = 80ms at 16kHz, ~58ms at 22050Hz
SILENCE_TIMEOUT_S = 0.3


def _default_model_path() -> str | None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidate = os.path.join(repo_root, "models", "piper", "en_US-lessac-medium.onnx")
    return candidate if os.path.exists(candidate) else None


def _default_config_path(model_path: str | None) -> str | None:
    if not model_path:
        return None
    candidate = f"{model_path}.json"
    return candidate if os.path.exists(candidate) else None


def _bytes_to_samples(raw: bytes) -> list[int]:
    count = len(raw) // 2
    return list(struct.unpack(f"<{count}h", raw[: count * 2]))


def _try_load_piper_onnx():
    """Try to import piper_onnx for in-process ONNX inference."""
    try:
        from piper_onnx import Piper
        return Piper
    except ImportError:
        return None


_PiperOnnx = _try_load_piper_onnx()


class PiperTTS:
    def __init__(
        self,
        voice_path: str | None = None,
        config_path: str | None = None,
        sample_rate: int = 22050,
    ) -> None:
        self.voice_path = voice_path or _default_model_path()
        self.config_path = config_path or _default_config_path(self.voice_path)
        self.sample_rate = sample_rate
        self.command = [sys.executable, "-m", "piper"]

        # In-process ONNX inference (preferred)
        self._onnx_model = None
        self._onnx_available = _PiperOnnx is not None

        # Subprocess fallback
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._warm = False

    @property
    def available(self) -> bool:
        return self.voice_path is not None and os.path.exists(self.voice_path)

    @property
    def engine(self) -> str:
        """Return which TTS engine is active."""
        if self._onnx_model is not None:
            return "piper_onnx"
        if self._warm:
            return "piper_subprocess"
        return "piper"

    def _build_cmd(self) -> list[str]:
        cmd = [
            *self.command,
            "--model",
            self.voice_path,
            "--output-raw",
        ]
        if self.config_path is not None:
            cmd.extend(["--config", self.config_path])
        return cmd

    def _ensure_onnx_model(self) -> bool:
        """Load the ONNX model in-process if piper-onnx is available."""
        if self._onnx_model is not None:
            return True
        if not self._onnx_available or not self.available or not self.config_path:
            return False
        try:
            self._onnx_model = _PiperOnnx(self.voice_path, self.config_path)
            self.sample_rate = self._onnx_model.sample_rate
            return True
        except Exception:
            self._onnx_available = False
            return False

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        """Start or reuse the persistent Piper subprocess (fallback path)."""
        if self._proc is not None and self._proc.returncode is None:
            return self._proc
        self._proc = await asyncio.create_subprocess_exec(
            *self._build_cmd(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._warm = False
        return self._proc

    async def warm_up(self) -> None:
        """Pre-load the model. Uses in-process ONNX if available, subprocess otherwise."""
        if not self.available:
            return

        if self._ensure_onnx_model():
            # In-process ONNX: model is already loaded, do a dummy synthesis to warm caches
            await asyncio.to_thread(self._onnx_model.create, "warmup")
            return

        # Subprocess fallback
        async with self._lock:
            proc = await self._ensure_process()
            proc.stdin.write(b"warmup\n")
            await proc.stdin.drain()
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(4096), timeout=5.0)
                    if not chunk:
                        break
                except asyncio.TimeoutError:
                    break
            self._warm = True

    async def synthesize_stream(self, text: str) -> AsyncIterator[list[int]]:
        """Yield sample chunks. Uses in-process ONNX if available, persistent subprocess otherwise."""
        if not self.available:
            raise RuntimeError("piper is not available")

        clean = text.replace("\n", " ").strip()
        if not clean:
            return

        # Preferred: in-process ONNX inference
        if self._ensure_onnx_model():
            audio, sr = await asyncio.to_thread(self._onnx_model.create, clean)
            samples = audio.flatten()
            # Convert float32 [-1,1] -> int16
            int16 = (samples * 32767).clip(-32768, 32767).astype("int16")
            sample_list = int16.tolist()
            # Yield in chunks for consistent frame sizing
            chunk_size = 1280
            for offset in range(0, len(sample_list), chunk_size):
                yield sample_list[offset:offset + chunk_size]
            return

        # Fallback: persistent subprocess
        async with self._lock:
            proc = await self._ensure_process()
            proc.stdin.write((clean + "\n").encode("utf-8"))
            await proc.stdin.drain()

            residual = b""
            timeout = 5.0 if not self._warm else SILENCE_TIMEOUT_S
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(STREAM_CHUNK_BYTES), timeout=timeout)
                    if not chunk:
                        self._proc = None
                        break
                    timeout = SILENCE_TIMEOUT_S
                    self._warm = True
                    raw = residual + chunk
                    usable = (len(raw) // 2) * 2
                    if usable > 0:
                        yield _bytes_to_samples(raw[:usable])
                    residual = raw[usable:]
                except asyncio.TimeoutError:
                    break

            if len(residual) >= 2:
                yield _bytes_to_samples(residual)

    async def synthesize(self, text: str) -> list[int]:
        """Full-buffer synthesis (legacy path)."""
        all_samples: list[int] = []
        async for chunk in self.synthesize_stream(text):
            all_samples.extend(chunk)
        return all_samples

    async def shutdown(self) -> None:
        """Terminate the persistent subprocess if running."""
        if self._proc is not None and self._proc.returncode is None:
            self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._proc.kill()
            self._proc = None
