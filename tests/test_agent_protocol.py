from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter, make_activity_event
from gateway.transport_spike.runtime import GatewayRuntime, Session
from gateway.transport_spike.server import stream_assistant_turn
from tests.test_transport_spike import DummyWebSocket, FakeSTT, FakeTTS

REPO_ROOT = Path(__file__).resolve().parent.parent


class MakeActivityEventTests(unittest.TestCase):
    def test_minimal_event(self) -> None:
        event = make_activity_event(activity_type="thinking", summary="Pondering")
        self.assertEqual(event["type"], "assistant_activity")
        self.assertEqual(event["activity_type"], "thinking")
        self.assertEqual(event["summary"], "Pondering")
        self.assertNotIn("progress", event)
        self.assertNotIn("tool_name", event)

    def test_unknown_activity_type_falls_back_to_other(self) -> None:
        event = make_activity_event(activity_type="exfiltrating", summary="x")
        self.assertEqual(event["activity_type"], "other")

    def test_tool_call_metadata_round_trips(self) -> None:
        event = make_activity_event(
            activity_type="tool_call",
            summary="Calling weather tool",
            tool_name="get_weather",
            parameters={"city": "Riyadh"},
            confidence=0.9,
            progress=0.5,
        )
        self.assertEqual(event["tool_name"], "get_weather")
        self.assertEqual(event["parameters"], {"city": "Riyadh"})
        self.assertEqual(event["confidence"], 0.9)
        self.assertEqual(event["progress"], 0.5)

    def test_progress_and_confidence_clamped(self) -> None:
        event = make_activity_event(
            activity_type="tool_call", summary="x", progress=4.2, confidence=-1.0
        )
        self.assertEqual(event["progress"], 1.0)
        self.assertEqual(event["confidence"], 0.0)

    def test_non_dict_parameters_rejected(self) -> None:
        event = make_activity_event(
            activity_type="tool_call", summary="x", parameters="DROP TABLE"
        )
        self.assertNotIn("parameters", event)

    def test_activity_text_fields_are_type_checked_and_bounded(self) -> None:
        event = make_activity_event(
            activity_type="tool_call",
            summary="s" * 5000,
            tool_name="t" * 300,
        )
        self.assertEqual(len(event["summary"]), 4096)
        self.assertEqual(len(event["tool_name"]), 256)

        malformed = make_activity_event(
            activity_type="thinking",
            summary={"not": "text"},
        )
        self.assertEqual(malformed["summary"], "")


class _ActivityAdapter(RuntimeAdapter):
    """Yields one assistant_activity event then completes the turn."""

    def __init__(self, activity: dict) -> None:
        super().__init__(AdapterConfig(kind="mock", name="activity"))
        self._activity = activity

    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        return "runtime-session"

    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        return "turn-1"

    async def stream_assistant_output(self, session_handle: str, turn_handle: str):
        yield {"type": "assistant_activity", **self._activity}
        yield {"type": "assistant_text_final", "text": "done"}

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict:
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")


class GatewayActivityForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def _run_turn(self, activity: dict) -> tuple[list[dict], DummyWebSocket]:
        events: list[dict] = []
        runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda record: events.append(record),
        )
        ws = DummyWebSocket()
        session = Session(ws, runtime)
        runtime.register_session(session)
        session.binding.adapter = _ActivityAdapter(activity)
        await asyncio.wait_for(stream_assistant_turn(session, "hi"), timeout=5.0)
        if session.speech_task is not None:
            await session.speech_task
        return events, ws

    async def test_tool_call_metadata_forwarded_to_client(self) -> None:
        events, ws = await self._run_turn({
            "activity_type": "tool_call",
            "summary": "Calling weather tool",
            "tool_name": "get_weather",
            "parameters": {"city": "Riyadh"},
            "confidence": 0.9,
        })
        ws_msgs = [m for m in ws.strings if m.get("type") == "assistant_activity"]
        self.assertEqual(len(ws_msgs), 1)
        self.assertEqual(ws_msgs[0]["tool_name"], "get_weather")
        self.assertEqual(ws_msgs[0]["parameters"], {"city": "Riyadh"})
        self.assertEqual(ws_msgs[0]["confidence"], 0.9)
        sink = [e for e in events if e["event_name"] == "assistant_activity"]
        self.assertEqual(sink[0]["payload"]["tool_name"], "get_weather")
        self.assertEqual(sink[0]["payload"]["parameters"], {"city": "Riyadh"})

    async def test_invalid_metadata_dropped_not_forwarded(self) -> None:
        events, ws = await self._run_turn({
            "activity_type": "tool_call",
            "summary": "weird adapter",
            "tool_name": 1234,
            "parameters": ["not", "a", "dict"],
            "confidence": "high",
        })
        ws_msgs = [m for m in ws.strings if m.get("type") == "assistant_activity"]
        self.assertEqual(len(ws_msgs), 1)
        self.assertNotIn("tool_name", ws_msgs[0])
        self.assertNotIn("parameters", ws_msgs[0])
        self.assertNotIn("confidence", ws_msgs[0])

    async def test_oversized_parameters_dropped(self) -> None:
        events, ws = await self._run_turn({
            "activity_type": "tool_call",
            "summary": "huge params",
            "parameters": {"blob": "x" * 10000},
        })
        ws_msgs = [m for m in ws.strings if m.get("type") == "assistant_activity"]
        self.assertEqual(len(ws_msgs), 1)
        self.assertNotIn("parameters", ws_msgs[0])


class MCPActivityMetadataTests(unittest.TestCase):
    def test_mcp_activity_event_includes_tool_name(self) -> None:
        from adapters.mcp_client import MCPClientAdapter

        adapter = MCPClientAdapter(
            AdapterConfig(
                kind="mcp_client",
                name="test",
                options={"command": "true", "chat_tool": "house_chat"},
            )
        )
        event = adapter._activity_event("working on it", 1.0, 2.0)
        self.assertEqual(event["activity_type"], "tool_call")
        self.assertEqual(event["tool_name"], "house_chat")
        self.assertEqual(event["progress"], 0.5)


class ProtocolArtifactsTests(unittest.TestCase):
    def test_protocol_spec_document_exists_and_covers_v1_events(self) -> None:
        spec = REPO_ROOT / "protocols" / "agent.md"
        self.assertTrue(spec.is_file(), "protocols/agent.md must exist (0.2.9)")
        body = spec.read_text(encoding="utf-8")
        for required in (
            "assistant_activity",
            "session_state_changed",
            "turn_interrupted",
            "assistant_text_delta",
            "assistant_text_final",
            "cancel_acknowledged",
            "turn_failed",
            "tool_name",
            "parameters",
            "confidence",
        ):
            self.assertIn(required, body, f"protocols/agent.md missing {required}")

    def test_client_renders_tool_parameters_on_hover(self) -> None:
        page = (REPO_ROOT / "client" / "transport-spike" / "index.html").read_text(encoding="utf-8")
        self.assertIn("line.title", page)
        self.assertIn("payload.parameters", page)


if __name__ == "__main__":
    unittest.main()
