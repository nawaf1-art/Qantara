from __future__ import annotations

import asyncio
import unittest

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime, Session
from gateway.transport_spike.speech import stream_assistant_turn
from tests.test_transport_spike import DeltaOnlyAdapter, DummyWebSocket, FakeSTT, FakeTTS


def _make_session() -> tuple[Session, list[dict], DummyWebSocket]:
    events: list[dict] = []
    runtime = GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=FakeSTT(),
        tts=FakeTTS(),
        event_sink=lambda record: events.append(record),
    )
    ws = DummyWebSocket()
    session = Session(ws, runtime)
    return session, events, ws


class SessionStateMachineTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_state_is_idle(self) -> None:
        session, _events, _ws = _make_session()
        self.assertEqual(session.state, "idle")

    async def test_set_state_emits_session_state_changed(self) -> None:
        session, events, ws = _make_session()
        await session.set_state("listening", reason="speech_start_detected")

        state_events = [e for e in events if e["event_name"] == "session_state_changed"]
        self.assertEqual(len(state_events), 1)
        payload = state_events[0]["payload"]
        self.assertEqual(payload["previous_state"], "idle")
        self.assertEqual(payload["current_state"], "listening")
        self.assertEqual(payload["reason"], "speech_start_detected")
        self.assertIn("ms_in_previous_state", payload)
        self.assertEqual(state_events[0]["source"], "session")

        ws_msgs = [m for m in ws.strings if m.get("type") == "session_state_changed"]
        self.assertEqual(len(ws_msgs), 1)
        self.assertEqual(ws_msgs[0]["current_state"], "listening")

    async def test_set_state_is_idempotent_for_same_state(self) -> None:
        session, events, _ws = _make_session()
        await session.set_state("listening")
        events.clear()
        await session.set_state("listening")

        state_events = [e for e in events if e["event_name"] == "session_state_changed"]
        self.assertEqual(state_events, [])

    async def test_set_state_rejects_unknown_values(self) -> None:
        session, _events, _ws = _make_session()
        with self.assertRaises(ValueError):
            await session.set_state("mulching")

    async def test_state_transitions_chain_correctly(self) -> None:
        session, events, _ws = _make_session()
        await session.set_state("listening")
        await session.set_state("thinking")
        await session.set_state("speaking")
        await session.set_state("idle")

        state_events = [e for e in events if e["event_name"] == "session_state_changed"]
        self.assertEqual(
            [(e["payload"]["previous_state"], e["payload"]["current_state"]) for e in state_events],
            [("idle", "listening"), ("listening", "thinking"), ("thinking", "speaking"), ("speaking", "idle")],
        )


class SessionStateFlowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_turn_transitions_thinking_then_speaking_then_idle(self) -> None:
        session, events, _ws = _make_session()
        session.runtime.register_session(session)
        session.binding.adapter = DeltaOnlyAdapter()

        await stream_assistant_turn(session, "hello")
        if session.speech_task is not None:
            await session.speech_task

        transitions = [
            (e["payload"]["previous_state"], e["payload"]["current_state"])
            for e in events
            if e["event_name"] == "session_state_changed"
        ]
        # Must include thinking first, then idle at the end of the turn.
        # (The in-test FakeTTS returns empty samples so playback_first_frame_sent
        # never fires — "speaking" transition is covered separately by the unit
        # tests above.)
        self.assertIn(("idle", "thinking"), transitions)
        self.assertEqual(transitions[-1][1], "idle")
        self.assertEqual(session.state, "idle")

    async def test_stream_turn_stays_active_until_queued_speech_finishes(self) -> None:
        class BlockingTTS(FakeTTS):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def synthesize(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                self.started.set()
                await self.release.wait()
                voice, _ = self.resolve_voice(None)
                return [0] * 160, voice, None

        events: list[dict] = []
        tts = BlockingTTS()
        runtime = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=tts,
            event_sink=lambda record: events.append(record),
        )
        session = Session(DummyWebSocket(), runtime)
        runtime.register_session(session)
        session.binding.adapter = DeltaOnlyAdapter()

        turn_task = asyncio.create_task(stream_assistant_turn(session, "hello"))
        await asyncio.wait_for(tts.started.wait(), timeout=1.0)
        await asyncio.sleep(0)

        self.assertFalse(turn_task.done())
        self.assertIsNotNone(session.current_turn_handle)
        self.assertEqual(session.state, "thinking")

        tts.release.set()
        await asyncio.wait_for(turn_task, timeout=1.0)

        transitions = [
            (e["payload"]["previous_state"], e["payload"]["current_state"])
            for e in events
            if e["event_name"] == "session_state_changed"
        ]
        self.assertEqual(transitions[-1][1], "idle")
        self.assertIsNone(session.current_turn_handle)


if __name__ == "__main__":
    unittest.main()
