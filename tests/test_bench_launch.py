from __future__ import annotations

import argparse
import unittest

from scripts.bench_launch import run


class LaunchBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_tts_iterations_runs_barge_in_only(self) -> None:
        args = argparse.Namespace(
            arabic=False,
            barge_in_iterations=2,
            text="test",
            tts_iterations=0,
            tts_provider="piper",
            voice_id=None,
        )

        payload = await run(args)

        self.assertEqual(len(payload["metrics"]), 1)
        self.assertEqual(payload["metrics"][0]["name"], "Gateway barge-in cancel path")
        self.assertEqual(payload["metrics"][0]["samples"], 2)
