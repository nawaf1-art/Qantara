"""V-1 (sentence splitter), V-2 (TTS normalizer) and B-1 (speak the tail from
the streamed deltas). Tables derived from
docs/audits/2026-09-24-probes/lifecycle/probe_tts_chunking.py,
speech/probe_chunking2.py and speech/probe_normalize.py."""
from __future__ import annotations

import unittest

from gateway.transport_spike.runtime import Session
from gateway.transport_spike.speech import (
    find_speech_breaks,
    normalize_tts_text,
    stream_assistant_turn,
)
from tests.test_audit_lifecycle_support import ScriptAdapter, make_runtime
from tests.test_transport_spike import DummyWebSocket, FakeTTS


async def run_tokens(tokens: list[str], *, final: str | None = None, output_language: str | None = None) -> tuple[list[str], DummyWebSocket, Session]:
    events = [{"type": "assistant_text_delta", "text": t} for t in tokens]
    if final is not None:
        events.append({"type": "assistant_text_final", "text": final})
    events.append({"type": "turn_completed"})
    tts = FakeTTS()
    runtime, _events = make_runtime(ScriptAdapter(events), tts=tts)
    session = Session(DummyWebSocket(), runtime)
    runtime.register_session(session)
    if output_language:
        session.primary_language = output_language
    await stream_assistant_turn(session, "q")
    return tts.spoken, session.websocket, session


class SentenceSplitterStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_decimal_is_not_split(self) -> None:
        spoken, _, _ = await run_tokens(["The", " price", " is", " 3", ".", "5", " dollars", " today", "."])
        self.assertEqual(spoken, ["The price is 3.5 dollars today."])

    async def test_time_is_not_split(self) -> None:
        spoken, _, _ = await run_tokens(["Meet", " at", " 3", ":", "30", " pm", "."])
        self.assertEqual(spoken, ["Meet at 3:30 pm."])

    async def test_abbreviation_is_not_split(self) -> None:
        spoken, _, _ = await run_tokens(["Ask", " Dr", ".", " Smith", " about", " it", "."])
        self.assertEqual(spoken, ["Ask Dr. Smith about it."])

    async def test_long_unpunctuated_text_is_cut_at_a_space(self) -> None:
        spoken, _, _ = await run_tokens([
            "The quick brown fox jumps over the lazy dog while the sun sets slo",
            "wly behind the distant hills",
        ])
        for chunk in spoken:
            self.assertNotIn("slo", chunk.split(), f"mid-word cut in {spoken!r}")
        self.assertEqual(" ".join(spoken), "The quick brown fox jumps over the lazy dog while the sun sets slowly behind the distant hills")

    async def test_arabic_question_mark_breaks(self) -> None:
        spoken, _, _ = await run_tokens(["هل", " تريد", " المساعدة", "؟", " أنا", " هنا", "."], output_language="ar")
        self.assertEqual(spoken, ["هل تريد المساعدة؟", "أنا هنا."])

    async def test_sentences_break_at_whitespace_after_terminator(self) -> None:
        spoken, _, _ = await run_tokens(["First", " one", ".", " Second", " one", "!", " Third?"])
        self.assertEqual(spoken, ["First one.", "Second one!", "Third?"])


class SentenceSplitterUnitTests(unittest.TestCase):
    def test_terminator_at_end_waits_for_more_text_unless_final(self) -> None:
        self.assertEqual(find_speech_breaks("Hello there.", final=False), [])
        self.assertEqual(find_speech_breaks("Hello there.", final=True), [12])

    def test_colon_before_digit_does_not_break(self) -> None:
        self.assertEqual(find_speech_breaks("Price: 3 dollars. ", final=False), [17])

    def test_colon_before_words_breaks(self) -> None:
        self.assertEqual(find_speech_breaks("Note: this matters ", final=False), [5])

    def test_common_abbreviations(self) -> None:
        for text in ("Mr. Brown ", "Mrs. Brown ", "Ms. Brown ", "St. Louis ", "e.g. this ", "i.e. that ", "cats vs. dogs ", "apples etc. and "):
            self.assertEqual(find_speech_breaks(text, final=False), [], text)

    def test_newline_breaks(self) -> None:
        self.assertEqual(find_speech_breaks("Line one\nLine two", final=False), [9])

    def test_arabic_terminators(self) -> None:
        self.assertEqual(find_speech_breaks("نعم؛ لا ", final=False), [4])
        self.assertEqual(find_speech_breaks("جملة۔ أخرى", final=False), [5])


