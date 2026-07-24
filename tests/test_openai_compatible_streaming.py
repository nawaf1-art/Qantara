from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from adapters.base import AdapterConfig
from adapters.openai_compatible import OpenAICompatibleAdapter


class OpenAICompatibleStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.stream_chunks: list[bytes] = []
        self.last_request_payload: dict = {}

        async def models_handler(_: web.Request) -> web.Response:
            return web.json_response({"data": [{"id": "test-model"}]})

        async def chat_handler(request: web.Request) -> web.StreamResponse:
            self.last_request_payload = await request.json()
            response = web.StreamResponse(
                headers={"Content-Type": "text/event-stream"}
            )
            await response.prepare(request)
            for chunk in self.stream_chunks:
                await response.write(chunk)
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/v1/models", models_handler)
        app.router.add_post("/v1/chat/completions", chat_handler)
        self.server = TestServer(app)
        await self.server.start_server()
        self.adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                kind="openai_compatible",
                name="test",
                options={
                    "base_url": str(self.server.make_url("")).rstrip("/"),
                    "model": "test-model",
                },
            )
        )

    async def asyncTearDown(self) -> None:
        await self.server.close()

    async def _run_turn(self) -> tuple[str, str, list[dict]]:
        session = await self.adapter.start_or_resume_session()
        turn = await self.adapter.submit_user_turn(session, "hello")
        events = [
            event
            async for event in self.adapter.stream_assistant_output(session, turn)
        ]
        return session, turn, events

    async def test_split_utf8_answer_is_preserved(self) -> None:
        first = (
            'data: {"choices":[{"delta":{"reasoning":"hidden","content":"أهلاً "}}]}\n\n'
        ).encode()
        second = (
            'data: {"choices":[{"delta":{"content":"بك"}}]}\n\ndata: [DONE]\n\n'
        ).encode()
        split_at = first.index("أ".encode()) + 1
        self.stream_chunks = [first[:split_at], first[split_at:] + second]

        _, _, events = await self._run_turn()

        deltas = [event["text"] for event in events if event["type"] == "assistant_text_delta"]
        self.assertEqual("".join(deltas), "أهلاً بك")
        self.assertEqual(events[-2], {"type": "assistant_text_final", "text": "أهلاً بك"})
        self.assertEqual(events[-1], {"type": "turn_completed"})

    async def test_reasoning_only_response_fails_without_speaking_it(self) -> None:
        event = {
            "choices": [{"delta": {"reasoning_content": "private reasoning"}}]
        }
        self.stream_chunks = [
            f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n".encode()
        ]

        session, _, events = await self._run_turn()

        self.assertFalse(any(event["type"] == "assistant_text_delta" for event in events))
        self.assertEqual(events[-1]["type"], "turn_failed")
        self.assertIn("reasoning was withheld", events[-1]["message"])
        self.assertEqual(
            [message["role"] for message in self.adapter._sessions[session]],
            ["system"],
        )

    async def test_reasoning_effort_is_opt_in(self) -> None:
        self.adapter.reasoning_effort = "none"
        self.stream_chunks = [
            b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
            b"data: [DONE]\n\n"
        ]

        await self._run_turn()

        self.assertEqual(self.last_request_payload["reasoning_effort"], "none")

    async def test_cancelled_connection_error_is_acknowledged_and_rolled_back(self) -> None:
        async def interrupted_stream(_):
            yield {"choices": [{"delta": {"content": "partial"}}]}
            raise aiohttp.ClientConnectionError("response closed by cancellation")

        session = await self.adapter.start_or_resume_session()
        turn = await self.adapter.submit_user_turn(session, "hello")
        with patch(
            "adapters.openai_compatible.iter_sse_json_objects",
            side_effect=interrupted_stream,
        ):
            events = self.adapter.stream_assistant_output(session, turn)
            first = await anext(events)
            self.assertEqual(first, {"type": "assistant_text_delta", "text": "partial"})

            await self.adapter.cancel_turn(session, turn)
            remaining = [event async for event in events]

        self.assertEqual(remaining, [{"type": "cancel_acknowledged"}])
        self.assertEqual(
            [message["role"] for message in self.adapter._sessions[session]],
            ["system"],
        )
