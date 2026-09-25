"""Regression tests for the 2026-09-24 audit: shared streaming helpers.

Covers AD-13 (aiohttp line limit vs the documented 1 MiB bound, SSE error
lines), AD-3 (inline <think> reasoning filter) and the NDJSON keep-alive
writer used by the session bridges (AD-1).
"""

from __future__ import annotations

import asyncio
import json
import unittest

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from qantara.streaming import (
    DEFAULT_MAX_LINE_CHARS,
    NDJSONEventWriter,
    ReasoningTagFilter,
    StreamLimitError,
    iter_sse_json_objects,
    iter_text_lines,
)


async def _chunks(values: list[bytes]):
    for value in values:
        yield value


def _run_filter(pieces: list[str], *, start_inside: bool = False) -> tuple[str, ReasoningTagFilter]:
    tag_filter = ReasoningTagFilter(start_inside=start_inside)
    visible = "".join(tag_filter.feed(piece) for piece in pieces) + tag_filter.flush()
    return visible, tag_filter


class LineLimitOverRealResponseTests(unittest.IsolatedAsyncioTestCase):
    async def _serve_line(self, payload: bytes) -> list[str]:
        async def handler(request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
            await response.prepare(request)
            await response.write(payload)
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/", handler)
        server = TestServer(app)
        await server.start_server()
        try:
            async with ClientSession() as session:
                async with session.get(server.make_url("/")) as response:
                    return [line async for line in iter_text_lines(response.content)]
        finally:
            await server.close()

    async def test_line_above_aiohttp_readline_limit_is_accepted(self) -> None:
        # aiohttp's StreamReader iterator is readline()-based and gives up at
        # ~128 KiB; qantara.streaming documents and must own a 1 MiB bound.
        text = "مرحبا بك " * 30000  # ~270k chars, ~510 KiB of UTF-8
        line = json.dumps({"type": "assistant_text_final", "text": text}, ensure_ascii=False)
        lines = await self._serve_line(line.encode("utf-8") + b"\n")
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["text"], text)

    async def test_line_above_documented_limit_is_rejected(self) -> None:
        payload = b"x" * (DEFAULT_MAX_LINE_CHARS + 10) + b"\n"
        with self.assertRaises(StreamLimitError):
            await self._serve_line(payload)


class SSEErrorFrameTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_field_line_is_reported_as_error_object(self) -> None:
        payload = (
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b'error: {"code":500,"message":"slot unavailable"}\n\n'
        )
        events = [event async for event in iter_sse_json_objects(_chunks([payload]))]
        self.assertEqual(events[0]["choices"][0]["delta"]["content"], "hi")
        self.assertIn("error", events[1])
        self.assertEqual(events[1]["error"]["message"], "slot unavailable")

    async def test_plain_text_error_line_is_reported(self) -> None:
        events = [event async for event in iter_sse_json_objects(_chunks([b"error: boom\n\n"]))]
        self.assertEqual(events, [{"error": {"message": "boom"}}])

    async def test_named_error_event_is_reported_as_error_object(self) -> None:
        payload = b'event: error\ndata: {"message":"context overflow"}\n\n'
        events = [event async for event in iter_sse_json_objects(_chunks([payload]))]
        self.assertEqual(events, [{"error": {"message": "context overflow"}}])

    async def test_named_non_error_event_is_unchanged(self) -> None:
        payload = b'event: message\ndata: {"choices":[]}\n\n'
        events = [event async for event in iter_sse_json_objects(_chunks([payload]))]
        self.assertEqual(events, [{"choices": []}])


