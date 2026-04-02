import asyncio
import os
import sys
import struct
from collections.abc import AsyncIterator


STREAM_CHUNK_BYTES = 2560  # 1280 samples = 80ms at 16kHz, ~58ms at 22050Hz


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

    async def synthesize_stream(self, text: str) -> AsyncIterator[list[int]]:
        """Yield sample chunks as Piper writes them to stdout, overlapping synthesis with playback."""
        if not self.available:
            raise RuntimeError("piper is not available")

        proc = await asyncio.create_subprocess_exec(
            *self._build_cmd(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()

        residual = b""
        try:
            while True:
                chunk = await proc.stdout.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                raw = residual + chunk
                # align to 2-byte sample boundary
                usable = (len(raw) // 2) * 2
                if usable > 0:
                    yield _bytes_to_samples(raw[:usable])
                residual = raw[usable:]

            if len(residual) >= 2:
                yield _bytes_to_samples(residual)
        finally:
            try:
                await proc.wait()
            except Exception:
                pass

    async def synthesize(self, text: str) -> list[int]:
        """Full-buffer synthesis (legacy path, kept for compatibility)."""
        all_samples: list[int] = []
        async for chunk in self.synthesize_stream(text):
            all_samples.extend(chunk)
        return all_samples
