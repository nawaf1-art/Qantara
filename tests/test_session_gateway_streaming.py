from __future__ import annotations

import json
import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from adapters.base import AdapterConfig
from adapters.session_gateway_http import SessionGatewayHTTPAdapter


class SessionGatewayStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_split_utf8_and_coalesced_records_are_preserved(self) -> None:
        first = json.dumps(
            {"type": "assistant_text_delta", "text": "أهلاً "},
            ensure_ascii=False,
        ).encode()
        second = json.dumps(
            {"type": "assistant_text_final", "text": "أهلاً بك"},
            ensure_ascii=False,
        ).encode()
        split_at = first.index("أ".encode()) + 1

        async def stream_handler(request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse(
                headers={"Content-Type": "application/x-ndjson"}
            )
            await response.prepare(request)
            await response.write(first[:split_at])
            await response.write(first[split_at:] + b"\n" + second)
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get(
            "/sessions/{session_handle}/turns/{turn_handle}/events",
            stream_handler,
        )
        server = TestServer(app)
        await server.start_server()
        try:
            adapter = SessionGatewayHTTPAdapter(
                AdapterConfig(
                    kind="session_gateway_http",
                    name="test",
                    options={"base_url": str(server.make_url("")).rstrip("/")},
                )
            )
            events = [
                event
                async for event in adapter.stream_assistant_output("session", "turn")
            ]
        finally:
            await server.close()

        self.assertEqual(events[0]["text"], "أهلاً ")
        self.assertEqual(events[1]["text"], "أهلاً بك")
