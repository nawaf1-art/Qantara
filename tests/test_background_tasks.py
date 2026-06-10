from __future__ import annotations

import asyncio
import unittest

from adapters.base import AdapterConfig
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS


class RuntimeRetainTaskTests(unittest.IsolatedAsyncioTestCase):
    def _make_runtime(self) -> GatewayRuntime:
        return GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=FakeSTT(),
            tts=FakeTTS(),
            event_sink=lambda record: None,
        )

    async def test_retained_task_is_referenced_until_done(self) -> None:
        runtime = self._make_runtime()
        release = asyncio.Event()

        async def waits() -> None:
            await release.wait()

        task = runtime.retain_task(asyncio.create_task(waits()))
        self.assertIn(task, runtime._background_tasks)
        release.set()
        await task
        self.assertNotIn(task, runtime._background_tasks)

    async def test_retained_task_exception_is_logged_not_swallowed(self) -> None:
        runtime = self._make_runtime()

        async def boom() -> None:
            raise RuntimeError("background boom")

        with self.assertLogs("gateway.transport_spike.runtime", level="ERROR") as captured:
            task = runtime.retain_task(asyncio.create_task(boom()))
            with self.assertRaises(RuntimeError):
                await task
            # done-callback runs after the await; yield once so it fires.
            await asyncio.sleep(0)
        self.assertTrue(any("background boom" in line for line in captured.output))
        self.assertNotIn(task, runtime._background_tasks)


class OpenClawRetainTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_retained_task_is_referenced_and_exception_logged(self) -> None:
        from gateway.openclaw_session_backend import server as openclaw_server

        async def boom() -> None:
            raise RuntimeError("escalate boom")

        with self.assertLogs("qantara.openclaw", level="ERROR") as captured:
            task = openclaw_server._retain_task(asyncio.create_task(boom()))
            self.assertIn(task, openclaw_server._BACKGROUND_TASKS)
            with self.assertRaises(RuntimeError):
                await task
            await asyncio.sleep(0)
        self.assertTrue(any("escalate boom" in line for line in captured.output))
        self.assertNotIn(task, openclaw_server._BACKGROUND_TASKS)


if __name__ == "__main__":
    unittest.main()
