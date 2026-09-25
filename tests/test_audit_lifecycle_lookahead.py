"""V-3 (stretch): the next sentence is synthesised while the current one is
still playing (one segment of look-ahead), and a barge-in discards it."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from gateway.transport_spike import speech
from gateway.transport_spike.runtime import Session
from tests.test_audit_lifecycle_support import SampleTTS, ScriptAdapter, make_runtime, wait_until
from tests.test_transport_spike import DummyWebSocket


def new_session(tts: SampleTTS) -> tuple[Session, DummyWebSocket]:
    runtime, _events = make_runtime(ScriptAdapter(), tts=tts)
    ws = DummyWebSocket()
    session = Session(ws, runtime)
    runtime.register_session(session)
    return session, ws


class LookAheadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.playback_gate = asyncio.Event()
        self.pacing_started = asyncio.Event()

        async def gated_sleep(_seconds: float) -> None:
            self.pacing_started.set()
            await self.playback_gate.wait()

        self.patcher = patch.object(speech, "_pace_sleep", gated_sleep)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_next_sentence_synthesises_during_playback(self) -> None:
        tts = SampleTTS(samples_per_call=16000)  # 1 s per sentence: pacing kicks in
        session, _ws = new_session(tts)
        generation = session.speech_generation
        for text in ("One.", "Two.", "Three."):
            speech.enqueue_speech(session, text, generation)
        await asyncio.wait_for(self.pacing_started.wait(), 2.0)  # sentence one is playing
        await wait_until(lambda: len(tts.spoken) >= 2)
        for _ in range(20):
            await asyncio.sleep(0)
        self.assertEqual(tts.spoken, ["One.", "Two."], "exactly one sentence of look-ahead")
        self.playback_gate.set()
        await asyncio.wait({session.speech_task})
        self.assertEqual(tts.spoken, ["One.", "Two.", "Three."])

    async def test_barge_in_discards_the_prepared_sentence(self) -> None:
        tts = SampleTTS(samples_per_call=16000)
        session, ws = new_session(tts)
        generation = session.speech_generation
        speech.enqueue_speech(session, "One.", generation)
        speech.enqueue_speech(session, "Two.", generation)
        await asyncio.wait_for(self.pacing_started.wait(), 2.0)
        await wait_until(lambda: len(tts.spoken) == 2)
        frames_during_one = len(ws.bytes_payloads)

        session.playback_generation += 1
        session.speech_generation += 1
        self.playback_gate.set()
        await asyncio.wait({session.speech_task})
        self.assertLessEqual(len(ws.bytes_payloads), frames_during_one, "the pre-synthesised sentence must not play")
        statuses = [m for m in ws.strings if m.get("type") == "tts_status"]
        self.assertEqual(len(statuses), 1, "tts_status is sent only for segments that play")


if __name__ == "__main__":
    unittest.main()
