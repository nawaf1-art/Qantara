import asyncio
import os
import sys
import struct
import time
from collections.abc import AsyncIterator


STREAM_CHUNK_BYTES = 2560  # 1280 samples = 80ms at 16kHz, ~58ms at 22050Hz
SILENCE_TIMEOUT_S = 0.3  # how long to wait for more output before assuming synthesis is done


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
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._warm = False

    @property
    def available(self) -> bool:
        return self.voice_path is not None and os.path.exists(self.voice_path)

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

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        """Start or reuse the persistent Piper subprocess."""
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
        """Pre-load the model by running a dummy synthesis. Call once at startup."""
        if not self.available or self._warm:
            return
        async with self._lock:
            proc = await self._ensure_process()
            proc.stdin.write(b"warmup\n")
            await proc.stdin.drain()
            # drain output
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(4096), timeout=5.0)
                    if not chunk:
                        break
                except asyncio.TimeoutError:
                    break
            self._warm = True

    async def synthesize_stream(self, text: str) -> AsyncIterator[list[int]]:
        """Yield sample chunks from the persistent Piper process as they arrive."""
        if not self.available:
            raise RuntimeError("piper is not available")

        async with self._lock:
            proc = await self._ensure_process()
            clean = text.replace("\n", " ").strip()
            if not clean:
                return

            proc.stdin.write((clean + "\n").encode("utf-8"))
            await proc.stdin.drain()

            residual = b""
            timeout = 5.0 if not self._warm else SILENCE_TIMEOUT_S
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(STREAM_CHUNK_BYTES), timeout=timeout)
                    if not chunk:
                        # process died
                        self._proc = None
                        break
                    # after first bytes arrive, use shorter timeout
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
        """Terminate the persistent process."""
        if self._proc is not None and self._proc.returncode is None:
            self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._proc.kill()
            self._proc = None
