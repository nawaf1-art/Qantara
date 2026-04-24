from __future__ import annotations

import unittest
import unittest.mock

from providers.stt.base import STTProvider


class _SilentProvider(STTProvider):
    kind = "silent"

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, samples: list[int], sample_rate: int) -> str:
        return ""


class _PartialCapableProvider(STTProvider):
    kind = "partial_capable"

    def __init__(self) -> None:
        self.partial_calls: list[tuple[int, int]] = []

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, samples: list[int], sample_rate: int) -> str:
        return "final"

    async def transcribe_partial(self, samples: list[int], sample_rate: int) -> str:
        self.partial_calls.append((len(samples), sample_rate))
        return f"partial-{len(samples)}"


class STTBaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_base_provider_declares_transcribe_partial_as_optional(self) -> None:
        provider = _SilentProvider()
        self.assertFalse(provider.supports_partial)
        with self.assertRaises(NotImplementedError):
            await provider.transcribe_partial([0, 0, 0], 16000)

    async def test_provider_opt_in_is_detected(self) -> None:
        provider = _PartialCapableProvider()
        self.assertTrue(provider.supports_partial)
        result = await provider.transcribe_partial([1, 2, 3, 4], 16000)
        self.assertEqual(result, "partial-4")
        self.assertEqual(provider.partial_calls, [(4, 16000)])


class PartialHelperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from gateway.transport_spike.speech import (  # noqa: F401 - import-time check
            compute_partial_transcript,
            should_enable_partials,
        )

    def test_should_enable_partials_honors_explicit_on(self) -> None:
        import os

        from gateway.transport_spike.speech import should_enable_partials

        with unittest.mock.patch.dict(os.environ, {"QANTARA_STT_STREAMING": "on"}, clear=False):
            self.assertTrue(should_enable_partials())

    def test_should_enable_partials_honors_explicit_off(self) -> None:
        import os

        from gateway.transport_spike.speech import should_enable_partials

        with unittest.mock.patch.dict(os.environ, {"QANTARA_STT_STREAMING": "off"}, clear=False):
            self.assertFalse(should_enable_partials())

    def test_should_enable_partials_auto_defaults_off_on_cpu(self) -> None:
        import os

        from gateway.transport_spike.speech import should_enable_partials

        env = {"QANTARA_STT_STREAMING": "auto", "QANTARA_WHISPER_DEVICE": "cpu"}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            self.assertFalse(should_enable_partials())

    def test_should_enable_partials_auto_enables_on_cuda(self) -> None:
        import os

        from gateway.transport_spike.speech import should_enable_partials

        env = {"QANTARA_STT_STREAMING": "auto", "QANTARA_WHISPER_DEVICE": "cuda"}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            self.assertTrue(should_enable_partials())

    async def test_compute_partial_returns_text_and_stable_prefix(self) -> None:
        from gateway.transport_spike.speech import compute_partial_transcript

        provider = _PartialCapableProvider()
        # First call — no prev text, stable prefix = 0
        result = await compute_partial_transcript(provider, [1, 2, 3], 16000, "")
        self.assertIsNotNone(result)
        text, stable = result
        self.assertEqual(text, "partial-3")
        self.assertEqual(stable, 0)

    async def test_compute_partial_returns_none_when_duplicate(self) -> None:
        from gateway.transport_spike.speech import compute_partial_transcript

        provider = _PartialCapableProvider()
        # Same 4 samples produce same text "partial-4" both times
        first = await compute_partial_transcript(provider, [1, 2, 3, 4], 16000, "")
        self.assertIsNotNone(first)
        prev_text = first[0]
        duplicate = await compute_partial_transcript(provider, [1, 2, 3, 4], 16000, prev_text)
        self.assertIsNone(duplicate)

    async def test_compute_partial_computes_stable_prefix_across_growth(self) -> None:
        from gateway.transport_spike.speech import compute_partial_transcript

        class _Grower(_PartialCapableProvider):
            async def transcribe_partial(self, samples, sample_rate):
                return "hello world"[: len(samples)]

        provider = _Grower()
        first = await compute_partial_transcript(provider, [0] * 5, 16000, "")
        self.assertEqual(first[0], "hello")
        second = await compute_partial_transcript(provider, [0] * 8, 16000, "hello")
        self.assertIsNotNone(second)
        self.assertEqual(second[0], "hello wo")
        self.assertEqual(second[1], 5)  # "hello" is stable

    async def test_compute_partial_returns_none_for_non_supporting_provider(self) -> None:
        from gateway.transport_spike.speech import compute_partial_transcript

        provider = _SilentProvider()
        result = await compute_partial_transcript(provider, [1, 2, 3], 16000, "")
        self.assertIsNone(result)

    async def test_compute_partial_returns_none_on_exception(self) -> None:
        from gateway.transport_spike.speech import compute_partial_transcript

        class _Failing(_PartialCapableProvider):
            async def transcribe_partial(self, samples, sample_rate):
                raise RuntimeError("transient")

        provider = _Failing()
        result = await compute_partial_transcript(provider, [1, 2, 3], 16000, "")
        self.assertIsNone(result)


class PartialLoopIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_loop_emits_partial_events_and_stops_cleanly(self) -> None:
        import asyncio
        import os

        from adapters.base import AdapterConfig
        from gateway.transport_spike.runtime import GatewayRuntime, Session
        from gateway.transport_spike.speech import start_partial_loop, stop_partial_loop
        from tests.test_transport_spike import DummyWebSocket, FakeTTS

        # Force partials on
        os.environ["QANTARA_STT_STREAMING"] = "on"
        try:
            stt = _PartialCapableProvider()
            runtime = GatewayRuntime(
                adapter_config=AdapterConfig(kind="mock", name="mock"),
                stt=stt,
                tts=FakeTTS(),
                event_sink=lambda record: None,
            )
            ws = DummyWebSocket()
            session = Session(ws, runtime)
            # Populate fake PCM so transcribe_partial has samples
            session.recent_pcm = [1, 2, 3, 4, 5]

            start_partial_loop(session, tick_interval_sec=0.01)
            # Give the loop a few ticks
            await asyncio.sleep(0.05)
            stop_partial_loop(session)
            # Wait briefly for cancellation
            await asyncio.sleep(0.01)

            # Partial events should have been pushed over the ws
            partial_msgs = [m for m in ws.strings if m.get("type") == "partial_transcript_ready"]
            self.assertGreaterEqual(len(partial_msgs), 1)
            self.assertEqual(partial_msgs[0]["text"], "partial-5")
            self.assertEqual(partial_msgs[0]["provider_kind"], "partial_capable")
            self.assertIn("ms_since_speech_start", partial_msgs[0])
            self.assertIn("stable_prefix_chars", partial_msgs[0])

            # stt.transcribe_partial should have been called at least once
            self.assertGreaterEqual(len(stt.partial_calls), 1)
            # Task cleaned up
            self.assertIsNone(session.partial_task)
        finally:
            os.environ.pop("QANTARA_STT_STREAMING", None)

    async def test_loop_noop_when_provider_does_not_support_partial(self) -> None:
        import os

        from adapters.base import AdapterConfig
        from gateway.transport_spike.runtime import GatewayRuntime, Session
        from gateway.transport_spike.speech import start_partial_loop
        from tests.test_transport_spike import DummyWebSocket, FakeTTS

        os.environ["QANTARA_STT_STREAMING"] = "on"
        try:
            stt = _SilentProvider()
            runtime = GatewayRuntime(
                adapter_config=AdapterConfig(kind="mock", name="mock"),
                stt=stt,
                tts=FakeTTS(),
                event_sink=lambda record: None,
            )
            ws = DummyWebSocket()
            session = Session(ws, runtime)
            session.recent_pcm = [1, 2, 3]

            start_partial_loop(session, tick_interval_sec=0.01)
            self.assertIsNone(session.partial_task)
        finally:
            os.environ.pop("QANTARA_STT_STREAMING", None)

    async def test_loop_noop_when_globally_disabled(self) -> None:
        import os

        from adapters.base import AdapterConfig
        from gateway.transport_spike.runtime import GatewayRuntime, Session
        from gateway.transport_spike.speech import start_partial_loop
        from tests.test_transport_spike import DummyWebSocket, FakeTTS

        os.environ["QANTARA_STT_STREAMING"] = "off"
        try:
            stt = _PartialCapableProvider()
            runtime = GatewayRuntime(
                adapter_config=AdapterConfig(kind="mock", name="mock"),
                stt=stt,
                tts=FakeTTS(),
                event_sink=lambda record: None,
            )
            ws = DummyWebSocket()
            session = Session(ws, runtime)
            session.recent_pcm = [1, 2, 3]

            start_partial_loop(session, tick_interval_sec=0.01)
            self.assertIsNone(session.partial_task)
        finally:
            os.environ.pop("QANTARA_STT_STREAMING", None)


class FasterWhisperPartialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from providers.stt.faster_whisper import FasterWhisperSTTProvider

        self.provider_cls = FasterWhisperSTTProvider

    def test_faster_whisper_provider_opts_into_partial_mode(self) -> None:
        provider = self.provider_cls()
        self.assertTrue(
            provider.supports_partial,
            "FasterWhisperSTTProvider must override transcribe_partial",
        )

    def test_partial_window_is_trailing_and_bounded(self) -> None:
        provider = self.provider_cls()
        long_samples = list(range(16000 * 10))  # 10 seconds at 16kHz
        window = provider._partial_window(long_samples, 16000)

        self.assertLessEqual(len(window), provider.partial_window_sec * 16000)
        self.assertGreater(len(window), 0)
        # Must be the trailing slice, not arbitrary
        self.assertEqual(window[-1], long_samples[-1])

    def test_partial_window_returns_full_buffer_when_short(self) -> None:
        provider = self.provider_cls()
        short_samples = list(range(1000))
        window = provider._partial_window(short_samples, 16000)
        self.assertEqual(window, short_samples)


if __name__ == "__main__":
    unittest.main()
