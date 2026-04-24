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


if __name__ == "__main__":
    unittest.main()
