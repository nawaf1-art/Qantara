from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import AnyUrl

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime
from gateway.transport_spike.server import create_app

try:
    from test_gateway_http import DeltaOnlyAdapter, FakeSTT, FakeTTS
except ModuleNotFoundError:
    from tests.test_gateway_http import DeltaOnlyAdapter, FakeSTT, FakeTTS

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = REPO_ROOT / "mcp_server.py"


def _tool_payload(result) -> dict:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool returned no JSON payload")


def _resource_payload(result) -> dict:
    for item in getattr(result, "contents", []) or []:
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("resource returned no JSON payload")


class MCPServerControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {"QANTARA_AUTH_TOKEN": "", "QANTARA_ADMIN_TOKEN": ""},
        )
        self.env_patch.start()
        self.runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda record: None,
        )
        self.runtime.default_binding().adapter = DeltaOnlyAdapter(
            AdapterConfig(kind="mock", name="mock")
        )
        self.server = TestServer(create_app(self.runtime))
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.env_patch.stop()

    async def _connect_voice_session(self, client_session_id: str = "mcp-control-client"):
        ws = await self.client.ws_connect("/ws")
        await ws.send_json(
            {
                "type": "session_init",
                "client_name": "mcp-control-test",
                "client_session_id": client_session_id,
                "voice_id": "fake_voice",
            }
        )
        await ws.receive_json()
        await ws.receive_json()
        return ws

    async def test_control_status_reports_active_browser_session(self) -> None:
        ws = await self._connect_voice_session("status-client")

        resp = await self.client.get("/api/control/voice/status")
        body = await resp.json()

        self.assertEqual(resp.status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["active_session_count"], 1)
        self.assertEqual(body["sessions"][0]["client_session_id"], "status-client")
        await ws.close()

    async def test_control_speak_requires_active_browser_session(self) -> None:
        resp = await self.client.post("/api/control/voice/speak", json={"text": "hello"})
        body = await resp.json()

        self.assertEqual(resp.status, 404)
        self.assertEqual(body["error"], "no active browser voice session")

    async def test_control_speak_queues_text_to_browser_session(self) -> None:
        ws = await self._connect_voice_session("speak-client")

        resp = await self.client.post(
            "/api/control/voice/speak",
            json={"client_session_id": "speak-client", "text": "hello from mcp"},
        )
        body = await resp.json()

        self.assertEqual(resp.status, 200)
        self.assertEqual(body["status"], "queued")
        seen_final = False
        seen_tts = False
        for _ in range(10):
            msg = await ws.receive_json()
            if msg.get("type") == "assistant_text_final":
                self.assertEqual(msg["text"], "hello from mcp")
                self.assertEqual(msg["source"], "control")
                seen_final = True
            if msg.get("type") == "tts_status":
                seen_tts = True
            if seen_final and seen_tts:
                break
        self.assertTrue(seen_final)
        self.assertTrue(seen_tts)
        await ws.close()

    async def test_control_transcript_records_control_speech(self) -> None:
        ws = await self._connect_voice_session("transcript-client")

        resp = await self.client.post(
            "/api/control/voice/speak",
            json={"client_session_id": "transcript-client", "text": "remember this"},
        )
        self.assertEqual(resp.status, 200)
        for _ in range(10):
            msg = await ws.receive_json()
            if msg.get("type") == "assistant_text_final":
                break

        transcript = await self.client.post(
            "/api/control/voice/transcript",
            json={"client_session_id": "transcript-client"},
        )
        body = await transcript.json()

        self.assertEqual(transcript.status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(any(item["text"] == "remember this" for item in body["transcript"]))
        self.assertTrue(any(event["event_name"] == "assistant_output_started" for event in body["timeline"]))
        await ws.close()

    async def test_control_translation_mode_updates_active_session(self) -> None:
        ws = await self._connect_voice_session("translation-client")

        resp = await self.client.post(
            "/api/control/voice/set_translation_mode",
            json={
                "client_session_id": "translation-client",
                "mode": "directional",
                "source": "en",
                "target": "ar",
            },
        )
        body = await resp.json()

        self.assertEqual(resp.status, 200)
        self.assertEqual(body["translation_mode"], "directional")
        self.assertEqual(body["session"]["translation_target"], "ar")
        update = await ws.receive_json()
        self.assertEqual(update["type"], "session_updated")
        self.assertEqual(update["translation_target"], "ar")
        await ws.close()

    async def test_control_requires_auth_when_gateway_auth_is_configured(self) -> None:
        await self.client.close()
        self.env_patch.stop()
        self.env_patch = patch.dict(
            os.environ,
            {"QANTARA_AUTH_TOKEN": "voice-secret-token-123456", "QANTARA_ADMIN_TOKEN": ""},
        )
        self.env_patch.start()
        self.runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda record: None,
        )
        self.server = TestServer(create_app(self.runtime))
        self.client = TestClient(self.server)
        await self.client.start_server()

        missing = await self.client.get("/api/control/voice/status")
        self.assertEqual(missing.status, 401)
        allowed = await self.client.get(
            "/api/control/voice/status",
            headers={"Authorization": "Bearer voice-secret-token-123456"},
        )
        self.assertEqual(allowed.status, 200)

    async def test_qantara_mcp_server_exposes_tools_and_speaks_via_gateway(self) -> None:
        ws = await self._connect_voice_session("mcp-stdio-client")
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(MCP_SERVER)],
            cwd=str(REPO_ROOT),
            env={
                **os.environ,
                "QANTARA_GATEWAY_URL": str(self.server.make_url("")).rstrip("/"),
                "QANTARA_MCP_SERVER_TRANSPORT": "stdio",
                "QANTARA_MCP_SERVER_LOG_LEVEL": "ERROR",
            },
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                self.assertIn("voice_get_status", tool_names)
                self.assertIn("voice_session_start", tool_names)
                self.assertIn("voice_speak", tool_names)
                self.assertIn("voice_get_transcript", tool_names)
                self.assertIn("voice_set_translation_mode", tool_names)

                status = _tool_payload(await session.call_tool("voice_get_status", arguments={}))
                self.assertEqual(status["active_session_count"], 1)
                active = _tool_payload(
                    await session.call_tool(
                        "voice_session_start",
                        arguments={"client_session_id": "mcp-stdio-client"},
                    )
                )
                self.assertEqual(active["status"], "active")
                translation = _tool_payload(
                    await session.call_tool(
                        "voice_set_translation_mode",
                        arguments={
                            "client_session_id": "mcp-stdio-client",
                            "mode": "assistant",
                        },
                    )
                )
                self.assertEqual(translation["translation_mode"], "assistant")
                spoken = _tool_payload(
                    await session.call_tool(
                        "voice_speak",
                        arguments={
                            "client_session_id": "mcp-stdio-client",
                            "text": "spoken through MCP server",
                        },
                    )
                )
                self.assertEqual(spoken["status"], "queued")

        seen_final = False
        for _ in range(10):
            msg = await ws.receive_json()
            if msg.get("type") == "assistant_text_final":
                self.assertEqual(msg["text"], "spoken through MCP server")
                seen_final = True
                break
        self.assertTrue(seen_final)

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(MCP_SERVER)],
            cwd=str(REPO_ROOT),
            env={
                **os.environ,
                "QANTARA_GATEWAY_URL": str(self.server.make_url("")).rstrip("/"),
                "QANTARA_MCP_SERVER_TRANSPORT": "stdio",
                "QANTARA_MCP_SERVER_LOG_LEVEL": "ERROR",
            },
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                transcript = _tool_payload(
                    await session.call_tool(
                        "voice_get_transcript",
                        arguments={"client_session_id": "mcp-stdio-client"},
                    )
                )
                self.assertTrue(any(item["text"] == "spoken through MCP server" for item in transcript["transcript"]))
        await ws.close()

    async def test_qantara_mcp_server_exposes_resources(self) -> None:
        ws = await self._connect_voice_session("mcp-resource-client")
        session_id = None
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(MCP_SERVER)],
            cwd=str(REPO_ROOT),
            env={
                **os.environ,
                "QANTARA_GATEWAY_URL": str(self.server.make_url("")).rstrip("/"),
                "QANTARA_MCP_SERVER_TRANSPORT": "stdio",
                "QANTARA_MCP_SERVER_LOG_LEVEL": "ERROR",
            },
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                resources = await session.list_resources()
                resource_uris = {str(resource.uri) for resource in resources.resources}
                self.assertIn("qantara://voices", resource_uris)
                self.assertIn("qantara://sessions", resource_uris)
                templates = await session.list_resource_templates()
                template_uris = {str(template.uriTemplate) for template in templates.resourceTemplates}
                self.assertIn("qantara://sessions/{session_id}/status", template_uris)
                sessions = _resource_payload(await session.read_resource(AnyUrl("qantara://sessions")))
                self.assertEqual(sessions["active_session_count"], 1)
                session_id = sessions["sessions"][0]["session_id"]
                status = _resource_payload(
                    await session.read_resource(AnyUrl(f"qantara://sessions/{session_id}/status"))
                )
                self.assertTrue(status["ok"])
                self.assertEqual(status["session"]["client_session_id"], "mcp-resource-client")
                voices = _resource_payload(await session.read_resource(AnyUrl("qantara://voices")))
                self.assertIn("voices", voices)
                avatars = _resource_payload(await session.read_resource(AnyUrl("qantara://avatars")))
                self.assertIn("presets", avatars)

        await ws.close()


if __name__ == "__main__":
    unittest.main()
