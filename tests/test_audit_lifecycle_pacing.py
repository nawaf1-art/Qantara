"""V-4 (server side): playback frames are paced against an absolute schedule
with a ~250 ms lead, so the client keeps a cushion instead of starving at
every frame boundary. Derived from
docs/audits/2026-09-24-probes/lifecycle/probe_playback_pacing.py and
speech/probe_pacing.py. Uses a fake clock: no wall-clock sleeps."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from gateway.transport_spike import speech
from gateway.transport_spike.runtime import Session
from tests.test_audit_lifecycle_support import ScriptAdapter, make_runtime
from tests.test_transport_spike import DummyWebSocket

FRAME = 1920
RATE = 16000


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []
        self.frames_at_sleep: list[int] = []
        self.on_sleep = None

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self.on_sleep is not None:
            self.on_sleep()
        self.now += seconds
        await asyncio.sleep(0)


def new_session() -> tuple[Session, DummyWebSocket]:
    runtime, _events = make_runtime(ScriptAdapter())
    ws = DummyWebSocket()
    session = Session(ws, runtime)
    runtime.register_session(session)
    return session, ws


class PlaybackPacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_quarter_second_is_sent_immediately_then_paced(self) -> None:
        session, ws = new_session()
        clock = FakeClock()
        clock.on_sleep = lambda: clock.frames_at_sleep.append(len(ws.bytes_payloads))
        samples = [100] * RATE  # 1 s of audio
        with patch.object(speech, "_pace_clock", clock.clock), patch.object(speech, "_pace_sleep", clock.sleep):
            await speech.send_pcm_samples(session, samples, RATE, "fake_tts", expected_generation=session.playback_generation)
        frame_seconds = FRAME / RATE
        self.assertGreaterEqual(clock.frames_at_sleep[0], 2, "the first ~250 ms must go out without waiting")
        for pause in clock.sleeps:
            self.assertLessEqual(pause, frame_seconds + 1e-9)
        # Total pacing = audio length minus the lead (never a full frame per frame).
        self.assertAlmostEqual(sum(clock.sleeps), 1.0 - speech.PLAYBACK_LEAD_SECONDS, delta=frame_seconds)
        self.assertEqual(len(ws.bytes_payloads), -(-RATE // FRAME))

    async def test_barge_in_stops_within_one_frame(self) -> None:
        session, ws = new_session()
        clock = FakeClock()
        generation = session.playback_generation

        def barge_in() -> None:
            if len(clock.sleeps) == 1:
                session.playback_generation += 1

        clock.on_sleep = barge_in
        samples = [100] * (RATE * 3)
        with patch.object(speech, "_pace_clock", clock.clock), patch.object(speech, "_pace_sleep", clock.sleep):
            await speech.send_pcm_samples(session, samples, RATE, "fake_tts", expected_generation=generation)
        sent_at_barge_in = 3  # two lead frames + the one that triggered the first sleep
        self.assertLessEqual(len(ws.bytes_payloads), sent_at_barge_in)
        stopped = [m for m in ws.strings if m.get("type") == "playback_stopped"]
        self.assertEqual(stopped[-1]["reason"], "cleared")

    async def test_cancelled_playback_reports_stopped(self) -> None:
        session, ws = new_session()
        release = asyncio.Event()

        async def blocking_sleep(_seconds: float) -> None:
            await release.wait()

        samples = [100] * (RATE * 3)
        with patch.object(speech, "_pace_sleep", blocking_sleep):
            task = asyncio.create_task(speech.send_pcm_samples(session, samples, RATE, "fake_tts", expected_generation=session.playback_generation))
            while not ws.bytes_payloads:
                await asyncio.sleep(0)
            for _ in range(20):
                await asyncio.sleep(0)
            task.cancel()
            await asyncio.wait({task})
        stopped = [m for m in ws.strings if m.get("type") == "playback_stopped"]
        self.assertTrue(stopped)
        self.assertEqual(stopped[-1]["reason"], "cleared")


if __name__ == "__main__":
    unittest.main()
