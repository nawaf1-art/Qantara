from __future__ import annotations

import unittest

from adapters.base import AdapterConfig
from adapters.mock_adapter import MockAdapter
from adapters.openai_compatible import OpenAICompatibleAdapter


class AdapterTranslationDirectiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_adapter_preserves_directive_in_turn_context(self) -> None:
        adapter = MockAdapter()
        handle = await adapter.start_or_resume_session({"client_session_id": "c1"})
        await adapter.submit_user_turn(
            handle,
            "hola mundo",
            {
                "source": "test",
                "input_language": "es",
                "translation_directive": "Respond in the same language.",
            },
        )
        session = adapter._sessions[handle]
        self.assertEqual(len(session["turns"]), 1)
        ctx = session["turns"][0]["turn_context"]
        self.assertEqual(ctx["translation_directive"], "Respond in the same language.")
        self.assertEqual(ctx["input_language"], "es")

    async def test_openai_adapter_builds_transient_voice_context_prompt(self) -> None:
        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                kind="openai_compatible",
                name="openai",
                options={"base_url": "http://127.0.0.1:11434", "model": "fake"},
            )
        )
        handle = await adapter.start_or_resume_session({"client_session_id": "c1"})
        turn_handle = await adapter.submit_user_turn(
            handle,
            "مرحبا",
            {
                "modality": "voice",
                "input_language": "ar",
                "translation_directive": "Respond in the same language.",
                "voice_id": "lessac",
            },
        )

        prompt = adapter._turn_context_prompts[turn_handle]
        self.assertIn("Qantara voice turn context", prompt)
        self.assertIn("Detected input language: ar", prompt)
        self.assertIn("Respond in the same language.", prompt)


if __name__ == "__main__":
    unittest.main()
