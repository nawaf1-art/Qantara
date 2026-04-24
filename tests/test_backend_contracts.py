from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from adapters.base import AdapterConfig
from adapters.session_gateway_http import SessionGatewayHTTPAdapter
from gateway.fake_session_backend.server import create_app as create_fake_backend_app
from gateway.ollama_session_backend.server import create_app as create_ollama_backend_app
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
    def __init__(self, lines: list[str], status: int = 200) -> None:
        self.status = status
        self.content = self._iter_lines(lines)

    async def _iter_lines(self, lines: list[str]):
        for line in lines:
            yield line.encode("utf-8")

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
