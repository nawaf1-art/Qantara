from __future__ import annotations

import unittest

from providers.voice_registry import filter_registry_voices


class VoiceRegistryChatterboxTests(unittest.TestCase):
    def test_chatterbox_voices_include_warm(self) -> None:
        voices = list(filter_registry_voices("chatterbox"))
        ids = [v.voice_id for v in voices]
        self.assertIn("chatterbox_warm", ids)

    def test_chatterbox_warm_allows_expressiveness(self) -> None:
        voices = {v.voice_id: v for v in filter_registry_voices("chatterbox")}
        warm = voices["chatterbox_warm"]
        self.assertIn("expressiveness", warm.allowed_transforms or [])


if __name__ == "__main__":
    unittest.main()
