from __future__ import annotations

import unittest

from gateway.session_backend_prompts import (
    build_voice_turn_context_prompt,
    build_voice_turn_user_message,
)


class SessionBackendPromptTests(unittest.TestCase):
    def test_context_prompt_includes_voice_and_translation_metadata(self) -> None:
        prompt = build_voice_turn_context_prompt(
            {
                "modality": "voice",
                "input_language": "es",
                "primary_language": "en",
                "translation_mode": "directional",
                "translation_source": "es",
                "translation_target": "ar",
                "translation_directive": "Respond only in Arabic.",
                "voice_id": "ar_JO-kareem-medium",
                "speech_rate": 1.05,
            }
        )

        self.assertIn("Qantara voice turn context", prompt)
        self.assertIn("Language instruction for this reply only: Respond only in Arabic.", prompt)
        self.assertIn("Detected input language: es", prompt)
        self.assertIn("Translation target: ar", prompt)
        self.assertIn("Qantara playback voice: ar_JO-kareem-medium", prompt)

    def test_user_message_returns_transcript_without_context(self) -> None:
        self.assertEqual(build_voice_turn_user_message("hello", {}), "hello")

    def test_user_message_wraps_transcript_with_context(self) -> None:
        message = build_voice_turn_user_message(
            "hola",
            {"translation_directive": "Respond only in Arabic."},
        )

        self.assertIn("Respond only in Arabic.", message)
        self.assertTrue(message.endswith("hola"))


if __name__ == "__main__":
    unittest.main()