class ReasoningTagFilterTests(unittest.TestCase):
    def test_think_block_removed_at_every_split_boundary(self) -> None:
        text = "<think>\nOkay, the user asks about France.\n</think>\n\nParis is the capital."
        for split_at in range(len(text) + 1):
            with self.subTest(split_at=split_at):
                visible, tag_filter = _run_filter([text[:split_at], text[split_at:]])
                self.assertEqual(visible, "Paris is the capital.")
                self.assertTrue(tag_filter.saw_reasoning)

    def test_char_by_char_stream_with_thinking_tag(self) -> None:
        text = "Hello. <THINKING>secret plan</Thinking> Goodbye."
        visible, tag_filter = _run_filter(list(text))
        self.assertEqual(visible, "Hello. Goodbye.")
        self.assertTrue(tag_filter.saw_reasoning)

    def test_plain_text_passes_through_with_minimal_holdback(self) -> None:
        tag_filter = ReasoningTagFilter()
        self.assertEqual(tag_filter.feed("Paris is "), "Paris is ")
        self.assertEqual(tag_filter.feed("big <"), "big ")
        self.assertEqual(tag_filter.feed("3 small"), "<3 small")
        self.assertEqual(tag_filter.flush(), "")
        self.assertFalse(tag_filter.saw_reasoning)

    def test_unfinished_tag_prefix_at_end_is_literal_text(self) -> None:
        visible, _ = _run_filter(["a <thin"])
        self.assertEqual(visible, "a <thin")

    def test_unterminated_reasoning_is_dropped(self) -> None:
        visible, tag_filter = _run_filter(["Answer.", "<think>still thinking"])
        self.assertEqual(visible, "Answer.")
        self.assertTrue(tag_filter.saw_reasoning)

    def test_stray_closing_tag_drops_pending_text_and_is_flagged(self) -> None:
        tag_filter = ReasoningTagFilter()
        emitted = tag_filter.feed("Okay, reasoning")
        emitted += tag_filter.feed("</think>\n\nThe answer.")
        emitted += tag_filter.flush()
        self.assertTrue(tag_filter.saw_stray_close)
        self.assertTrue(tag_filter.saw_reasoning)
        self.assertTrue(emitted.endswith("The answer."))
        self.assertNotIn("</think>", emitted)

    def test_start_inside_reasoning_with_only_closing_tag(self) -> None:
        text = "Okay, the user wants the capital.\nI will answer briefly.</think>\n\nParis."
        for split_at in range(len(text) + 1):
            with self.subTest(split_at=split_at):
                visible, tag_filter = _run_filter(
                    [text[:split_at], text[split_at:]], start_inside=True
                )
                self.assertEqual(visible, "Paris.")
                self.assertTrue(tag_filter.saw_reasoning)

    def test_start_inside_without_any_tag_releases_text_at_end(self) -> None:
        visible, tag_filter = _run_filter(["Paris ", "is the capital."], start_inside=True)
        self.assertEqual(visible, "Paris is the capital.")
        self.assertFalse(tag_filter.saw_reasoning)

    def test_start_inside_with_explicit_open_tag(self) -> None:
        visible, _ = _run_filter(["<think>plan</think>Done."], start_inside=True)
        self.assertEqual(visible, "Done.")


class _Sink:
    def __init__(self) -> None:
        self.lines: list[dict] = []

    async def write(self, data: bytes) -> None:
        for line in data.decode("utf-8").splitlines():
            if line.strip():
                self.lines.append(json.loads(line))


class NDJSONEventWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_unescaped_utf8_json_lines(self) -> None:
        sink = _Sink()
        raw: list[bytes] = []

        async def write(data: bytes) -> None:
            raw.append(data)
            await sink.write(data)

        writer = NDJSONEventWriter(write)
        await writer.send({"type": "assistant_text_final", "text": "مرحبا"})
        self.assertIn("مرحبا".encode(), raw[0])
        self.assertTrue(raw[0].endswith(b"\n"))

    async def test_keepalive_is_sent_while_idle(self) -> None:
        sink = _Sink()
        writer = NDJSONEventWriter(
            sink.write,
            keepalive_seconds=0.05,
            keepalive_event=lambda: {"type": "assistant_activity", "activity_type": "thinking", "summary": "Still working"},
        )
        async with writer:
            await asyncio.sleep(0.3)
            await writer.send({"type": "turn_completed"})
        keepalives = [line for line in sink.lines if line["type"] == "assistant_activity"]
        self.assertGreaterEqual(len(keepalives), 2)
        self.assertEqual(sink.lines[-1]["type"], "turn_completed")

    async def test_no_keepalive_after_close(self) -> None:
        sink = _Sink()
        writer = NDJSONEventWriter(
            sink.write,
            keepalive_seconds=0.02,
            keepalive_event=lambda: {"type": "assistant_activity", "activity_type": "thinking", "summary": "x"},
        )
        async with writer:
            await writer.send({"type": "turn_completed"})
        count = len(sink.lines)
        await asyncio.sleep(0.1)
        self.assertEqual(len(sink.lines), count)

    async def test_keepalive_stops_quietly_when_peer_disconnects(self) -> None:
        async def broken_write(_data: bytes) -> None:
            raise ConnectionResetError("peer gone")

        writer = NDJSONEventWriter(
            broken_write,
            keepalive_seconds=0.01,
            keepalive_event=lambda: {"type": "assistant_activity", "activity_type": "thinking", "summary": "x"},
        )
        async with writer:
            await asyncio.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
