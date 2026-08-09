from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from adapters.base import AdapterConfig
from adapters.factory import create_adapter
from adapters.mcp_client import MCPClientAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_chat_server.py"


class MCPClientAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _adapter(self) -> MCPClientAdapter:
        return MCPClientAdapter(
            AdapterConfig(
                kind="mcp_client",
                name="fixture",
                options={
                    "transport": "stdio",
                    "command": f"{sys.executable} {FIXTURE}",
                    "chat_tool": "voice_chat",
                    "timeout_seconds": 10,
                },
            )
        )

    def test_stdio_command_split_preserves_windows_paths(self) -> None:
        command = r"C:\hostedtoolcache\windows\Python\3.11.9\x64\python.exe D:\a\Qantara\tests\fixtures\mcp_chat_server.py"

        parts = MCPClientAdapter._split_command(command, windows=True)

        self.assertEqual(parts[0], r"C:\hostedtoolcache\windows\Python\3.11.9\x64\python.exe")
        self.assertEqual(parts[1], r"D:\a\Qantara\tests\fixtures\mcp_chat_server.py")

    def test_stdio_command_split_unquotes_windows_executable_with_spaces(self) -> None:
        command = r'"C:\Program Files\Python\python.exe" D:\agent\server.py'

        parts = MCPClientAdapter._split_command(command, windows=True)

        self.assertEqual(parts, [r"C:\Program Files\Python\python.exe", r"D:\agent\server.py"])

    def test_text_extraction_stops_at_configured_limit(self) -> None:
        result = SimpleNamespace(
            content=[SimpleNamespace(text="123"), SimpleNamespace(text="45")],
            structuredContent=None,
        )
        with patch("adapters.mcp_client.MAX_MCP_TOOL_OUTPUT_CHARS", 4):
            with self.assertRaisesRegex(RuntimeError, "output exceeded"):
                MCPClientAdapter._extract_text(result)

    async def test_stdio_adapter_lists_tools_and_reports_health(self) -> None:
        adapter = self._adapter()

        tools = await adapter.list_tools()
        health = await adapter.check_health()

        self.assertTrue(any(tool["name"] == "voice_chat" for tool in tools))
        self.assertEqual(health.status, "ok")

    async def test_stdio_adapter_streams_progress_and_final_text(self) -> None:
        adapter = self._adapter()

        session_handle = await adapter.start_or_resume_session({"client_name": "test"})
        turn_handle = await adapter.submit_user_turn(
            session_handle,
            "hello from voice",
            {"output_language": "ar"},
        )
        events = [event async for event in adapter.stream_assistant_output(session_handle, turn_handle)]

        activity_events = [event for event in events if event["type"] == "assistant_activity"]
        final_events = [event for event in events if event["type"] == "assistant_text_final"]
        self.assertTrue(any("reading voice transcript" in event["summary"] for event in activity_events))
        self.assertTrue(any(event.get("progress") == 1.0 for event in activity_events))
        self.assertEqual(final_events[-1]["text"], "MCP reply (ar): hello from voice")

    async def test_factory_creates_mcp_client_adapter(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QANTARA_MCP_TRANSPORT": "stdio",
                "QANTARA_MCP_COMMAND": f"{sys.executable} {FIXTURE}",
                "QANTARA_MCP_CHAT_TOOL": "voice_chat",
            },
            clear=False,
        ):
            adapter = create_adapter(AdapterConfig(kind="mcp_client", name="mcp"))

        self.assertIsInstance(adapter, MCPClientAdapter)


if __name__ == "__main__":
    unittest.main()
