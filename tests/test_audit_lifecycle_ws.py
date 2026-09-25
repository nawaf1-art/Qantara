"""WebSocket receive-loop regressions from the 2026-09-24 audit.

V-10 / LC-K2 (barge-in blocks the loop), Q-12 call site / LC-9 (mesh
election awaited inline), V-9 (typed turns inherit the voice language),
LC-10 (duplicate client_session_id), LC-11 / SP-13 (malformed control
fields). Derived from docs/audits/2026-09-24-probes/lifecycle/
probe_k2_hol_and_poisoned_chain.py, probe_grace_bound.py,
probe_mesh_unbounded_connect.py, probe_duplicate_client_session.py and
speech/probe_typed_turn.py, speech/probe_nan.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gateway.transport_spike.runtime import Session
from tests.test_audit_lifecycle_support import (
    RecordingSTT,
    ScriptAdapter,
    close_ws_session,
    count_events,
    make_runtime,
    pcm_frame,
    start_ws_session,
    wait_until,
)


def only_session(runtime) -> Session:
    sessions = list(runtime._active_session_refs.values())
    assert len(sessions) == 1, sessions
    return sessions[0]


class BargeInDoesNotBlockLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_is_processed_while_cancel_teardown_is_pending(self) -> None:
        adapter = ScriptAdapter([
            {"type": "assistant_text_delta", "text": "A long answer"},
            {"type": "turn_completed"},
        ])
        adapter.block_after = 1
        adapter.cancel_delay_event = asyncio.Event()  # backend cancel hangs
        runtime, events = make_runtime(adapter)
        ws, task = await start_ws_session(runtime)
        try:
            ws.feed_json({"type": "submit_turn", "text": "tell me"})
            await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)
            session = only_session(runtime)
            frames_before = session.frames_in

            ws.feed_json({"type": "clear_playback"})
            for _ in range(5):
                ws.feed_bytes(pcm_frame(0))
            await wait_until(lambda: session.frames_in == frames_before + 5, timeout=0.3)
            self.assertTrue(ws.of_type("playback_cleared"))
            self.assertFalse(adapter.cancelled.is_set(), "backend cancel still pending")

            adapter.cancel_delay_event.set()
            await wait_until(lambda: session.current_turn_task is None)
            self.assertEqual(count_events(events, "turn_interrupted"), 1)
        finally:
            await close_ws_session(ws, task)

    async def test_force_cancel_after_grace_runs_in_background(self) -> None:
        adapter = ScriptAdapter([
            {"type": "assistant_text_delta", "text": "I will not stop"},
            {"type": "turn_completed"},
        ])
        adapter.block_after = 1
        adapter.ack_on_cancel = False

        async def wedged_stream(session_handle, turn_handle):
            yield {"type": "assistant_text_delta", "text": "I will not stop"}
            adapter.stream_blocked.set()
            await asyncio.Event().wait()

        adapter.stream_assistant_output = wedged_stream  # type: ignore[method-assign]
        with patch.dict(os.environ, {"QANTARA_TURN_CANCEL_GRACE_MS": "20"}):
            runtime, events = make_runtime(adapter)
            ws, task = await start_ws_session(runtime)
            try:
                ws.feed_json({"type": "submit_turn", "text": "tell me"})
                await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)
                session = only_session(runtime)
                ws.feed_json({"type": "clear_playback"})
                await wait_until(lambda: count_events(events, "turn_cancel_forced") == 1)
                await wait_until(lambda: session.current_turn_task is None)
                self.assertEqual(session.state, "idle")
            finally:
                await close_ws_session(ws, task)

    async def test_new_turn_after_barge_in_is_not_rejected(self) -> None:
        adapter = ScriptAdapter([
            {"type": "assistant_text_delta", "text": "First answer"},
            {"type": "turn_completed"},
        ])
        adapter.block_after = 1
        adapter.cancel_delay_event = asyncio.Event()
        runtime, _events = make_runtime(adapter)
        ws, task = await start_ws_session(runtime)
        try:
            ws.feed_json({"type": "submit_turn", "text": "first"})
            await asyncio.wait_for(adapter.stream_blocked.wait(), 2.0)
            ws.feed_json({"type": "clear_playback"})
            ws.feed_json({"type": "submit_turn", "text": "second"})
            await wait_until(lambda: ws.consumed >= 4)
            adapter.cancel_delay_event.set()
            await wait_until(lambda: len(adapter.submits) == 2)
            self.assertEqual(ws.of_type("turn_rejected"), [])
        finally:
            await close_ws_session(ws, task)


class _FakeRegistry:
    def list_peers(self) -> list:
        return []


class _FakeMeshController:
    def __init__(self, should_claim: bool = True) -> None:
        self.registry = _FakeRegistry()
        self.release = asyncio.Event()
        self.should_claim = should_claim
        self.calls = 0

    async def run_election(self, *, session_id: str, local_rms: float):
        self.calls += 1
        await self.release.wait()
        return SimpleNamespace(winner_node_id="peer" if not self.should_claim else "me", should_claim=self.should_claim)


class MeshElectionCallSiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_election_does_not_block_audio_and_submit_defaults_to_respond(self) -> None:
        adapter = ScriptAdapter()
        runtime, events = make_runtime(adapter, stt=RecordingSTT(text="hello there"))
        controller = _FakeMeshController()
        runtime.mesh_controller = controller
        ws, task = await start_ws_session(runtime)
        try:
            session = only_session(runtime)
            with patch("gateway.transport_spike.websocket_api.MESH_ELECTION_SUBMIT_DEADLINE_SECONDS", 0.02):
                ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.3})
                for _ in range(5):
                    ws.feed_bytes(pcm_frame(500))
                await wait_until(lambda: session.frames_in == 5, timeout=0.3)
                ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.0})
                ws.feed_json({"type": "transcribe_recent_audio", "submit_turn": True})
                await wait_until(lambda: len(adapter.submits) == 1)
            self.assertGreaterEqual(count_events(events, "mesh_election_timeout"), 1)
            controller.release.set()
        finally:
            await close_ws_session(ws, task)

    async def test_lost_election_defers_the_turn(self) -> None:
        adapter = ScriptAdapter()
        runtime, _events = make_runtime(adapter, stt=RecordingSTT(text="hello there"))
        controller = _FakeMeshController(should_claim=False)
        controller.release.set()
        runtime.mesh_controller = controller
        ws, task = await start_ws_session(runtime)
        try:
            ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.3})
            ws.feed_bytes(pcm_frame(500))
            ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.0})
            ws.feed_json({"type": "transcribe_recent_audio", "submit_turn": True})
            await wait_until(lambda: bool(ws.of_type("turn_deferred_to_peer")))
            self.assertEqual(adapter.submits, [])
        finally:
            await close_ws_session(ws, task)


class TypedTurnLanguageTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_english_turn_after_arabic_voice_turn(self) -> None:
        adapter = ScriptAdapter([{"type": "assistant_text_final", "text": "OK."}])
        stt = RecordingSTT(text="مرحبا كيف الحال", language="ar", probability=0.95)
        runtime, _events = make_runtime(adapter, stt=stt)
        ws, task = await start_ws_session(runtime)
        try:
            session = only_session(runtime)
            ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.3})
            for _ in range(60):
                ws.feed_bytes(pcm_frame(500))
            ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.0})
            ws.feed_json({"type": "transcribe_recent_audio", "submit_turn": True})
            await wait_until(lambda: len(adapter.submits) == 1)
            await wait_until(lambda: session.current_turn_task is None)
            self.assertEqual(adapter.submits[0][2].get("output_language"), "ar")

            ws.feed_json({"type": "submit_turn", "text": "What's the weather in London?"})
            await wait_until(lambda: len(adapter.submits) == 2)
            context = adapter.submits[1][2]
            self.assertEqual(context.get("output_language"), "en")
            self.assertNotEqual(context.get("input_language"), "ar")
        finally:
            await close_ws_session(ws, task)

    async def test_typed_arabic_turn_uses_arabic(self) -> None:
        adapter = ScriptAdapter([{"type": "assistant_text_final", "text": "OK."}])
        runtime, _events = make_runtime(adapter)
        ws, task = await start_ws_session(runtime)
        try:
            ws.feed_json({"type": "submit_turn", "text": "ما هو الطقس اليوم؟"})
            await wait_until(lambda: len(adapter.submits) == 1)
            self.assertEqual(adapter.submits[0][2].get("output_language"), "ar")
        finally:
            await close_ws_session(ws, task)


class DuplicateClientSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_resolution_prefers_newest_tab(self) -> None:
        runtime, _events = make_runtime(ScriptAdapter())
        ws1, task1 = await start_ws_session(runtime, "shared-id")
        ws2, task2 = await start_ws_session(runtime, "shared-id")
        try:
            sessions = list(runtime._active_session_refs.values())
            newest = next(s for s in sessions if s.websocket is ws2)
            self.assertIs(runtime.resolve_active_session(client_session_id="shared-id"), newest)
        finally:
            await close_ws_session(ws2, task2)
            await close_ws_session(ws1, task1)


class MalformedControlFieldTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runtime, self.events = make_runtime(ScriptAdapter())
        self.ws, self.task = await start_ws_session(self.runtime)
        self.session = only_session(self.runtime)

    async def asyncTearDown(self) -> None:
        await close_ws_session(self.ws, self.task)

    async def _still_alive(self) -> None:
        before = len(self.ws.of_type("session_updated"))
        self.ws.feed_json({"type": "session_update"})
        await wait_until(lambda: len(self.ws.of_type("session_updated")) > before)

    def _errors(self) -> list[dict]:
        return [e["payload"] for e in self.events if e["event_name"] == "recoverable_error"]

    async def test_non_numeric_rms_is_a_recoverable_error(self) -> None:
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": "loud"})
        await self._still_alive()
        self.assertTrue(any("rms" in str(e.get("message")) for e in self._errors()))
        self.assertEqual(self.session.last_vad_state, "speech", "the VAD transition itself still counts")

    async def test_non_string_vad_state_is_rejected(self) -> None:
        self.ws.feed_json({"type": "vad_state", "state": ["speech"]})
        await self._still_alive()
        self.assertTrue(self._errors())
        self.assertEqual(self.session.last_vad_state, "silence")

    async def test_nan_transforms_are_rejected(self) -> None:
        self.ws.feed_json({"type": "session_update", "voice_pitch": "nan", "speech_rate": "inf", "expressiveness": "nan"})
        await wait_until(lambda: bool(self.ws.of_type("session_updated")))
        self.assertEqual(self.session.voice_pitch, 0.0)
        self.assertNotEqual(self.session.speech_rate, float("inf"))
        self.assertIsNone(self.session.expressiveness)
        payload = self.ws.of_type("session_updated")[-1]
        json.dumps(payload, allow_nan=False)  # must be valid JSON
        self.assertTrue(any("voice_pitch" in str(e.get("message")) for e in self._errors()))

    async def test_json_nan_literal_rms_is_rejected(self) -> None:
        self.ws.feed_text('{"type": "vad_state", "state": "speech", "rms": NaN}')
        await self._still_alive()
        self.assertTrue(any("rms" in str(e.get("message")) for e in self._errors()))


if __name__ == "__main__":
    unittest.main()
