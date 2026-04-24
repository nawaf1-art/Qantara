from __future__ import annotations

import asyncio
import unittest

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter
from gateway.transport_spike.runtime import GatewayRuntime, Session
from gateway.transport_spike.server import stream_assistant_turn
from gateway.transport_spike.speech import cancel_active_turn
from tests.test_transport_spike import DummyWebSocket, FakeSTT, FakeTTS


class _BlockingAdapter(RuntimeAdapter):
    """Adapter that streams the first delta, then blocks so the test can
    inject a cancel mid-turn. Mirrors real backends where a model is still
    generating when the user barges in."""

    def __init__(self) -> None:
        super().__init__(AdapterConfig(kind="mock", name="blocking"))
        self._first_delta_released = asyncio.Event()
        self._cancel_called = asyncio.Event()
        self._cancel_arguments: dict | None = None

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
        yield {"type": "assistant_text_delta", "text": "Hello there, I was about to say"}
        self._first_delta_released.set()
        # Block until cancelled — simulates a model mid-generation
        await self._cancel_called.wait()
        yield {"type": "cancel_acknowledged"}

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict:
        self._cancel_arguments = cancel_context
        self._cancel_called.set()
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")


def _make_session() -> tuple[Session, list[dict], DummyWebSocket, _BlockingAdapter]:
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
    adapter = _BlockingAdapter()
    session.binding.adapter = adapter
    return session, events, ws, adapter


class BargeInTests(unittest.IsolatedAsyncioTestCase):
    async def test_barge_in_emits_turn_interrupted_with_partial_text(self) -> None:
        session, events, ws, adapter = _make_session()

        # Start the turn, wait for the first delta to land
        turn_task = asyncio.create_task(stream_assistant_turn(session, "hello"))
        session.current_turn_task = turn_task
        await adapter._first_delta_released.wait()

        # Barge-in
        await cancel_active_turn(session, "speech_detected")

        # Wait for turn to wind down
        await turn_task

        # turn_interrupted event fired with partial_text
        interrupted = [e for e in events if e["event_name"] == "turn_interrupted"]
        self.assertEqual(len(interrupted), 1)
        payload = interrupted[0]["payload"]
        self.assertEqual(payload["partial_text"], "Hello there, I was about to say")
        self.assertIn("resumable", payload)
        self.assertIn("interrupted_during_state", payload)
        self.assertEqual(interrupted[0]["source"], "session")

        # Client receives the turn_interrupted message
        ws_msgs = [m for m in ws.strings if m.get("type") == "turn_interrupted"]
        self.assertEqual(len(ws_msgs), 1)
        self.assertEqual(ws_msgs[0]["partial_text"], "Hello there, I was about to say")

    async def test_barge_in_transitions_to_interrupted_then_idle(self) -> None:
        session, events, _ws, adapter = _make_session()

        turn_task = asyncio.create_task(stream_assistant_turn(session, "hello"))
        session.current_turn_task = turn_task
        await adapter._first_delta_released.wait()
        await cancel_active_turn(session, "speech_detected")
        await turn_task

        transitions = [
            (e["payload"]["previous_state"], e["payload"]["current_state"])
            for e in events
            if e["event_name"] == "session_state_changed"
        ]
        # Must include a transition to interrupted, then back to idle
        to_interrupted = [t for t in transitions if t[1] == "interrupted"]
        self.assertEqual(len(to_interrupted), 1)
        self.assertEqual(transitions[-1][1], "idle")
        self.assertEqual(session.state, "idle")

    async def test_no_turn_interrupted_when_nothing_streamed_yet(self) -> None:
        session, events, _ws, _adapter = _make_session()
        # cancel_active_turn is a no-op when there's no active turn
        await cancel_active_turn(session, "speech_detected")
        interrupted = [e for e in events if e["event_name"] == "turn_interrupted"]
        self.assertEqual(interrupted, [])

    async def test_subsequent_turn_starts_cleanly_after_interruption(self) -> None:
        """Regression guard: the livekit-agents / pipecat interruption-deadlock
        pattern. After a barge-in, a new turn must start and complete without
        hanging."""
        from tests.test_transport_spike import DeltaOnlyAdapter

        session, events, _ws, adapter = _make_session()

        turn_task = asyncio.create_task(stream_assistant_turn(session, "first"))
        session.current_turn_task = turn_task
        await adapter._first_delta_released.wait()
        await cancel_active_turn(session, "speech_detected")
        await turn_task

        # Swap in a simple adapter and run a fresh turn
        session.binding.adapter = DeltaOnlyAdapter()
        session.current_turn_handle = None
        session.current_turn_task = None

        await asyncio.wait_for(stream_assistant_turn(session, "second"), timeout=5.0)
        if session.speech_task is not None:
            await session.speech_task

        self.assertEqual(session.state, "idle")
        # And the second turn's final text made it through
        final = [e for e in events if e["event_name"] == "assistant_output_completed"]
        self.assertGreaterEqual(len(final), 1)


