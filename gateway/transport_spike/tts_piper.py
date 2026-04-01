import asyncio
import shutil


class PiperTTS:
    def __init__(self, voice_path: str | None = None, sample_rate: int = 22050) -> None:
        self.voice_path = voice_path
        self.sample_rate = sample_rate
        self.binary = shutil.which("piper")

    @property
    def available(self) -> bool:
        return self.binary is not None and self.voice_path is not None

    async def synthesize(self, text: str) -> list[int]:
        if not self.available:
            raise RuntimeError("piper is not available")

        cmd = [
            self.binary,
            "--model",
            self.voice_path,
            "--output-raw",
        ]

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
