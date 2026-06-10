from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from providers.stt.faster_whisper import DEFAULT_MODEL, FasterWhisperSTTProvider


class FasterWhisperMultilingualTests(unittest.TestCase):
    def test_default_model_is_small_multilingual(self) -> None:
        self.assertEqual(DEFAULT_MODEL, "small")

    def test_env_override_respected(self) -> None:
        with patch.dict(os.environ, {"QANTARA_WHISPER_MODEL": "medium"}):
            provider = FasterWhisperSTTProvider()
            self.assertEqual(provider.model_name, "medium")

    def test_default_when_env_unset(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "QANTARA_WHISPER_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            provider = FasterWhisperSTTProvider()
            self.assertEqual(provider.model_name, "small")


class FasterWhisperModelInitRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_ensure_model_constructs_model_once(self) -> None:
        """transcribe() and transcribe_partial() run _ensure_model on
        separate threads via asyncio.to_thread — lazy init must not load
        the (large) Whisper model twice under concurrency."""
        import asyncio
        import time

        constructions: list[float] = []

        class SlowFakeModel:
            def __init__(self, *args, **kwargs) -> None:
                constructions.append(time.monotonic())
                time.sleep(0.05)  # widen the race window

        provider = FasterWhisperSTTProvider()
        provider._WhisperModel = SlowFakeModel
        provider._import_error = None

        await asyncio.gather(
            asyncio.to_thread(provider._ensure_model),
            asyncio.to_thread(provider._ensure_model),
        )
        self.assertEqual(len(constructions), 1)


if __name__ == "__main__":
    unittest.main()