class NormalizerTests(unittest.TestCase):
    def test_slash_is_not_turned_into_or(self) -> None:
        self.assertNotIn(" or ", normalize_tts_text("The store is open 24/7", language="en"))
        self.assertNotIn(" or ", normalize_tts_text("Meeting on 24/09/2026", language="en"))

    def test_kilometers_per_hour(self) -> None:
        self.assertEqual(normalize_tts_text("Drive at 60 km/h max", language="en"), "Drive at 60 kilometers per hour max")

    def test_markdown_heading_and_link_are_stripped(self) -> None:
        out = normalize_tts_text("## Summary\nSee [the docs](https://example.com/guide) for more", language="en")
        self.assertNotIn("#", out)
        self.assertNotIn("http", out)
        self.assertIn("the docs", out)

    def test_code_fence_markers_are_stripped(self) -> None:
        out = normalize_tts_text("Run this:\n```bash\nls -la\n```\nDone", language="en")
        self.assertNotIn("```", out)
        self.assertNotIn("bash", out)
        self.assertIn("ls -la", out)

    def test_english_units_only_for_english(self) -> None:
        self.assertIn("percent", normalize_tts_text("Growth was 85% this year", language="en"))
        self.assertIn("degrees Celsius", normalize_tts_text("It is 30°C", language="en"))
        arabic = normalize_tts_text("نسبة النجاح 85% هذا العام", language="ar")
        self.assertNotIn("percent", arabic)
        self.assertIn("85%", arabic)
        self.assertNotIn("degrees", normalize_tts_text("درجة الحرارة 45°C اليوم", language="ar"))
        self.assertNotIn("percent", normalize_tts_text("La tasa es del 50%", language="es"))

    def test_unknown_language_uses_script(self) -> None:
        self.assertIn("percent", normalize_tts_text("Growth was 85%"))
        self.assertNotIn("percent", normalize_tts_text("نسبة النجاح 85%"))

    def test_millimeters_needs_a_word_boundary(self) -> None:
        self.assertNotIn("millimeters", normalize_tts_text("Blood pressure 120 mmHg", language="en"))
        self.assertIn("millimeters", normalize_tts_text("Rain 12 mm today", language="en"))


class StreamedTailTests(unittest.IsolatedAsyncioTestCase):
    async def test_tail_is_spoken_from_deltas_when_final_differs(self) -> None:
        # The Ollama bridge normalises its final text (drops '*', '#', newlines),
        # so slicing the final by the streamed length garbles the tail.
        tokens = ["**Paris** tips.", " Walk along the Seine at sunset"]
        final = "Paris tips. Walk along the Seine at sunset"
        spoken, ws, session = await run_tokens(tokens, final=final)
        self.assertEqual(spoken[-1], "Walk along the Seine at sunset")
        finals = [m for m in ws.strings if m.get("type") == "assistant_text_final"]
        self.assertEqual(finals[-1]["text"], final)
        assistant_items = [i for i in session.transcript_items if i["role"] == "assistant"]
        self.assertEqual(assistant_items[-1]["text"], final)

    async def test_final_only_reply_is_spoken(self) -> None:
        spoken, _, _ = await run_tokens([], final="Hello again, this is the whole reply.")
        self.assertEqual(" ".join(spoken), "Hello again, this is the whole reply.")

    async def test_output_language_reaches_normalizer(self) -> None:
        spoken, _, _ = await run_tokens(["نسبة النجاح 85% هذا العام."], output_language="ar")
        self.assertTrue(spoken)
        # FakeTTS records the normalised text it was asked to synthesise.
        self.assertNotIn("percent", spoken[0])
        self.assertIn("85%", spoken[0])


if __name__ == "__main__":
    unittest.main()
