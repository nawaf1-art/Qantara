"""Turn lifecycle regressions from the 2026-09-24 audit.

Q-03 (silent backend failures), Q-05a (cancelled speech task poisons the
next reply), Q-08 / LC-K1 / LC-5 (duplicate cancel events, text after
interrupt), LC-12 (barge-in during session start), B-5 (state after
barge-in), V-9 (voice/language leak), LC-K6 (dead ``resumable``).
Derived from docs/audits/2026-09-24-probes/lifecycle/probe_silent_turn_failure.py,
probe_k1_*.py, probe_k2_hol_and_poisoned_chain.py,
probe_bargein_during_session_start.py, probe_state_after_bargein.py,
probe_text_after_interrupt.py and speech/probe_voice_sticky.py.
"""
from __future__ import annotations

import asyncio
import unittest

from adapters.base import RuntimeAdapter
from gateway.transport_spike.runtime import Session
from gateway.transport_spike.speech import (
    cancel_active_turn,
    enqueue_speech,
    start_assistant_turn,
    stream_assistant_turn,
)
from tests.test_audit_lifecycle_support import (
    SampleTTS,
    ScriptAdapter,
    count_events,
    make_runtime,
    wait_until,
)
from tests.test_transport_spike import DummyWebSocket, FakeTTS


def new_session(adapter: RuntimeAdapter, tts: FakeTTS | None = None) -> tuple[Session, list[dict], DummyWebSocket]:
    runtime, events = make_runtime(adapter, tts=tts)
    ws = DummyWebSocket()
    session = Session(ws, runtime)
    runtime.register_session(session)
    return session, events, ws


def of_type(ws: DummyWebSocket, message_type: str) -> list[dict]:
    return [m for m in ws.strings if m.get("type") == message_type]


class _FailingSubmitAdapter(ScriptAdapter):
    def __init__(self, failures: int, exc: Exception | None = None) -> None:
        super().__init__()
        self.failures = failures
        self.exc = exc or RuntimeError("unknown session handle")

    async def submit_user_turn(self, session_handle, transcript, turn_context=None):
        self.submits.append((session_handle, transcript, dict(turn_context or {})))
        if len(self.submits) <= self.failures:
            raise self.exc
        return f"turn-{len(self.submits)}"


class _FailingStartAdapter(ScriptAdapter):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    async def start_or_resume_session(self, client_context=None):
        self.sessions_started += 1
        if self.sessions_started <= self.failures:
            raise ConnectionError("backend down")
        return f"rt-{self.sessions_started}"


class _FailingStreamAdapter(ScriptAdapter):
    async def stream_assistant_output(self, session_handle, turn_handle):
        yield {"type": "assistant_text_delta", "text": "Partial answer"}
        raise TimeoutError()


class BackendFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_handle_is_reset_and_submit_retried_once(self) -> None:
        adapter = _FailingSubmitAdapter(failures=1)
        session, events, ws = new_session(adapter)
        session.runtime_session_handle = "stale-handle"
        await stream_assistant_turn(session, "hello")
        self.assertEqual(len(adapter.submits), 2)
        self.assertEqual(adapter.submits[0][0], "stale-handle")
        self.assertEqual(adapter.submits[1][0], "rt-1", "retry must use a fresh backend session")
        self.assertEqual(session.runtime_session_handle, "rt-1")
        self.assertEqual(of_type(ws, "turn_failed"), [])
        self.assertTrue(of_type(ws, "assistant_text_final"))

    async def test_repeated_submit_failure_reports_turn_failed(self) -> None:
        adapter = _FailingSubmitAdapter(failures=5)
        session, events, ws = new_session(adapter)
        await start_assistant_turn(session, "hello")
        task = session.current_turn_task
        await asyncio.wait({task})
        self.assertIsNone(task.exception(), "adapter errors must not escape the turn task")
        self.assertEqual(len(adapter.submits), 2, "retry exactly once")
        failed = of_type(ws, "turn_failed")
        self.assertEqual(len(failed), 1)
        self.assertIn("unknown session handle", failed[0]["message"])
        self.assertIn("failure_kind", failed[0])
        self.assertIn("retriable", failed[0])
        self.assertGreaterEqual(count_events(events, "recoverable_error"), 1)
        self.assertEqual(session.state, "idle")
        self.assertEqual(of_type(ws, "turn_state")[-1]["state"], "idle")

    async def test_session_start_failure_retries_then_reports(self) -> None:
        adapter = _FailingStartAdapter(failures=1)
        session, _events, ws = new_session(adapter)
        await stream_assistant_turn(session, "hello")
        self.assertEqual(adapter.sessions_started, 2)
        self.assertEqual(of_type(ws, "turn_failed"), [])

        adapter2 = _FailingStartAdapter(failures=9)
        session2, _events2, ws2 = new_session(adapter2)
        await stream_assistant_turn(session2, "hello")
        self.assertEqual(len(of_type(ws2, "turn_failed")), 1)
        self.assertEqual(adapter2.submits, [])

    async def test_stream_failure_reports_turn_failed_without_retry(self) -> None:
        adapter = _FailingStreamAdapter()
        session, events, ws = new_session(adapter)
        await stream_assistant_turn(session, "hello")
        failed = of_type(ws, "turn_failed")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["failure_kind"], "timeout")
        self.assertTrue(failed[0]["retriable"])
        self.assertEqual(len(adapter.submits), 1)

    async def test_adapter_turn_failed_passes_failure_kind_and_retriable(self) -> None:
        adapter = ScriptAdapter([
            {"type": "turn_failed", "message": "agent crashed", "failure_kind": "agent_error", "retriable": False},
        ])
        session, _events, ws = new_session(adapter)
        await stream_assistant_turn(session, "hello")
        failed = of_type(ws, "turn_failed")
        self.assertEqual(failed, [{"type": "turn_failed", "message": "agent crashed", "failure_kind": "agent_error", "retriable": False}])

    async def test_malformed_adapter_events_do_not_kill_the_turn(self) -> None:
        adapter = ScriptAdapter([
            {"text": "no type"},
            {"type": "assistant_text_delta"},
            {"type": "assistant_text_delta", "text": 42},
            "not a dict",
            {"type": "assistant_text_delta", "text": "Fine."},
            {"type": "assistant_text_final"},
            {"type": "turn_completed"},
        ])
        session, _events, ws = new_session(adapter)
        await stream_assistant_turn(session, "hello")
        self.assertEqual(of_type(ws, "turn_failed"), [])
        self.assertEqual(of_type(ws, "assistant_text_final")[-1]["text"], "Fine.")

    async def test_turn_task_is_retained_by_runtime(self) -> None:
        adapter = ScriptAdapter()
        adapter.block_after = 0
        session, _events, _ws = new_session(adapter)
        await start_assistant_turn(session, "hello")
        self.assertIn(session.current_turn_task, session.runtime._background_tasks)
        adapter.release_stream.set()
        await asyncio.wait({session.current_turn_task})


class PoisonedSpeechChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_head_task_does_not_silence_next_segment(self) -> None:
        tts = SampleTTS(samples_per_call=160)
        session, _events, ws = new_session(ScriptAdapter(), tts=tts)

        async def never() -> None:
            await asyncio.Event().wait()

        head = asyncio.create_task(never())
        session.speech_task = head
        head.cancel()
        enqueue_speech(session, "Still spoken.", session.speech_generation)
        await asyncio.wait({session.speech_task})
        self.assertEqual(tts.spoken, ["Still spoken."])
        self.assertTrue(ws.bytes_payloads)

    async def test_force_cancel_during_synthesis_does_not_silence_next_turn(self) -> None:
        import os

        os.environ["QANTARA_TURN_CANCEL_GRACE_MS"] = "20"
        self.addCleanup(os.environ.pop, "QANTARA_TURN_CANCEL_GRACE_MS", None)
        tts = SampleTTS(samples_per_call=160)
        gate = tts.gate(1)  # second sentence of turn 1 synthesises slowly
        adapter = ScriptAdapter([
            {"type": "assistant_text_delta", "text": "First sentence."},
            {"type": "assistant_text_delta", "text": " Second sentence is long."},
            {"type": "turn_completed"},
        ])
        session, _events, ws = new_session(adapter, tts=tts)
        await start_assistant_turn(session, "turn one")
        first_task = session.current_turn_task
        await asyncio.wait_for(tts.entered[1].wait(), timeout=2.0)

        session.playback_generation += 1
        session.speech_generation += 1
        await cancel_active_turn(session, "playback_cleared")
        await asyncio.wait_for(asyncio.wait({first_task}), timeout=2.0)
        gate.set()

        adapter.events = [{"type": "assistant_text_final", "text": "Hello again, this is the whole reply."}]
        frames_before = len(ws.bytes_payloads)
        await start_assistant_turn(session, "turn two")
        await asyncio.wait_for(asyncio.wait({session.current_turn_task}), timeout=2.0)
        self.assertIn("Hello again, this is the whole reply.", tts.spoken)
        self.assertGreater(len(ws.bytes_payloads), frames_before, "turn two must produce audio")


class CancelOwnershipTests(unittest.IsolatedAsyncioTestCase):
    def _blocking_adapter(self) -> ScriptAdapter:
        adapter = ScriptAdapter([
            {"type": "assistant_text_delta", "text": "Here is a long answer that"},
            {"type": "assistant_text_delta", "text": " keeps going after the cancel."},
            {"type": "turn_completed"},
        ])
        adapter.block_after = 1
        return adapter

    async def test_concurrent_cancels_are_deduplicated(self) -> None:
        adapter = self._blocking_adapter()
        cancel_gate = asyncio.Event()
        adapter.cancel_delay_event = cancel_gate
        session, events, ws = new_session(adapter)
        await start_assistant_turn(session, "tell me a story")
        await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)

        first = asyncio.create_task(cancel_active_turn(session, "playback_cleared"))
        second = asyncio.create_task(cancel_active_turn(session, "voice_interrupt"))
        await asyncio.sleep(0)
        cancel_gate.set()
        await asyncio.wait_for(asyncio.gather(first, second), 2.0)
        await wait_until(lambda: session.current_turn_task is None)

        self.assertEqual(len(adapter.cancel_calls), 1)
        self.assertEqual(count_events(events, "turn_interrupted"), 1)
        self.assertEqual(count_events(events, "turn_cancel_requested"), 1)
        self.assertEqual(len(of_type(ws, "turn_interrupted")), 1)
        self.assertEqual(len(of_type(ws, "cancel_status")), 1, "adapter-streamed cancel_acknowledged must not duplicate cancel_status")

    async def test_single_cancel_sends_one_cancel_status(self) -> None:
        adapter = self._blocking_adapter()
        session, _events, ws = new_session(adapter)
        await start_assistant_turn(session, "tell me a story")
        await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)
        await cancel_active_turn(session, "speech_detected")
        await wait_until(lambda: session.current_turn_task is None)
        self.assertEqual(len(of_type(ws, "cancel_status")), 1)

    async def test_no_text_is_sent_or_recorded_after_interrupt(self) -> None:
        adapter = self._blocking_adapter()
        adapter.ack_on_cancel = False  # wedged-ish backend keeps streaming text
        session, _events, ws = new_session(adapter)
        await start_assistant_turn(session, "tell me a story")
        await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)
        await cancel_active_turn(session, "speech_detected")
        await wait_until(lambda: session.current_turn_task is None)

        interrupted_at = next(i for i, m in enumerate(ws.strings) if m.get("type") == "turn_interrupted")
        late = [m for m in ws.strings[interrupted_at:] if m.get("type") in {"assistant_text_delta", "assistant_text_final"}]
        self.assertEqual(late, [])
        assistant = [i for i in session.transcript_items if i["role"] == "assistant"]
        for item in assistant:
            self.assertNotIn("keeps going", item["text"])
            self.assertTrue(item.get("interrupted"))

    async def test_spoken_part_is_recorded_as_interrupted(self) -> None:
        adapter = ScriptAdapter([
            {"type": "assistant_text_delta", "text": "First part. "},
            {"type": "assistant_text_delta", "text": "Second part"},
            {"type": "turn_completed"},
        ])
        adapter.block_after = 2
        session, _events, _ws = new_session(adapter)
        await start_assistant_turn(session, "q")
        await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)
        await cancel_active_turn(session, "speech_detected")
        await wait_until(lambda: session.current_turn_task is None)
        assistant = [i for i in session.transcript_items if i["role"] == "assistant"]
        self.assertEqual(len(assistant), 1)
        self.assertEqual(assistant[0]["text"], "First part.")
        self.assertTrue(assistant[0]["interrupted"])

    async def test_turn_interrupted_has_no_dead_resumable_field(self) -> None:
        adapter = self._blocking_adapter()
        session, events, ws = new_session(adapter)
        await start_assistant_turn(session, "q")
        await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)
        await cancel_active_turn(session, "speech_detected")
        await wait_until(lambda: session.current_turn_task is None)
        payload = of_type(ws, "turn_interrupted")[0]
        self.assertNotIn("resumable", payload)
        self.assertIn("partial_text", payload)
        self.assertIn("interrupted_during_state", payload)


