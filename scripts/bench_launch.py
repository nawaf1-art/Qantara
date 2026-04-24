"""Small launch benchmark snapshot for Qantara.

This is not a lab-grade benchmark harness. It captures the release-readiness
numbers we want in docs: gateway-side barge-in latency and local TTS synthesis
latency on the current machine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def make_barge_in_session() -> tuple[Any, list[dict], Any]:
    import json as _json

    from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter
    from gateway.transport_spike.runtime import GatewayRuntime, Session
    from providers.stt.base import STTProvider
    from providers.tts.base import TTSProvider, VoiceSpec

    class DummyWebSocket:
        closed = False

        async def send_str(self, data: str) -> None:
            _json.loads(data)

        async def send_bytes(self, data: bytes) -> None:
            _ = data

        def exception(self) -> None:
            return None

    class FakeSTT(STTProvider):
        kind = "fake_stt"

        @property
        def available(self) -> bool:
            return True

        async def transcribe(self, samples: list[int], sample_rate: int) -> str:
            return f"{len(samples)}@{sample_rate}"

    class FakeTTS(TTSProvider):
        kind = "fake_tts"

        @property
        def available(self) -> bool:
            return True

        @property
        def default_voice_id(self) -> str | None:
            return "fake_voice"

        def list_available_voices(self) -> list[dict]:
            return [
                {
                    "voice_id": "fake_voice",
                    "label": "Fake Voice",
                    "locale": "en-US",
                    "sample_rate": 16000,
                    "defaults": {"rate": 1.0, "pitch": 0, "tone": "neutral"},
                    "allowed_transforms": ["rate"],
                }
            ]

        def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
            return (
                VoiceSpec(
                    voice_id=voice_id or "fake_voice",
                    label="Fake Voice",
                    sample_rate=16000,
                    locale="en-US",
                    defaults={"rate": 1.0, "pitch": 0, "tone": "neutral"},
                    allowed_transforms=["rate"],
                ),
                None,
            )

        async def synthesize(
            self,
            text: str,
            voice_id: str | None = None,
            speech_rate: float | None = None,
            *,
            expressiveness: float | None = None,
        ) -> tuple[list[int], VoiceSpec, str | None]:
            _ = (text, speech_rate, expressiveness)
            voice, fallback = self.resolve_voice(voice_id)
            return [], voice, fallback

    class BlockingAdapter(RuntimeAdapter):
        def __init__(self) -> None:
            super().__init__(AdapterConfig(kind="mock", name="blocking"))
            self.first_delta_released = asyncio.Event()
            self.cancel_called = asyncio.Event()

        async def start_or_resume_session(self, client_context: dict | None = None) -> str:
            return "runtime-session"

        async def submit_user_turn(
            self,
            session_handle: str,
            transcript: str,
            turn_context: dict | None = None,
        ) -> str:
            return "turn-1"

        async def stream_assistant_output(self, session_handle: str, turn_handle: str):
            yield {"type": "assistant_text_delta", "text": "Hello there, I was about to say"}
            self.first_delta_released.set()
            await self.cancel_called.wait()
            yield {"type": "cancel_acknowledged"}

        async def cancel_turn(
            self,
            session_handle: str,
            turn_handle: str,
            cancel_context: dict | None = None,
        ) -> dict:
            self.cancel_called.set()
            return {"status": "acknowledged"}

        async def check_health(self) -> AdapterHealth:
            return AdapterHealth(status="ok")

    events: list[dict] = []
    runtime = GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=FakeSTT(),
        tts=FakeTTS(),
        event_sink=lambda record: events.append(record),
    )
    session = Session(DummyWebSocket(), runtime)
    runtime.register_session(session)
    adapter = BlockingAdapter()
    session.binding.adapter = adapter
    return session, events, adapter


@dataclass(frozen=True)
class Series:
    name: str
    unit: str
    samples: list[float]
    note: str = ""

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.samples)
        p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
        return {
            "name": self.name,
            "unit": self.unit,
            "samples": len(self.samples),
            "median": round(statistics.median(self.samples), 2),
            "mean": round(statistics.mean(self.samples), 2),
            "p95": round(ordered[p95_index], 2),
            "min": round(min(self.samples), 2),
            "max": round(max(self.samples), 2),
            "note": self.note,
        }


async def measure_barge_in(iterations: int) -> Series:
    from gateway.transport_spike.server import stream_assistant_turn
    from gateway.transport_spike.speech import cancel_active_turn
    samples: list[float] = []
    for _ in range(iterations):
        session, events, adapter = make_barge_in_session()
        turn_task = asyncio.create_task(stream_assistant_turn(session, "benchmark"))
        session.current_turn_task = turn_task
        await adapter.first_delta_released.wait()

        started = time.perf_counter()
        await cancel_active_turn(session, "benchmark")
        await turn_task
        samples.append((time.perf_counter() - started) * 1000)

        interrupted = [e for e in events if e["event_name"] == "turn_interrupted"]
        if len(interrupted) != 1:
            raise RuntimeError("barge-in benchmark did not emit exactly one turn_interrupted event")

    return Series(
        name="Gateway barge-in cancel path",
        unit="ms",
        samples=samples,
        note="cancel_active_turn to turn completion on loopback test adapter",
    )


async def measure_tts(provider_kind: str, voice_id: str | None, iterations: int, text: str) -> Series | None:
    from providers.factory import create_tts_provider

    provider = create_tts_provider(provider_kind)
    if not provider.available:
        return None

    samples: list[float] = []
    resolved_voice_id = voice_id
    for _ in range(iterations):
        started = time.perf_counter()
        _samples, voice, _fallback = await provider.synthesize(text, voice_id=voice_id)
        samples.append((time.perf_counter() - started) * 1000)
        resolved_voice_id = voice.voice_id

    return Series(
        name=f"{provider.kind} TTS synthesis ({resolved_voice_id or 'default'})",
        unit="ms",
        samples=samples,
        note="short launch phrase, full synthesis latency",
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    series: list[Series] = [await measure_barge_in(args.barge_in_iterations)]
    tts = await measure_tts(args.tts_provider, args.voice_id, args.tts_iterations, args.text)
    if tts is not None:
        series.append(tts)
    if args.arabic:
        arabic = await measure_tts(
            args.tts_provider,
            "ar_JO-kareem-medium",
            args.tts_iterations,
            "مرحبا، قنطرة جاهزة للمحادثة الصوتية المحلية.",
        )
        if arabic is not None:
            series.append(arabic)

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "metrics": [item.summary() for item in series],
    }


def print_markdown(payload: dict[str, Any]) -> None:
    print("# Qantara Launch Benchmark Snapshot")
    print()
    print(f"Generated: `{payload['generated_at']}`")
    print(f"Host: `{payload['platform']}`, Python `{payload['python']}`")
    print()
    print("| Metric | Samples | Median | p95 | Note |")
    print("|---|---:|---:|---:|---|")
    for metric in payload["metrics"]:
        unit = metric["unit"]
        print(
            f"| {metric['name']} | {metric['samples']} | "
            f"{metric['median']} {unit} | {metric['p95']} {unit} | {metric['note']} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--arabic", action="store_true", help="Also measure the Arabic Piper voice when present")
    parser.add_argument("--barge-in-iterations", type=int, default=20)
    parser.add_argument("--tts-iterations", type=int, default=3)
    parser.add_argument("--tts-provider", default="piper")
    parser.add_argument("--voice-id", default=None)
    parser.add_argument("--text", default="Qantara is ready for a local voice conversation.")
    args = parser.parse_args()

    payload = asyncio.run(run(args))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_markdown(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
