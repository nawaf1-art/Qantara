"""Q-01 / LC-1 / SP-1 / LC-13: the STT input must be the utterance, not the
last 6 seconds of the mic. Derived from
docs/audits/2026-09-24-probes/lifecycle/probe_utterance_truncation.py."""
from __future__ import annotations

import os
import unittest
from array import array
from unittest.mock import patch

from gateway.transport_spike.common import UtteranceBuffer
from tests.test_audit_lifecycle_support import (
    RecordingSTT,
    close_ws_session,
    make_runtime,
    pcm_frame,
    start_ws_session,
    wait_until,
)

FRAME = 640  # 40 ms at 16 kHz, the browser client's packet size
FRAMES_PER_SECOND = 16000 // FRAME


def feed_seconds(ws, value: int, seconds: float) -> None:
    for _ in range(int(seconds * FRAMES_PER_SECOND)):
        ws.feed_bytes(pcm_frame(value, FRAME))


class UtteranceOverWebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.stt = RecordingSTT()
        self.runtime, self.events = make_runtime(stt=self.stt)
        self.ws, self.task = await start_ws_session(self.runtime)

    async def asyncTearDown(self) -> None:
        await close_ws_session(self.ws, self.task)

    async def _transcribe(self) -> list[int]:
        before = len(self.stt.calls)
        results_before = len(self.ws.of_type("transcript_result"))
        self.ws.feed_json({"type": "transcribe_recent_audio"})
        await wait_until(lambda: len(self.ws.of_type("transcript_result")) > results_before)
        if len(self.stt.calls) == before:
            return []
        return self.stt.calls[-1]

    async def test_long_utterance_keeps_its_beginning(self) -> None:
        feed_seconds(self.ws, 0, 1.0)  # idle mic before speaking
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
        for second in range(1, 9):  # 8 s of speech, each sample tagged with its second
            feed_seconds(self.ws, second, 1.0)
        self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
        feed_seconds(self.ws, 0, 1.5)  # endpoint silence
        got = await self._transcribe()
        present = sorted({s for s in got if s})
        self.assertEqual(present, list(range(1, 9)), "every second of the utterance must reach STT")
        # ~400 ms pre-roll + 8 s speech + 1.5 s trailing silence, not the idle second before.
        self.assertLessEqual(len(got), int((0.45 + 8 + 1.5) * 16000))
        self.assertGreaterEqual(len(got), int((0.3 + 8 + 1.5) * 16000))

    async def test_language_gate_gets_speech_duration_not_buffer_length(self) -> None:
        captured: dict = {}

        def fake_resolver(**kwargs):
            captured.update(kwargs)
            return kwargs["primary_language"]

        with patch("gateway.transport_spike.language_resolution.resolve_effective_language", side_effect=fake_resolver):
            feed_seconds(self.ws, 0, 3.0)
            self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
            feed_seconds(self.ws, 5, 1.0)
            self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
            feed_seconds(self.ws, 0, 1.5)
            await self._transcribe()
        self.assertIn("duration_ms", captured)
        self.assertGreaterEqual(captured["duration_ms"], 900)
        self.assertLessEqual(captured["duration_ms"], 1100)

    async def test_idle_audio_before_speech_is_limited_to_preroll(self) -> None:
        feed_seconds(self.ws, 7, 3.0)
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
        feed_seconds(self.ws, 1, 1.0)
        self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
        got = await self._transcribe()
        idle = sum(1 for s in got if s == 7)
        self.assertGreater(idle, 0, "pre-roll must seed the utterance")
        self.assertLessEqual(idle, int(0.45 * 16000))

    async def test_buffer_is_cleared_on_submit(self) -> None:
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
        feed_seconds(self.ws, 1, 0.5)
        self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
        first = await self._transcribe()
        self.assertTrue(first)
        second = await self._transcribe()
        self.assertEqual(second, [])
        self.assertEqual(self.ws.of_type("transcript_result")[-1]["engine"], "none")

    async def test_abandoned_utterance_does_not_prefix_the_next_one(self) -> None:
        # The client may skip a submit (weak speech, cooldown). A fresh onset
        # after a long silence must start a new utterance.
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
        feed_seconds(self.ws, 3, 0.5)
        self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
        feed_seconds(self.ws, 0, 3.0)
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
        feed_seconds(self.ws, 9, 0.5)
        self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
        got = await self._transcribe()
        self.assertNotIn(3, set(got))
        self.assertIn(9, set(got))

    async def test_short_pause_continues_the_same_utterance(self) -> None:
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
        feed_seconds(self.ws, 3, 0.5)
        self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
        feed_seconds(self.ws, 0, 0.6)
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
        feed_seconds(self.ws, 9, 0.5)
        self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
        got = await self._transcribe()
        self.assertIn(3, set(got))
        self.assertIn(9, set(got))

    async def test_push_to_talk_stream_markers_bound_the_utterance(self) -> None:
        # The translate page sends no VAD, only mic_stream_started/stopped.
        self.ws.feed_json({"type": "mic_stream_started", "sample_rate": 16000})
        feed_seconds(self.ws, 4, 7.0)
        self.ws.feed_json({"type": "mic_stream_stopped"})
        got = await self._transcribe()
        self.assertEqual(len(got), 7 * 16000)

    async def test_stream_start_then_vad_uses_vad_boundaries(self) -> None:
        # The main client sends mic_stream_started once, then VAD events; the
        # idle audio between mic start and the first speech must not be kept.
        self.ws.feed_json({"type": "mic_stream_started", "sample_rate": 16000})
        feed_seconds(self.ws, 7, 3.0)
        self.ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
        feed_seconds(self.ws, 1, 1.0)
        self.ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
        got = await self._transcribe()
        self.assertLessEqual(sum(1 for s in got if s == 7), int(0.45 * 16000))


class UtteranceCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_utterance_is_capped_keeping_its_beginning(self) -> None:
        stt = RecordingSTT()
        with patch.dict(os.environ, {"QANTARA_MAX_UTTERANCE_MS": "1000"}):
            runtime, _events = make_runtime(stt=stt)
            ws, task = await start_ws_session(runtime)
        try:
            ws.feed_json({"type": "vad_state", "state": "speech", "rms": 0.2})
            feed_seconds(ws, 1, 1.0)
            feed_seconds(ws, 2, 2.0)
            ws.feed_json({"type": "vad_state", "state": "silence", "rms": 0.001})
            ws.feed_json({"type": "transcribe_recent_audio"})
            await wait_until(lambda: bool(ws.of_type("transcript_result")))
            got = stt.calls[-1]
            self.assertLessEqual(len(got), 16000)
            self.assertIn(1, set(got))
            self.assertNotIn(2, set(got))
        finally:
            await close_ws_session(ws, task)


class UtteranceBufferUnitTests(unittest.TestCase):
    def test_decodes_little_endian_frames_without_python_loops(self) -> None:
        buf = UtteranceBuffer(sample_rate=16000, max_ms=30000, preroll_ms=400)
        payload = b"".join(int(s).to_bytes(2, "little", signed=True) for s in [100, -100, 32767, -32768])
        buf.append_pcm(payload)
        samples, _speech_ms = buf.take()
        self.assertIsInstance(samples, array)
        self.assertEqual(samples.tolist(), [100, -100, 32767, -32768])

    def test_storage_is_compact(self) -> None:
        buf = UtteranceBuffer(sample_rate=16000, max_ms=30000, preroll_ms=400)
        buf.speech_started()
        buf.append_pcm(bytes(16000 * 2 * 6))
        self.assertIsInstance(buf.snapshot(), array)
        self.assertEqual(buf.snapshot().itemsize, 2)

    def test_default_cap_is_thirty_seconds(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QANTARA_MAX_UTTERANCE_MS", None)
            buf = UtteranceBuffer(sample_rate=16000)
        self.assertEqual(buf.max_samples, 30 * 16000)


if __name__ == "__main__":
    unittest.main()
