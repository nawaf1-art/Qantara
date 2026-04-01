import asyncio
import os
import sys


def _default_model_path() -> str | None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidate = os.path.join(repo_root, "models", "piper", "en_US-lessac-medium.onnx")
    return candidate if os.path.exists(candidate) else None


def _default_config_path(model_path: str | None) -> str | None:
    if not model_path:
        return None
    candidate = f"{model_path}.json"
    return candidate if os.path.exists(candidate) else None


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

    async def synthesize(self, text: str) -> list[int]:
        if not self.available:
            raise RuntimeError("piper is not available")

        cmd = [
            *self.command,
            "--model",
            self.voice_path,
            "--output-raw",
        ]
        if self.config_path is not None:
            cmd.extend(["--config", self.config_path])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate(text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or "piper failed")

        samples = []
        for i in range(0, len(stdout) - 1, 2):
            samples.append(int.from_bytes(stdout[i:i + 2], "little", signed=True))
        return samples
