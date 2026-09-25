"""Regression tests for the 2026-09-24 audit: session-gateway HTTP adapter
and the Ollama / OpenClaw session bridges.

Q-04/AD-1 (30 s total timeout, keep-alives, cancel on idle timeout), AD-7
(queued OpenClaw cancel, prompt Ollama cancel), B-1/AD-4 (bridge final ==
joined deltas), AD-12 (bridge health model check), AD-13 (line limit,
ensure_ascii, error lines), item 16 (one ClientSession per adapter).
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from adapters.base import AdapterConfig, UnknownSessionError, is_unknown_session_error
from adapters.session_gateway_http import BackendIdleTimeoutError, SessionGatewayHTTPAdapter
from gateway.ollama_session_backend import server as ollama_bridge
from gateway.openclaw_session_backend import server as openclaw_bridge


def _ndjson(event: dict) -> bytes:
    return (json.dumps(event) + "\n").encode()


class _ScriptedBackend:
    """Minimal session backend whose /events behaviour each test scripts."""

    def __init__(self) -> None:
        self.cancel_calls: list[tuple[str, str]] = []
        self.events_script = None
        self.peers: list[tuple] = []
        self.server: TestServer | None = None

    async def sessions(self, request: web.Request) -> web.Response:
        self.peers.append(request.transport.get_extra_info("peername"))
        return web.json_response({"session_handle": "s1"})

    async def turns(self, request: web.Request) -> web.Response:
        self.peers.append(request.transport.get_extra_info("peername"))
        if request.match_info["s"] != "s1":
            return web.json_response({"error": "unknown session handle"}, status=404)
        return web.json_response({"turn_handle": "t1"})

    async def cancel(self, request: web.Request) -> web.Response:
        self.cancel_calls.append((request.match_info["s"], request.match_info["t"]))
        return web.json_response({"status": "acknowledged"})

    async def events(self, request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
        await response.prepare(request)
        await self.events_script(response)
        await response.write_eof()
        return response

    async def start(self) -> str:
        app = web.Application()
        app.router.add_post("/sessions", self.sessions)
        app.router.add_post("/sessions/{s}/turns", self.turns)
        app.router.add_get("/sessions/{s}/turns/{t}/events", self.events)
        app.router.add_post("/sessions/{s}/turns/{t}/cancel", self.cancel)
        self.server = TestServer(app)
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")

    async def close(self) -> None:
        if self.server is not None:
            await self.server.close()


class SessionGatewayAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.backend = _ScriptedBackend()
        base_url = await self.backend.start()
        self.adapter = SessionGatewayHTTPAdapter(
            AdapterConfig(
                kind="session_gateway_http",
                name="audit",
                options={
                    "base_url": base_url,
                    "timeout_seconds": 0.3,
                    "idle_timeout_seconds": 0.6,
                },
            )
        )

    async def asyncTearDown(self) -> None:
        await self.adapter.aclose()
        await self.backend.close()

    async def _collect(self) -> list[dict]:
        return [event async for event in self.adapter.stream_assistant_output("s1", "t1")]

    async def test_long_turn_with_keepalives_outlives_request_timeout(self) -> None:
        async def script(response: web.StreamResponse) -> None:
            for _ in range(6):  # 1.2 s total, never idle for more than 0.2 s
                await asyncio.sleep(0.2)
                await response.write(_ndjson({"type": "assistant_activity", "activity_type": "thinking", "summary": "Still working"}))
            await response.write(_ndjson({"type": "assistant_text_final", "text": "Done."}))
            await response.write(_ndjson({"type": "turn_completed"}))

        self.backend.events_script = script
        events = await self._collect()
        self.assertEqual(events[-1]["type"], "turn_completed")
        self.assertEqual(self.backend.cancel_calls, [])

    async def test_idle_timeout_cancels_backend_turn_and_raises_clear_error(self) -> None:
        async def script(response: web.StreamResponse) -> None:
            await asyncio.sleep(5.0)

        self.backend.events_script = script
        with self.assertRaises(BackendIdleTimeoutError) as caught:
            await asyncio.wait_for(self._collect(), timeout=4.0)
        self.assertIn("no events", str(caught.exception))
        self.assertEqual(self.backend.cancel_calls, [("s1", "t1")])

    async def test_error_line_is_reported_as_turn_failed(self) -> None:
        async def script(response: web.StreamResponse) -> None:
            await response.write(_ndjson({"type": "assistant_text_delta", "text": "partial"}))
            await response.write(b'error: {"message": "agent crashed"}\n')

        self.backend.events_script = script
        events = await self._collect()
        self.assertEqual(events[-1]["type"], "turn_failed")
        self.assertIn("agent crashed", events[-1]["message"])

    async def test_untyped_error_object_is_reported_as_turn_failed(self) -> None:
        async def script(response: web.StreamResponse) -> None:
            await response.write(_ndjson({"error": "model not loaded"}))

        self.backend.events_script = script
        events = await self._collect()
        self.assertEqual(events, [{"type": "turn_failed", "message": "model not loaded"}])

    async def test_long_arabic_final_line_is_accepted(self) -> None:
        reply = "مرحبا بك " * 3500

        async def script(response: web.StreamResponse) -> None:
            # ensure_ascii=True inflates this to ~190 KiB on one line.
            await response.write(_ndjson({"type": "assistant_text_final", "text": reply}))

        self.backend.events_script = script
        events = await self._collect()
        self.assertEqual(events[0]["text"], reply)

    async def test_unknown_session_raises_typed_error(self) -> None:
        with self.assertRaises(UnknownSessionError) as caught:
            await self.adapter.submit_user_turn("stale", "hello")
        self.assertTrue(is_unknown_session_error(caught.exception))

    async def test_one_client_session_is_reused_and_closed(self) -> None:
        await self.adapter.start_or_resume_session()
        first = self.adapter._http
        await self.adapter.submit_user_turn("s1", "hello")
        self.assertIsNotNone(first)
        self.assertIs(self.adapter._http, first)
        # Keep-alive reuse: both requests came over the same TCP connection.
        self.assertEqual(len(set(self.backend.peers)), 1)
        await self.adapter.aclose()
        self.assertTrue(first.closed)


class _FakeProc:
    def __init__(self, stdout: bytes, delay: float = 0.0) -> None:
        self._stdout = stdout
        self._delay = delay
        self.returncode = 0
        self.pid = -1

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(self._delay)
        return self._stdout, b""


def _openclaw_payload(text: str) -> bytes:
    return json.dumps({"result": {"payloads": [{"text": text}], "meta": {}}}, ensure_ascii=False).encode()


class OpenClawBridgeAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.spawned: list[tuple] = []
        self.delay = 0.0
        self.reply = "hello from openclaw"

        async def fake_exec(*args, **kwargs):
            self.spawned.append(args)
            return _FakeProc(_openclaw_payload(self.reply), delay=self.delay)

        self.patches = [
            patch.object(openclaw_bridge.asyncio, "create_subprocess_exec", side_effect=fake_exec),
            patch.object(openclaw_bridge, "_terminate_process_group", AsyncMock()),
        ]
        for patcher in self.patches:
            patcher.start()
        self.client = TestClient(TestServer(openclaw_bridge.create_app()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        for patcher in self.patches:
            patcher.stop()

    async def _new_turn(self, session: str, text: str) -> str:
        data = await (await self.client.post(f"/sessions/{session}/turns", json={"transcript": text})).json()
        return data["turn_handle"]

    async def _events(self, session: str, turn: str) -> list[dict]:
        body = await (await self.client.get(f"/sessions/{session}/turns/{turn}/events")).text()
        return [json.loads(line) for line in body.splitlines() if line.strip()]

    async def test_turn_cancelled_while_queued_never_spawns(self) -> None:
        self.delay = 0.6
        session = (await (await self.client.post("/sessions", json={})).json())["session_handle"]
        turn_a = await self._new_turn(session, "turn A: book table")
        turn_b = await self._new_turn(session, "turn B: email boss")

        stream_a = asyncio.create_task(self._events(session, turn_a))
        await asyncio.sleep(0.1)
        stream_b = asyncio.create_task(self._events(session, turn_b))
        await asyncio.sleep(0.1)
        await self.client.post(f"/sessions/{session}/turns/{turn_b}/cancel", json={})

        # The queued turn is acknowledged without waiting for turn A.
        events_b = await asyncio.wait_for(stream_b, timeout=0.3)
        self.assertEqual([event["type"] for event in events_b], ["cancel_acknowledged"])
        events_a = await stream_a
        self.assertEqual(events_a[-1]["type"], "turn_completed")
        self.assertEqual(len(self.spawned), 1)
        self.assertIn("turn A: book table", " ".join(self.spawned[0]))

    async def test_keepalive_is_sent_while_agent_works(self) -> None:
        self.delay = 0.35
        with patch.object(openclaw_bridge, "KEEPALIVE_SECONDS", 0.1):
            session = (await (await self.client.post("/sessions", json={})).json())["session_handle"]
            turn = await self._new_turn(session, "long task")
            events = await self._events(session, turn)
        activities = [event for event in events if event["type"] == "assistant_activity"]
        self.assertGreaterEqual(len(activities), 2)
        self.assertEqual(activities[0]["activity_type"], "thinking")
        self.assertEqual(events[-1]["type"], "turn_completed")

    async def test_arabic_output_is_not_ascii_escaped(self) -> None:
        self.reply = "مرحبا بك"
        session = (await (await self.client.post("/sessions", json={})).json())["session_handle"]
        turn = await self._new_turn(session, "hello")
        raw = await (await self.client.get(f"/sessions/{session}/turns/{turn}/events")).read()
        self.assertIn("مرحبا بك".encode(), raw)
        self.assertNotIn(b"\\u0645", raw)


class _FakeOllama:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.tokens: list[str] = ["Hello", " there."]
        self.first_token_delay = 0.0
        self.hang_after_first = False
        self.models = [{"name": "qwen3.5:2b", "model": "qwen3.5:2b"}]
        self.server: TestServer | None = None
        self.disconnected = asyncio.Event()

    async def chat(self, request: web.Request) -> web.StreamResponse:
        self.payloads.append(await request.json())
        response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
        await response.prepare(request)
        try:
            if self.first_token_delay:
                await asyncio.sleep(self.first_token_delay)
            for index, token in enumerate(self.tokens):
                await response.write(_ndjson({"message": {"role": "assistant", "content": token}, "done": False}))
                if self.hang_after_first and index == 0:
                    await asyncio.sleep(30)
            await response.write(_ndjson({"message": {"role": "assistant", "content": ""}, "done": True}))
        except (asyncio.CancelledError, ConnectionResetError):
            self.disconnected.set()
            raise
        return response

    async def tags(self, _: web.Request) -> web.Response:
        return web.json_response({"models": self.models})

    async def start(self) -> str:
        app = web.Application()
        app.router.add_post("/api/chat", self.chat)
        app.router.add_get("/api/tags", self.tags)
        # Cancel the handler when the bridge drops the upstream connection.
        self.server = TestServer(app, handler_cancellation=True)
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")


class OllamaBridgeAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ollama = _FakeOllama()
        base = await self.ollama.start()
        self.base_patch = patch.object(ollama_bridge, "OLLAMA_BASE_URL", base)
        self.base_patch.start()
        self.client = TestClient(TestServer(ollama_bridge.create_app()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.ollama.server.close()
        self.base_patch.stop()

    async def _session(self) -> str:
        return (await (await self.client.post("/sessions", json={})).json())["session_handle"]

    async def _turn(self, session: str, text: str = "hi", turn_context: dict | None = None) -> str:
        body = {"transcript": text}
        if turn_context is not None:
            body["turn_context"] = turn_context
        return (await (await self.client.post(f"/sessions/{session}/turns", json=body)).json())["turn_handle"]

    async def _events(self, session: str, turn: str) -> list[dict]:
        body = await (await self.client.get(f"/sessions/{session}/turns/{turn}/events")).text()
        return [json.loads(line) for line in body.splitlines() if line.strip()]

    async def test_final_text_equals_joined_raw_deltas(self) -> None:
        self.ollama.tokens = ["**Sure!**", " Here are ideas:\n\n", "1. Visit the **Louvre**.\n\n",
                              "2. Walk along the Seine at sunset"]
        session = await self._session()
        events = await self._events(session, await self._turn(session))
        deltas = "".join(event["text"] for event in events if event["type"] == "assistant_text_delta")
        final = next(event for event in events if event["type"] == "assistant_text_final")
        self.assertEqual(final["text"], deltas)
        self.assertEqual(deltas, "".join(self.ollama.tokens))

    async def test_inline_think_block_is_filtered_and_announced_once(self) -> None:
        self.ollama.tokens = ["<think>", "planning", " more", "</thi", "nk>\n\n", "Paris."]
        session = await self._session()
        events = await self._events(session, await self._turn(session))
        deltas = "".join(event["text"] for event in events if event["type"] == "assistant_text_delta")
        self.assertEqual(deltas, "Paris.")
        activities = [event for event in events if event["type"] == "assistant_activity"]
        self.assertEqual(len(activities), 1)
        history = ollama_bridge.BACKEND.sessions[session].history
        self.assertEqual(history[-1], {"role": "assistant", "content": "Paris."})

    async def test_keepalive_sent_while_waiting_for_first_token(self) -> None:
        self.ollama.first_token_delay = 0.35
        with patch.object(ollama_bridge, "KEEPALIVE_SECONDS", 0.1):
            session = await self._session()
            events = await self._events(session, await self._turn(session))
        activities = [event for event in events if event["type"] == "assistant_activity"]
        self.assertGreaterEqual(len(activities), 2)
        self.assertEqual(events[-1]["type"], "turn_completed")

    async def test_cancel_closes_upstream_promptly(self) -> None:
        self.ollama.hang_after_first = True
        session = await self._session()
        turn = await self._turn(session)
        stream = asyncio.create_task(self._events(session, turn))
        await asyncio.sleep(0.2)
        await self.client.post(f"/sessions/{session}/turns/{turn}/cancel", json={})
        events = await asyncio.wait_for(stream, timeout=1.0)
        self.assertEqual(events[-1]["type"], "cancel_acknowledged")
        await asyncio.wait_for(self.ollama.disconnected.wait(), timeout=1.0)

    async def test_cancel_before_first_token_is_prompt(self) -> None:
        self.ollama.first_token_delay = 30
        session = await self._session()
        turn = await self._turn(session)
        stream = asyncio.create_task(self._events(session, turn))
        await asyncio.sleep(0.2)
        await self.client.post(f"/sessions/{session}/turns/{turn}/cancel", json={})
        events = await asyncio.wait_for(stream, timeout=1.0)
        self.assertEqual(events[-1]["type"], "cancel_acknowledged")

    async def test_voice_context_is_merged_into_single_system_message(self) -> None:
        session = await self._session()
        context = {"input_language": "ar", "primary_language": "en", "translation_directive": "Respond only in Arabic."}
        await self._events(session, await self._turn(session, "مرحبا", context))
        messages = self.ollama.payloads[-1]["messages"]
        roles = [message["role"] for message in messages]
        self.assertEqual(roles, ["system", "user"])
        self.assertIn("Respond only in Arabic.", messages[0]["content"])

    async def test_health_degraded_when_model_not_pulled(self) -> None:
        self.ollama.models = [{"name": "llama3.2:3b", "model": "llama3.2:3b"}]
        data = await (await self.client.get("/health")).json()
        self.assertEqual(data["status"], "degraded")
        self.assertIn("qwen3.5:2b", data["detail"])

    async def test_health_ok_when_model_pulled(self) -> None:
        data = await (await self.client.get("/health")).json()
        self.assertEqual(data["status"], "ok")


if __name__ == "__main__":
    unittest.main()