class _BufferingAdapter(RuntimeAdapter):
    """Adapter that blocks without streaming any deltas first — models the
    OpenClaw pattern where the full final_text arrives as one delta at the
    very end, so current_turn_buffered_text is empty throughout the
    thinking phase. Used to confirm turn_interrupted still fires."""

    def __init__(self) -> None:
        super().__init__(AdapterConfig(kind="mock", name="buffering"))
        self._cancel_called = asyncio.Event()
        self._streaming_started = asyncio.Event()

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
        self._streaming_started.set()
        # Sit in "thinking" — no delta emitted yet
        await self._cancel_called.wait()
        yield {"type": "cancel_acknowledged"}

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict:
        self._cancel_called.set()
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")


class BargeInEdgeCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_interrupted_fires_even_with_empty_partial_text(self) -> None:
        """Regression: OpenClaw-style adapters buffer their entire response
        until the end. Before fix, cancel mid-thinking produced no
        turn_interrupted event because the guard required non-empty
        current_turn_buffered_text. Now: the event fires unconditionally
        whenever a real turn is cancelled, with empty partial_text if
        nothing streamed yet."""
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
        adapter = _BufferingAdapter()
        session.binding.adapter = adapter

        turn_task = asyncio.create_task(stream_assistant_turn(session, "hi"))
        session.current_turn_task = turn_task
        await adapter._streaming_started.wait()

        # Nothing has streamed; buffered text is empty
        self.assertEqual(session.current_turn_buffered_text, "")

        await cancel_active_turn(session, "speech_detected")
        await turn_task

        interrupted = [e for e in events if e["event_name"] == "turn_interrupted"]
        self.assertEqual(
            len(interrupted), 1,
            "turn_interrupted must fire when a real turn is cancelled, "
            "regardless of whether the adapter has streamed any deltas yet",
        )
        self.assertEqual(interrupted[0]["payload"]["partial_text"], "")
        self.assertEqual(interrupted[0]["payload"]["interrupted_during_state"], "thinking")

        ws_msgs = [m for m in ws.strings if m.get("type") == "turn_interrupted"]
        self.assertEqual(len(ws_msgs), 1)

    async def test_barge_in_survives_racing_speech_start_state_change(self) -> None:
        """Regression: the client sends vad_state and clear_playback
        concurrently. If vad_state processes first, set_state(listening)
        lands BEFORE cancel_active_turn captures the pre-cancel state, and
        the previous guard `if state in {thinking,speaking}` would skip the
        interrupted transition. Now: interrupted fires whenever a real
        turn is being cancelled."""
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
        adapter = _BufferingAdapter()
        session.binding.adapter = adapter

        turn_task = asyncio.create_task(stream_assistant_turn(session, "hi"))
        session.current_turn_task = turn_task
        await adapter._streaming_started.wait()

        # Simulate the race: concurrent vad_state message flipped the
        # session into "listening" BEFORE cancel_active_turn runs.
        await session.set_state("listening", reason="speech_start_detected_race")

        await cancel_active_turn(session, "playback_cleared")
        await turn_task

        transitions = [
            (e["payload"]["previous_state"], e["payload"]["current_state"])
            for e in events
            if e["event_name"] == "session_state_changed"
        ]
        # We must see a transition into interrupted despite the racing
        # listening state
        to_interrupted = [t for t in transitions if t[1] == "interrupted"]
        self.assertEqual(
            len(to_interrupted), 1,
            f"expected exactly one transition to interrupted, got: {transitions}",
        )

        # And turn_interrupted event fires
        interrupted = [e for e in events if e["event_name"] == "turn_interrupted"]
        self.assertEqual(len(interrupted), 1)


class BargeInLatencyBenchmark(unittest.IsolatedAsyncioTestCase):
    """Latency budget for the interruption path. Documented in
    docs/BENCHMARKS.md — these numbers are what the public comparison
    against livekit-agents / pipecat will be held to.
    """

    async def test_cancel_to_turn_interrupted_under_100ms(self) -> None:
        import time

        session, events, _ws, adapter = _make_session()

        turn_task = asyncio.create_task(stream_assistant_turn(session, "hello"))
        session.current_turn_task = turn_task
        await adapter._first_delta_released.wait()

        cancel_started_ms = time.monotonic() * 1000
        await cancel_active_turn(session, "speech_detected")
        await turn_task
        cancel_finished_ms = time.monotonic() * 1000

        interrupted = [e for e in events if e["event_name"] == "turn_interrupted"]
        self.assertEqual(len(interrupted), 1)

        # Total cancel path latency budget: 100ms locally. Real network adapters
        # will add transport time but the gateway-side path must stay tight.
        elapsed_ms = cancel_finished_ms - cancel_started_ms
        self.assertLess(
            elapsed_ms,
            100.0,
            f"barge-in path took {elapsed_ms:.1f}ms — budget is 100ms (see docs/BENCHMARKS.md)",
        )


if __name__ == "__main__":
    unittest.main()
