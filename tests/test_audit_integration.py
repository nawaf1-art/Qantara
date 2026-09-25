"""Cross-area wiring added while integrating the 2026-09-24 audit fixes."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from gateway.transport_spike import runtime as runtime_module
from gateway.transport_spike.websocket_api import declared_source_language


class _ClosableAdapter:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


class _FailingCloseAdapter:
    async def aclose(self) -> None:
        raise RuntimeError("boom")


class CloseAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_adapter_calls_aclose(self) -> None:
        adapter = _ClosableAdapter()
        await runtime_module._close_adapter(adapter)
        self.assertEqual(adapter.closed, 1)

    async def test_close_adapter_tolerates_missing_or_failing_aclose(self) -> None:
        await runtime_module._close_adapter(object())
        await runtime_module._close_adapter(_FailingCloseAdapter())


class ProviderWarmupTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self, tts: object) -> SimpleNamespace:
        retained: list = []
        fake = SimpleNamespace(tts=tts, retain_task=retained.append, retained=retained)
        return fake

    async def test_warmup_is_opt_in(self) -> None:
        calls: list[str] = []

        async def warmup() -> None:
            calls.append("warm")

        fake = self._runtime(SimpleNamespace(available=True, warmup=warmup))
        with mock.patch.dict(os.environ, {}, clear=True):
            runtime_module.GatewayRuntime.start_provider_warmup(fake)
        self.assertEqual(fake.retained, [])

        with mock.patch.dict(os.environ, {"QANTARA_TTS_WARMUP": "1"}, clear=True):
            runtime_module.GatewayRuntime.start_provider_warmup(fake)
        self.assertEqual(len(fake.retained), 1)
        await fake.retained[0]
        self.assertEqual(calls, ["warm"])

    async def test_warmup_failure_is_logged_not_raised(self) -> None:
        async def warmup() -> None:
            raise RuntimeError("no weights")

        fake = self._runtime(SimpleNamespace(available=True, warmup=warmup))
        with mock.patch.dict(os.environ, {"QANTARA_TTS_WARMUP": "1"}, clear=True):
            runtime_module.GatewayRuntime.start_provider_warmup(fake)
            with self.assertLogs("gateway.transport_spike.runtime", level="WARNING"):
                await fake.retained[0]

    def test_warmup_skips_unavailable_provider(self) -> None:
        fake = self._runtime(SimpleNamespace(available=False, warmup=None))
        with mock.patch.dict(os.environ, {"QANTARA_TTS_WARMUP": "1"}, clear=True):
            runtime_module.GatewayRuntime.start_provider_warmup(fake)
        self.assertEqual(fake.retained, [])


class DeclaredSourceLanguageTests(unittest.TestCase):
    def test_translation_modes_force_the_declared_source(self) -> None:
        for mode in ("directional", "live"):
            session = SimpleNamespace(translation_mode=mode, translation_source="ar")
            self.assertEqual(declared_source_language(session), "ar")

    def test_assistant_mode_keeps_auto_detection(self) -> None:
        self.assertIsNone(declared_source_language(SimpleNamespace(translation_mode="assistant", translation_source="ar")))
        self.assertIsNone(declared_source_language(SimpleNamespace(translation_mode=None, translation_source=None)))
        self.assertIsNone(declared_source_language(SimpleNamespace(translation_mode="live", translation_source=None)))


class RemovedSettingsTests(unittest.TestCase):
    def test_wyoming_constants_are_gone(self) -> None:
        from gateway.transport_spike import common

        self.assertFalse(hasattr(common, "WYOMING_ENABLED"))


if __name__ == "__main__":
    unittest.main()
