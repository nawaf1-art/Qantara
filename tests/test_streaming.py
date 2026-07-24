from __future__ import annotations

import unittest

from adapters.openai_compatible import _extract_answer_delta
from qantara.streaming import iter_ndjson_objects, iter_sse_json_objects


async def _chunks(values: list[bytes]):
    for value in values:
        yield value


class StreamingParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_ndjson_preserves_split_utf8_and_multiple_lines(self) -> None:
        encoded = '{"message":{"content":"أهلاً"}}\n{"done":true}'.encode()
        split_at = encoded.index("أ".encode()) + 1
        events = [
            event
            async for event in iter_ndjson_objects(
                _chunks([encoded[:split_at], encoded[split_at:]])
            )
        ]
        self.assertEqual(events[0]["message"]["content"], "أهلاً")
        self.assertTrue(events[1]["done"])

    async def test_sse_handles_split_frames_and_done_marker(self) -> None:
        payload = (
            b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        events = [
            event
            async for event in iter_sse_json_objects(
                _chunks([payload[:17], payload[17:61], payload[61:]])
            )
        ]
        self.assertEqual(
            [event["choices"][0]["delta"]["content"] for event in events],
            ["hello", " world"],
        )

    def test_reasoning_is_not_promoted_to_spoken_content(self) -> None:
        content, has_reasoning = _extract_answer_delta(
            {"content": "", "reasoning": "internal chain", "reasoning_content": "legacy"}
        )
        self.assertEqual(content, "")
        self.assertTrue(has_reasoning)

    def test_answer_content_is_kept_when_reasoning_is_present(self) -> None:
        content, has_reasoning = _extract_answer_delta(
            {"content": "final answer", "thinking": "internal chain"}
        )
        self.assertEqual(content, "final answer")
        self.assertTrue(has_reasoning)