class _SlowStartAdapter(ScriptAdapter):
    def __init__(self) -> None:
        super().__init__([{"type": "assistant_text_final", "text": "ghost response"}])
        self.start_entered = asyncio.Event()
        self.release_start = asyncio.Event()

    async def start_or_resume_session(self, client_context=None):
        self.start_entered.set()
        await self.release_start.wait()
        return await super().start_or_resume_session(client_context)


class BargeInDuringSessionStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_barge_in_while_backend_session_is_starting_is_honored(self) -> None:
        adapter = _SlowStartAdapter()
        session, events, ws = new_session(adapter)
        await start_assistant_turn(session, "hello")
        await asyncio.wait_for(adapter.start_entered.wait(), 2.0)
        self.assertIsNone(session.runtime_session_handle)

        await cancel_active_turn(session, "speech_detected")
        adapter.release_start.set()
        await asyncio.wait_for(asyncio.wait({session.current_turn_task}), 2.0)

        self.assertEqual(count_events(events, "turn_interrupted"), 1)
        self.assertEqual(of_type(ws, "assistant_text_final"), [], "no ghost reply after barge-in")
        self.assertEqual(adapter.submits, [], "an interrupted turn must not be submitted")


class StateAfterBargeInTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_is_listening_when_user_is_still_speaking(self) -> None:
        adapter = ScriptAdapter([
            {"type": "assistant_text_delta", "text": "Answer"},
            {"type": "turn_completed"},
        ])
        adapter.block_after = 1
        session, _events, _ws = new_session(adapter)
        await start_assistant_turn(session, "q")
        await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)
        session.last_vad_state = "speech"
        await cancel_active_turn(session, "speech_detected")
        await wait_until(lambda: session.current_turn_task is None)
        self.assertEqual(session.state, "listening")

    async def test_state_is_idle_when_user_is_silent(self) -> None:
        session, _events, _ws = new_session(ScriptAdapter())
        await stream_assistant_turn(session, "q")
        self.assertEqual(session.state, "idle")


class VoiceAndLanguageLeakTests(unittest.IsolatedAsyncioTestCase):
    async def test_per_turn_voice_is_not_persisted(self) -> None:
        tts = FakeTTS()
        session, _events, _ws = new_session(ScriptAdapter([
            {"type": "assistant_text_final", "text": "مرحبا بك."},
        ]), tts=tts)
        session.voice_id = "fake_voice"
        session.input_language = "ar"
        await stream_assistant_turn(session, "مرحبا")
        self.assertEqual(tts.requested_voice_ids[-1], "ar_JO-kareem-medium")
        self.assertEqual(session.voice_id, "fake_voice", "the Arabic turn voice must not stick to the session")


if __name__ == "__main__":
    unittest.main()
