from __future__ import annotations

import inspect
import unittest

from providers.tts.base import TTSProvider


class TTSProviderContractTests(unittest.TestCase):
    def test_synthesize_accepts_expressiveness_kw(self) -> None:
        sig = inspect.signature(TTSProvider.synthesize)
        self.assertIn("expressiveness", sig.parameters)
        param = sig.parameters["expressiveness"]
        self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(param.default, None)


if __name__ == "__main__":
    unittest.main()
