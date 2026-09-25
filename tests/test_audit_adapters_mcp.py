"""Regression tests for the 2026-09-24 audit: MCP client adapter (B-6/AD-9).

One long-lived MCP client session per adapter (reconnect on failure), a
stable session id argument, a cached tool list, real cancellation, and
readable errors instead of ExceptionGroup text.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.base import AdapterConfig
from adapters.mcp_client import MCPClientAdapter, _readable_error

SERVER_SOURCE = '''
from __future__ import annotations

import asyncio
import os
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("audit-agent", log_level="ERROR")
HISTORY: dict[str, list[str]] = {}
MARKER = sys.argv[1]


@mcp.tool(name="chat")
async def chat(
    message: str,
    session_id: str | None = None,
    turn_context: dict | None = None,
    client_context: dict | None = None,
) -> str:
    if message == "crash":
        os._exit(3)
    if message.startswith("slow"):
        await asyncio.sleep(3.0)
        with open(MARKER, "a", encoding="utf-8") as handle:
            handle.write(f"side effect for {message!r}\\n")
    HISTORY.setdefault(session_id or "", []).append(message)
    client = (client_context or {}).get("client_name", "")
    return f"pid={os.getpid()} session={session_id} history={HISTORY[session_id or '']} client={client}"


if __name__ == "__main__":
    mcp.run()
'''


def _field(text: str, name: str) -> str:
    for part in text.split(" "):
        if part.startswith(f"{name}="):
            return part[len(name) + 1:]
    return ""


class MCPLongLivedSessionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.server_path = Path(cls._tmp.name) / "audit_mcp_server.py"
        cls.server_path.write_text(SERVER_SOURCE, encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    async def asyncSetUp(self) -> None:
        self.marker = Path(self._tmp.name) / f"side_effect_{id(self)}.txt"
        if self.marker.exists():
            self.marker.unlink()
        command = " ".join(shlex.quote(part) for part in (sys.executable, str(self.server_path), str(self.marker)))
        self.adapter = MCPClientAdapter(
            AdapterConfig(
                kind="mcp_client",
                name="audit",
                options={"transport": "stdio", "command": command, "chat_tool": "chat", "timeout_seconds": 20},
            )
        )

    async def asyncTearDown(self) -> None:
        await self.adapter.aclose()

    async def _turn(self, session: str, text: str) -> list[dict]:
        turn = await self.adapter.submit_user_turn(session, text, {"output_language": "en"})
        return [event async for event in self.adapter.stream_assistant_output(session, turn)]

    @staticmethod
    def _final(events: list[dict]) -> str:
        return next(event for event in events if event["type"] == "assistant_text_final")["text"]

    async def test_turns_share_one_server_process_and_a_stable_session_id(self) -> None:
        session = await self.adapter.start_or_resume_session({"client_session_id": "browser-42", "client_name": "web"})
        first = self._final(await self._turn(session, "my name is Nawaf"))
        second = self._final(await self._turn(session, "what is my name?"))
        self.assertEqual(_field(first, "pid"), _field(second, "pid"))
        self.assertEqual(_field(second, "session"), "browser-42")
        self.assertIn("my name is Nawaf", second)
        self.assertEqual(_field(second, "client"), "web")

    async def test_distinct_sessions_get_distinct_session_ids(self) -> None:
        first = await self.adapter.start_or_resume_session({})
        second = await self.adapter.start_or_resume_session({})
        text_a = self._final(await self._turn(first, "a"))
        text_b = self._final(await self._turn(second, "b"))
        self.assertNotEqual(_field(text_a, "session"), _field(text_b, "session"))
        self.assertTrue(_field(text_a, "session"))

    async def test_tool_list_is_cached_across_turns(self) -> None:
        from mcp import ClientSession

        original = ClientSession.list_tools
        calls = 0

        async def counting_list_tools(session, *args, **kwargs):
            nonlocal calls
            calls += 1
            return await original(session, *args, **kwargs)

        session = await self.adapter.start_or_resume_session({})
        with patch.object(ClientSession, "list_tools", counting_list_tools):
            for index in range(3):
                await self._turn(session, f"turn {index}")
        self.assertEqual(calls, 1)

    async def test_cancel_stops_the_tool_call_on_the_server(self) -> None:
        session = await self.adapter.start_or_resume_session({})
        await self._turn(session, "warm up")  # connection established
        turn = await self.adapter.submit_user_turn(session, "slow: send the email", {})

        async def consume() -> list[dict]:
            return [event async for event in self.adapter.stream_assistant_output(session, turn)]

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.5)
        result = await self.adapter.cancel_turn(session, turn, {"reason": "barge_in"})
        self.assertEqual(result["status"], "acknowledged")
        events = await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual(events[-1]["type"], "cancel_acknowledged")

        await asyncio.sleep(3.2)
        self.assertFalse(self.marker.exists(), "cancelled MCP call still produced its side effect")
        # The shared connection survives a cancelled call.
        self.assertIn("after cancel", self._final(await self._turn(session, "after cancel")))

    async def test_cancel_for_unknown_turn_is_a_noop(self) -> None:
        session = await self.adapter.start_or_resume_session({})
        result = await self.adapter.cancel_turn(session, "no-such-turn")
        self.assertEqual(result["status"], "acknowledged")

    async def test_server_crash_fails_readably_and_next_turn_reconnects(self) -> None:
        session = await self.adapter.start_or_resume_session({})
        before = self._final(await self._turn(session, "hello"))
        crashed = await asyncio.wait_for(self._turn(session, "crash"), timeout=10.0)
        self.assertEqual(crashed[-1]["type"], "turn_failed")
        self.assertNotIn("TaskGroup", crashed[-1]["message"])
        after = self._final(await asyncio.wait_for(self._turn(session, "hello again"), timeout=15.0))
        self.assertNotEqual(_field(before, "pid"), _field(after, "pid"))

    async def test_aclose_stops_the_server_process(self) -> None:
        session = await self.adapter.start_or_resume_session({})
        pid = int(_field(self._final(await self._turn(session, "hello")), "pid"))
        await self.adapter.aclose()
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(0.1)
        else:
            self.fail("MCP server process still running after aclose()")


class MCPErrorReadabilityTests(unittest.IsolatedAsyncioTestCase):
    def test_exception_group_is_unwrapped(self) -> None:
        group = ExceptionGroup("unhandled errors in a TaskGroup", [FileNotFoundError(2, "No such file", "agent-bin")])
        message = _readable_error(group)
        self.assertNotIn("TaskGroup", message)
        self.assertIn("No such file", message)

    async def test_missing_command_fails_turn_with_readable_message(self) -> None:
        adapter = MCPClientAdapter(
            AdapterConfig(
                kind="mcp_client",
                name="missing",
                options={"transport": "stdio", "command": "/nonexistent/qantara-mcp-agent", "chat_tool": "chat", "timeout_seconds": 5},
            )
        )
        try:
            session = await adapter.start_or_resume_session({})
            turn = await adapter.submit_user_turn(session, "hello", {})
            events = [event async for event in adapter.stream_assistant_output(session, turn)]
        finally:
            await adapter.aclose()
        self.assertEqual(events[-1]["type"], "turn_failed")
        self.assertNotIn("TaskGroup", events[-1]["message"])
        self.assertTrue(events[-1]["message"])


if __name__ == "__main__":
    unittest.main()
