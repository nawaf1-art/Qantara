"""Measure Piper TTS first-chunk latency: persistent subprocess vs per-call subprocess."""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from gateway.transport_spike.tts_piper import PiperTTS

TEST_TEXTS = [
    "Hello, how can I help you today?",
    "I received your turn. This response is coming from the fake session backend.",
    "The weather in Kuwait City is warm and sunny with temperatures around thirty five degrees.",
]

RUNS_PER_TEXT = 3


async def measure_persistent_stream(tts: PiperTTS, text: str) -> dict:
    """Measure the persistent subprocess streaming path."""
    start = time.monotonic()
    first_chunk_ms = None
    total_samples = 0
    chunk_count = 0

    async for samples in tts.synthesize_stream(text):
        if first_chunk_ms is None:
            first_chunk_ms = round((time.monotonic() - start) * 1000, 1)
        total_samples += len(samples)
        chunk_count += 1

    total_ms = round((time.monotonic() - start) * 1000, 1)
    return {
        "method": "persistent_stream",
        "first_chunk_ms": first_chunk_ms or total_ms,
        "total_ms": total_ms,
        "total_samples": total_samples,
        "chunk_count": chunk_count,
    }


async def measure_one_shot(tts: PiperTTS, text: str) -> dict:
    """Measure the old per-call subprocess path (spawns new process each time)."""
    cmd = tts._build_cmd()
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate(text.encode("utf-8"))
    total_ms = round((time.monotonic() - start) * 1000, 1)
    total_samples = len(stdout) // 2
    return {
        "method": "one_shot",
        "first_chunk_ms": total_ms,
        "total_ms": total_ms,
        "total_samples": total_samples,
        "chunk_count": 1,
    }


async def main():
    tts = PiperTTS()
    if not tts.available:
        print("ERROR: Piper model not found")
        sys.exit(1)

    print(f"Piper model: {tts.voice_path}")
    print(f"Sample rate: {tts.sample_rate}")
    print(f"Runs per text: {RUNS_PER_TEXT}")
    print()

    # Warm up the persistent process (model loading)
    print("Warming up persistent subprocess (model loading)...")
    warm_start = time.monotonic()
    await tts.warm_up()
    warm_ms = round((time.monotonic() - warm_start) * 1000, 0)
    print(f"Warm-up complete in {warm_ms}ms")
    print()

    for text in TEST_TEXTS:
        print(f'Text: "{text[:60]}{"..." if len(text) > 60 else ""}" ({len(text)} chars)')
        print("-" * 80)

        persistent_results = []
        one_shot_results = []

        for run in range(RUNS_PER_TEXT):
            p = await measure_persistent_stream(tts, text)
            o = await measure_one_shot(tts, text)
            persistent_results.append(p)
            one_shot_results.append(o)
            print(
                f"  Run {run+1}: "
                f"persistent first={p['first_chunk_ms']}ms total={p['total_ms']}ms | "
                f"one_shot first={o['first_chunk_ms']}ms total={o['total_ms']}ms"
            )

        avg_p_first = round(sum(r["first_chunk_ms"] for r in persistent_results) / len(persistent_results), 1)
        avg_p_total = round(sum(r["total_ms"] for r in persistent_results) / len(persistent_results), 1)
        avg_o_first = round(sum(r["first_chunk_ms"] for r in one_shot_results) / len(one_shot_results), 1)
        avg_o_total = round(sum(r["total_ms"] for r in one_shot_results) / len(one_shot_results), 1)

        improvement = round(avg_o_first - avg_p_first, 1)
        pct = round((improvement / avg_o_first) * 100, 1) if avg_o_first > 0 else 0

        print(f"  AVG persistent: first_chunk={avg_p_first}ms total={avg_p_total}ms")
        print(f"  AVG one_shot:   first_chunk={avg_o_first}ms total={avg_o_total}ms")
        print(f"  IMPROVEMENT:    {improvement}ms faster ({pct}%)")
        print()

    await tts.shutdown()
    print("=" * 80)
    print("BASELINE COMPARISON:")
    print(f"  Mainline first-chunk: ~1500ms (documented)")
    print(f"  This branch (persistent subprocess): see AVG persistent numbers above")


if __name__ == "__main__":
    asyncio.run(main())
