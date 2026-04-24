"""Smoke test for Qantara.

Run: python3 scripts/smoke_test.py (or `make smoke-test`)

Starts the gateway in-process against a mock adapter, opens a WebSocket
client, runs one full turn (session_init → submit_turn → assistant_text_final
→ turn_state idle), and exits 0 on success. No real model or mic required.

This is the "did I break the plumbing" check — it does not validate STT,
TTS, or a real backend.
"""

from __future__ import annotations

import asyncio
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter  # noqa: E402
from gateway.transport_spike.runtime import GatewayRuntime  # noqa: E402
from gateway.transport_spike.server import create_app  # noqa: E402
from providers.stt.base import STTProvider  # noqa: E402
from providers.tts.base import TTSProvider, VoiceSpec  # noqa: E402


class _SmokeSTT(STTProvider):
    kind = "smoke_stt"

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, samples: list[int], sample_rate: int) -> str:
        return "hi"


class _SmokeTTS(TTSProvider):
    kind = "smoke_tts"

    @property
    def available(self) -> bool:
        return True

    @property
    def default_voice_id(self) -> str | None:
        return "smoke_voice"

    def list_available_voices(self) -> list[dict]:
        return [{"voice_id": "smoke_voice", "label": "Smoke", "locale": "en-US", "sample_rate": 16000, "defaults": {}, "allowed_transforms": []}]

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        return VoiceSpec(voice_id="smoke_voice", label="Smoke", sample_rate=16000, locale="en-US"), None

    async def synthesize(self, text, voice_id=None, speech_rate=None):
        return [], VoiceSpec(voice_id="smoke_voice", label="Smoke", sample_rate=16000, locale="en-US"), None


class _SmokeAdapter(RuntimeAdapter):
    async def start_or_resume_session(self, client_context=None):
        return "smoke-runtime"

    async def submit_user_turn(self, session_handle, transcript, turn_context=None):
        return "smoke-turn"

    async def stream_assistant_output(self, session_handle, turn_handle):
        yield {"type": "assistant_text_delta", "text": "smoke reply"}
        yield {"type": "turn_completed"}

    async def cancel_turn(self, session_handle, turn_handle, cancel_context=None):
        return {"status": "acknowledged"}

    async def check_health(self):
        return AdapterHealth(status="ok")


async def run_smoke() -> int:
    runtime = GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=_SmokeSTT(),
        tts=_SmokeTTS(),
        event_sink=lambda record: None,
    )
    runtime.default_binding().adapter = _SmokeAdapter(AdapterConfig(kind="mock", name="mock"))
    server = TestServer(create_app(runtime))
    client = TestClient(server)
    await client.start_server()
    try:
        ws = await client.ws_connect("/ws")
        await ws.send_json(
            {
                "type": "session_init",
                "client_name": "smoke",
                "client_session_id": "smoke-client",
                "voice_id": "smoke_voice",
            }
        )
        await ws.receive_json()
        await ws.receive_json()
        await ws.send_json({"type": "submit_turn", "text": "hi"})
        saw_final = False
        saw_idle = False
        for _ in range(30):
            msg = await ws.receive_json()
            if msg.get("type") == "assistant_text_final":
                saw_final = True
            if msg.get("type") == "turn_state" and msg.get("state") == "idle":
                saw_idle = True
            if saw_final and saw_idle:
                break
        await ws.close()
        if saw_final and saw_idle:
            print("smoke test: ok (session_init → submit_turn → assistant_text_final → turn_state idle)")
            return 0
        print("smoke test: fail — missing final or idle state")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run_smoke()))
