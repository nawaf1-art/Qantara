from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from adapters.base import AdapterConfig
from adapters.session_gateway_http import SessionGatewayHTTPAdapter
from gateway.fake_session_backend.server import create_app as create_fake_backend_app
from gateway.ollama_session_backend.server import (
    SessionState,
    _ollama_stream_messages,
)
from gateway.ollama_session_backend.server import (
    create_app as create_ollama_backend_app,
)
from gateway.openclaw_session_backend.server import create_app as create_openclaw_backend_app


class FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.pid = 9999

    async def communicate(self):
        return self._stdout, self._stderr


class FakeStreamResponse:
    def __init__(self, chunks: list[str | bytes], status: int = 200) -> None:
        self.status = status
        self.content = self._iter_chunks(chunks)

    async def _iter_chunks(self, chunks: list[str | bytes]):
        for chunk in chunks:
            yield chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")

    async def text(self) -> str:
        return ""

    def close(self) -> None:
        return None


class FakeClientSession:
    async def close(self) -> None:
        return None


class BackendContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_gateway_adapter_against_fake_backend(self) -> None:
        server = TestServer(create_fake_backend_app())
        client = TestClient(server)
        await client.start_server()
        try:
            adapter = SessionGatewayHTTPAdapter(
                AdapterConfig(
                    kind="session_gateway_http",
                    name="fake",
                    options={"base_url": str(client.make_url("")).rstrip("/")},
                )
            )
            session_handle = await adapter.start_or_resume_session({"client_name": "test"})
            self.assertTrue(session_handle)
            turn_handle = await adapter.submit_user_turn(session_handle, "hello")
            events = [event async for event in adapter.stream_assistant_output(session_handle, turn_handle)]
            self.assertTrue(any(event["type"] == "assistant_text_delta" for event in events))
            self.assertTrue(any(event["type"] == "assistant_text_final" for event in events))
            cancel = await adapter.cancel_turn(session_handle, turn_handle)
            self.assertEqual(cancel["status"], "acknowledged")
        finally:
            await client.close()

    async def test_fake_backend_rejects_invalid_request_shapes(self) -> None:
        server = TestServer(create_fake_backend_app())
        client = TestClient(server)
        await client.start_server()
        try:
            response = await client.post("/sessions", json=[])
            self.assertEqual(response.status, 400)
            session_data = await (await client.post("/sessions", json={})).json()
            response = await client.post(
                f"/sessions/{session_data['session_handle']}/turns",
                json={"transcript": {"not": "text"}},
            )
            self.assertEqual(response.status, 400)
        finally:
            await client.close()

    async def test_ollama_backend_contract_streams_upstream_response(self) -> None:
        async def fake_ollama_stream_messages(session_state, transcript, turn_context=None):
            self.assertEqual(transcript, "hello")
            self.assertEqual(turn_context["translation_directive"], "Respond only in Arabic.")
            self.assertTrue(session_state.history)
            return FakeClientSession(), FakeStreamResponse(
                [
                    json.dumps({"message": {"content": "hello from "}, "done": False}) + "\n",
                    json.dumps({"message": {"content": "ollama"}, "done": False}) + "\n",
                    json.dumps({"done": True}) + "\n",
                ]
            )

        with patch(
            "gateway.ollama_session_backend.server._ollama_stream_messages",
            side_effect=fake_ollama_stream_messages,
        ):
            server = TestServer(create_ollama_backend_app())
            client = TestClient(server)
            await client.start_server()
            try:
                session_resp = await client.post(
                    "/sessions",
                    json={"client_context": {"client_name": "test"}},
                )
                session_data = await session_resp.json()
                turn_resp = await client.post(
                    f"/sessions/{session_data['session_handle']}/turns",
                    json={
                        "transcript": "hello",
                        "turn_context": {"translation_directive": "Respond only in Arabic."},
                    },
                )
                turn_data = await turn_resp.json()
                events_resp = await client.get(
                    f"/sessions/{session_data['session_handle']}/turns/{turn_data['turn_handle']}/events"
                )
                body = await events_resp.text()
                self.assertIn("hello from ollama", body)
                self.assertIn('"type": "assistant_text_final"', body)
                self.assertIn('"type": "turn_completed"', body)
            finally:
                await client.close()

    async def test_ollama_native_request_disables_thinking_by_default(self) -> None:
        captured: dict = {}

        async def chat_handler(request):
            captured.update(await request.json())
            return web.json_response({"done": True})

        app = web.Application()
        app.router.add_post("/api/chat", chat_handler)
        server = TestServer(app)
        await server.start_server()
        client_session = None
        upstream = None
        try:
            with patch(
                "gateway.ollama_session_backend.server.OLLAMA_BASE_URL",
                str(server.make_url("")).rstrip("/"),
            ):
                client_session, upstream = await _ollama_stream_messages(
                    SessionState(client_context={}, history=[]),
                    "hello",
                )
                await upstream.read()
            self.assertIs(captured["think"], False)
            self.assertEqual(captured["model"], "qwen3.5:2b")
        finally:
            if upstream is not None:
                upstream.close()
            if client_session is not None:
                await client_session.close()
            await server.close()

    async def test_ollama_backend_handles_split_utf8_and_coalesced_ndjson(self) -> None:
        first = json.dumps(
            {"message": {"content": "أهلاً "}, "done": False},
            ensure_ascii=False,
        ).encode("utf-8")
        second = json.dumps(
            {"message": {"content": "بك"}, "done": False},
            ensure_ascii=False,
        ).encode("utf-8")
        done = json.dumps({"done": True}).encode("utf-8")
        split_at = first.index("أ".encode()) + 1

        async def fake_ollama_stream_messages(session_state, transcript, turn_context=None):
            return FakeClientSession(), FakeStreamResponse(
                [
                    first[:split_at],
                    first[split_at:] + b"\n" + second + b"\n" + done,
                ]
            )

        with patch(
            "gateway.ollama_session_backend.server._ollama_stream_messages",
            side_effect=fake_ollama_stream_messages,
        ):
            server = TestServer(create_ollama_backend_app())
            client = TestClient(server)
            await client.start_server()
            try:
                session_data = await (await client.post("/sessions", json={})).json()
                turn_data = await (
                    await client.post(
                        f"/sessions/{session_data['session_handle']}/turns",
                        json={"transcript": "hello"},
                    )
                ).json()
                events_resp = await client.get(
                    f"/sessions/{session_data['session_handle']}/turns/{turn_data['turn_handle']}/events"
                )
                body = await events_resp.text()
                events = [json.loads(line) for line in body.splitlines()]
                final = next(event for event in events if event["type"] == "assistant_text_final")
                self.assertEqual(final["text"], "أهلاً بك")
                self.assertNotIn("\ufffd", body)
                self.assertIn('"type": "turn_completed"', body)
            finally:
                await client.close()

    async def test_ollama_backend_does_not_speak_reasoning_only_output(self) -> None:
        async def fake_ollama_stream_messages(session_state, transcript, turn_context=None):
            return FakeClientSession(), FakeStreamResponse(
                [
                    json.dumps(
                        {
                            "message": {
                                "thinking": "private chain of thought",
                                "content": "",
                            },
                            "done": False,
                        }
                    )
                    + "\n",
                    json.dumps({"done": True}) + "\n",
                ]
            )

        with patch(
            "gateway.ollama_session_backend.server._ollama_stream_messages",
            side_effect=fake_ollama_stream_messages,
        ):
            server = TestServer(create_ollama_backend_app())
            client = TestClient(server)
            await client.start_server()
            try:
                session_data = await (await client.post("/sessions", json={})).json()
                turn_data = await (
                    await client.post(
                        f"/sessions/{session_data['session_handle']}/turns",
                        json={"transcript": "hello"},
                    )
                ).json()
                events_resp = await client.get(
                    f"/sessions/{session_data['session_handle']}/turns/{turn_data['turn_handle']}/events"
                )
                body = await events_resp.text()
                self.assertIn('"type": "turn_failed"', body)
                self.assertIn("reasoning was withheld", body)
                self.assertNotIn("private chain of thought", body)
                self.assertNotIn('"type": "turn_completed"', body)
            finally:
                await client.close()

    async def test_ollama_backend_rejects_invalid_request_shapes(self) -> None:
        server = TestServer(create_ollama_backend_app())
        client = TestClient(server)
        await client.start_server()
        try:
            response = await client.post("/sessions", json=[])
            self.assertEqual(response.status, 400)

            session_data = await (await client.post("/sessions", json={})).json()
            response = await client.post(
                f"/sessions/{session_data['session_handle']}/turns",
                json={"transcript": 42},
            )
            self.assertEqual(response.status, 400)
            response = await client.post(
                f"/sessions/{session_data['session_handle']}/turns",
                json={"transcript": "hello", "turn_context": []},
            )
            self.assertEqual(response.status, 400)
        finally:
            await client.close()

    async def test_openclaw_backend_contract_with_mocked_cli(self) -> None:
        payload = {
            "result": {
                "payloads": [{"text": "hello from openclaw"}],
                "meta": {"agentMeta": {"name": "Spectra"}},
            }
        }

        async def fake_create_subprocess_exec(*args, **kwargs):
            return FakeProc(json.dumps(payload).encode("utf-8"))

        with patch("gateway.openclaw_session_backend.server.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            server = TestServer(create_openclaw_backend_app())
            client = TestClient(server)
            await client.start_server()
            try:
                session_resp = await client.post("/sessions", json={"client_context": {"client_session_id": "sticky-client"}})
                session_data = await session_resp.json()
                turn_resp = await client.post(f"/sessions/{session_data['session_handle']}/turns", json={"transcript": "hello", "turn_context": {}})
                turn_data = await turn_resp.json()
                events_resp = await client.get(f"/sessions/{session_data['session_handle']}/turns/{turn_data['turn_handle']}/events")
                body = await events_resp.text()
                self.assertIn("hello from openclaw", body)
                cancel_resp = await client.post(f"/sessions/{session_data['session_handle']}/turns/{turn_data['turn_handle']}/cancel", json={"cancel_context": {}})
                cancel_data = await cancel_resp.json()
                self.assertEqual(cancel_data["status"], "acknowledged")
            finally:
                await client.close()

    async def test_openclaw_health_is_shallow_by_default(self) -> None:
        with patch("gateway.openclaw_session_backend.server.asyncio.create_subprocess_exec") as create_proc:
            server = TestServer(create_openclaw_backend_app())
            client = TestClient(server)
            await client.start_server()
            try:
                health_resp = await client.get("/health")
                health_data = await health_resp.json()
                self.assertEqual(health_data["status"], "ok")
                self.assertEqual(health_data["mode"], "shallow")
                create_proc.assert_not_called()
            finally:
                await client.close()

    async def test_openclaw_backend_rejects_non_string_client_session_id(self) -> None:
        server = TestServer(create_openclaw_backend_app())
        client = TestClient(server)
        await client.start_server()
        try:
            response = await client.post(
                "/sessions",
                json={"client_context": {"client_session_id": ["not", "text"]}},
            )
            self.assertEqual(response.status, 400)
            self.assertEqual(
                (await response.json())["error"],
                "client_session_id must be a string",
            )
        finally:
            await client.close()

    async def test_openclaw_deep_health_is_explicit(self) -> None:
        payload = {
            "result": {
                "payloads": [{"text": "hello from openclaw"}],
                "meta": {"agentMeta": {"name": "Spectra"}},
            }
        }

        async def fake_create_subprocess_exec(*args, **kwargs):
            return FakeProc(json.dumps(payload).encode("utf-8"))

        with (
            patch("gateway.openclaw_session_backend.server.OPENCLAW_HEALTH_MODE", "deep"),
            patch("gateway.openclaw_session_backend.server.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec) as create_proc,
        ):
            server = TestServer(create_openclaw_backend_app())
            client = TestClient(server)
            await client.start_server()
            try:
                health_resp = await client.get("/health")
                health_data = await health_resp.json()
                self.assertEqual(health_data["status"], "ok")
                self.assertEqual(health_data["mode"], "deep")
                self.assertIn("agent=Spectra", health_data["detail"])
                create_proc.assert_called_once()
            finally:
                await client.close()

    async def test_openclaw_deep_health_timeout_kills_subprocess(self) -> None:
        """A deep health check whose CLI call times out must terminate the
        spawned subprocess instead of leaking it in the background."""
        import asyncio as _asyncio

        class HangingProc:
            pid = 99999

            def __init__(self) -> None:
                self.returncode: int | None = None

            async def communicate(self):
                # Hangs until killed, like a wedged CLI process.
                while self.returncode is None:
                    await _asyncio.sleep(0.01)
                return b"", b""

        proc = HangingProc()
        kills: list[tuple[object, bool]] = []

        async def fake_create_subprocess_exec(*args, **kwargs):
            return proc

        async def fake_terminate(process, hard=False):
            kills.append((process, hard))
            process.returncode = -9

        with (
            patch("gateway.openclaw_session_backend.server.OPENCLAW_HEALTH_MODE", "deep"),
            patch("gateway.openclaw_session_backend.server.OPENCLAW_HEALTH_TIMEOUT_SECONDS", 0.05),
            patch("gateway.openclaw_session_backend.server.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec),
            patch("gateway.openclaw_session_backend.server._terminate_process_group", side_effect=fake_terminate),
        ):
            server = TestServer(create_openclaw_backend_app())
            client = TestClient(server)
            await client.start_server()
            try:
                health_resp = await client.get("/health")
                health_data = await health_resp.json()
                self.assertEqual(health_data["status"], "degraded")
                self.assertEqual(kills, [(proc, True)])
            finally:
                await client.close()

    async def test_openclaw_backend_injects_qantara_turn_context(self) -> None:
        payload = {
            "result": {
                "payloads": [{"text": "hello from openclaw"}],
                "meta": {"agentMeta": {"name": "Spectra"}},
            }
        }
        captured_args: list[tuple] = []

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured_args.append(args)
            return FakeProc(json.dumps(payload).encode("utf-8"))

        with patch("gateway.openclaw_session_backend.server.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            server = TestServer(create_openclaw_backend_app())
            client = TestClient(server)
            await client.start_server()
            try:
                session_resp = await client.post("/sessions", json={"client_context": {"client_session_id": "context-client"}})
                session_data = await session_resp.json()
                turn_resp = await client.post(
                    f"/sessions/{session_data['session_handle']}/turns",
                    json={
                        "transcript": "hola",
                        "turn_context": {
                            "modality": "voice",
                            "input_language": "es",
                            "translation_directive": "Respond only in Arabic.",
                            "voice_id": "ar_JO-kareem-medium",
                        },
                    },
                )
                turn_data = await turn_resp.json()
                events_resp = await client.get(f"/sessions/{session_data['session_handle']}/turns/{turn_data['turn_handle']}/events")
                body = await events_resp.text()
                self.assertIn("openclaw", body)

                command = captured_args[0]
                message = command[command.index("--message") + 1]
                self.assertIn("Qantara voice turn context", message)
                self.assertIn("Respond only in Arabic.", message)
                self.assertIn("Detected input language: es", message)
                self.assertIn("Qantara playback voice: ar_JO-kareem-medium", message)
                self.assertIn("User transcript:", message)
                self.assertIn("hola", message)
            finally:
                await client.close()
