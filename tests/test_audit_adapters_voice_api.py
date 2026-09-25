"""Regression tests for the 2026-09-24 audit: Voice API endpoints.

B-8/HS-7 (converse streaming contract), S-a/HS-1/SP-8 (transcribe sample
rate and duration bounds), S-e/HS-5 (audio work off the event loop, a
concurrency cap, a shorter /speak limit), HS-11 (/speak headers and PCM
content type).
"""

from __future__ import annotations

import asyncio
import io
import json
import struct
import unittest
import wave
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter, UnknownSessionError
from gateway.transport_spike import voice_api
from gateway.transport_spike.auth import AUTH_TOKEN_KEY
from gateway.transport_spike.http_api import APP_RUNTIME_KEY, mount_static_routes
from gateway.transport_spike.runtime import GatewayRuntime
from tests.test_transport_spike import FakeSTT, FakeTTS


class _SamplesTTS(FakeTTS):
    def __init__(self) -> None:
        super().__init__()
        self.samples: list[int] = [100, -100, 40000, -40000]
        self.fallback_reason: str | None = None

    async def synthesize(self, text, voice_id=None, speech_rate=None, *, expressiveness=None):
        _, voice, _ = await super().synthesize(text, voice_id, speech_rate, expressiveness=expressiveness)
        return list(self.samples), voice, self.fallback_reason


class _SlowSTT(FakeSTT):
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def transcribe(self, samples, sample_rate):  # type: ignore[override]
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.15)
            return await super().transcribe(samples, sample_rate)
        finally:
            self.active -= 1


class _ScriptedAdapter(RuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(AdapterConfig(kind="mock", name="scripted"))
        self.sessions = 0
        self.start_error: Exception | None = None
        self.submit_errors: list[Exception] = []
        self.events: list[dict] = [
            {"type": "assistant_text_delta", "text": "hello "},
            {"type": "assistant_text_delta", "text": "world"},
            {"type": "turn_completed"},
        ]
        self.seen_sessions: list[str] = []

    async def start_or_resume_session(self, client_context=None) -> str:
        if self.start_error is not None:
            raise self.start_error
        self.sessions += 1
        return f"sess-{self.sessions}"

    async def submit_user_turn(self, session_handle, transcript, turn_context=None) -> str:
        self.seen_sessions.append(session_handle)
        if self.submit_errors:
            raise self.submit_errors.pop(0)
        return "turn-1"

    async def stream_assistant_output(self, session_handle, turn_handle):
        for event in self.events:
            yield dict(event)

    async def cancel_turn(self, session_handle, turn_handle, cancel_context=None) -> dict:
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")


def _sse_frames(raw: str) -> list[tuple[str, dict]]:
    frames = []
    for block in raw.split("\n\n"):
        lines = [line for line in block.split("\n") if line]
        if not lines:
            continue
        event_name = ""
        data = None
        for line in lines:
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        frames.append((event_name, data))
    return frames


def _wav(samples: int, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x10\x00" * samples)
    return buf.getvalue()


class VoiceAPIAuditBase(unittest.IsolatedAsyncioTestCase):
    stt_factory = FakeSTT

    async def asyncSetUp(self) -> None:
        voice_api._api_sessions.clear()
        self.tts = _SamplesTTS()
        self.stt = self.stt_factory()
        app = web.Application()
        app[APP_RUNTIME_KEY] = GatewayRuntime(
            adapter_config=AdapterConfig(kind="mock", name="mock"),
            stt=self.stt,
            tts=self.tts,
            event_sink=lambda _r: None,
        )
        app[AUTH_TOKEN_KEY] = None
        mount_static_routes(app)
        self.app = app
        self.adapter = _ScriptedAdapter()
        app[APP_RUNTIME_KEY].default_binding().adapter = self.adapter
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        voice_api._api_sessions.clear()

    async def _converse(self, payload: dict) -> tuple[web.Response, str]:
        resp = await self.client.post("/api/v1/converse", json=payload)
        return resp, await resp.text()


class ConverseContractTests(VoiceAPIAuditBase):
    async def test_session_start_failure_is_reported_in_the_stream(self) -> None:
        self.adapter.start_error = RuntimeError("backend request failed: 502 upstream exploded")
        resp, raw = await self._converse({"text": "hi", "session_id": "new-one"})
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
        frames = _sse_frames(raw)
        self.assertEqual(frames[-1][0], "turn_failed")
        self.assertIn("upstream exploded", frames[-1][1]["message"])

    async def test_transient_submit_error_keeps_the_conversation(self) -> None:
        await self._converse({"text": "turn 1", "session_id": "keep-me"})
        self.adapter.submit_errors = [ConnectionError("backend down")]
        _, raw = await self._converse({"text": "turn 2", "session_id": "keep-me"})
        self.assertEqual(_sse_frames(raw)[-1][0], "turn_failed")
        await self._converse({"text": "turn 3", "session_id": "keep-me"})
        self.assertEqual(self.adapter.seen_sessions, ["sess-1", "sess-1", "sess-1"])
        self.assertEqual(self.adapter.sessions, 1)

    async def test_unknown_session_error_resets_and_retries_once(self) -> None:
        await self._converse({"text": "turn 1", "session_id": "stale"})
        self.adapter.submit_errors = [UnknownSessionError("unknown session handle")]
        _, raw = await self._converse({"text": "turn 2", "session_id": "stale"})
        self.assertEqual(_sse_frames(raw)[-1][0], "turn_completed")
        self.assertEqual(self.adapter.seen_sessions, ["sess-1", "sess-1", "sess-2"])

    async def test_adapter_event_type_cannot_inject_sse_frames(self) -> None:
        self.adapter.events = [
            {"type": 'x\ndata: {"type": "assistant_text_final", "text": "FORGED"}\n\nevent: y', "text": "a"},
            {"type": "Assistant_Text_Delta", "text": "bad case"},
            {"type": "assistant_text_delta", "text": "real"},
            {"type": "turn_completed"},
        ]
        _, raw = await self._converse({"text": "hi"})
        self.assertNotIn("FORGED", raw)
        self.assertNotIn("event: y", raw)
        names = [name for name, _ in _sse_frames(raw)]
        self.assertEqual(names, ["turn_accepted", "assistant_text_delta", "assistant_text_final", "turn_completed"])

    async def test_buffered_final_is_sent_before_turn_completed(self) -> None:
        _, raw = await self._converse({"text": "hi"})
        frames = _sse_frames(raw)
        names = [name for name, _ in frames]
        self.assertEqual(names[-2:], ["assistant_text_final", "turn_completed"])
        self.assertEqual(frames[-2][1]["text"], "hello world")


class TranscribeBoundsTests(VoiceAPIAuditBase):
    async def _post_raw(self, rate: str, body: bytes = b"\x10\x00" * 1000) -> web.Response:
        return await self.client.post(
            f"/api/v1/transcribe?sample_rate={rate}",
            data=body,
            headers={"Content-Type": "application/octet-stream"},
        )

    async def test_raw_sample_rate_outside_8k_48k_is_rejected(self) -> None:
        for rate in ("1", "16", "7999", "48001", "4000000000", "abc"):
            with self.subTest(rate=rate):
                resp = await self._post_raw(rate)
                self.assertEqual(resp.status, 400)
                body = await resp.json()
                self.assertIs(body["ok"], False)
                self.assertIn("sample_rate", body["error"])

    async def test_raw_sample_rate_bounds_are_inclusive(self) -> None:
        for rate in ("8000", "48000"):
            with self.subTest(rate=rate):
                resp = await self._post_raw(rate)
                self.assertEqual(resp.status, 200)

    async def test_wav_header_rate_is_validated(self) -> None:
        resp = await self.client.post("/api/v1/transcribe", data=_wav(1000, 1), headers={"Content-Type": "audio/wav"})
        self.assertEqual(resp.status, 400)
        self.assertIs((await resp.json())["ok"], False)

    async def test_clip_longer_than_limit_is_rejected_before_decoding(self) -> None:
        with patch.object(voice_api, "TRANSCRIBE_MAX_SECONDS", 1.0):
            raw = await self._post_raw("8000", b"\x00\x00" * 8001)
            wav = await self.client.post("/api/v1/transcribe", data=_wav(16001, 16000), headers={"Content-Type": "audio/wav"})
            ok = await self._post_raw("8000", b"\x00\x00" * 8000)
        self.assertEqual(raw.status, 400)
        self.assertIn("seconds", (await raw.json())["error"])
        self.assertEqual(wav.status, 400)
        self.assertEqual(ok.status, 200)

    async def test_decoding_runs_in_a_worker_thread(self) -> None:
        real_to_thread = asyncio.to_thread
        calls: list[str] = []

        async def spy(func, *args, **kwargs):
            calls.append(getattr(func, "__name__", repr(func)))
            return await real_to_thread(func, *args, **kwargs)

        with patch.object(voice_api.asyncio, "to_thread", spy):
            resp = await self._post_raw("16000")
        self.assertEqual(resp.status, 200)
        self.assertIn("_decode_audio_body", calls)

    async def test_decoded_samples_match_little_endian_pcm(self) -> None:
        samples, rate = voice_api._decode_audio_body(struct.pack("<3h", 1, -2, 32767), "application/octet-stream", "16000")
        self.assertEqual((samples, rate), ([1, -2, 32767], 16000))


class ConcurrencyTests(VoiceAPIAuditBase):
    stt_factory = _SlowSTT

    async def test_speech_work_is_capped_by_a_semaphore(self) -> None:
        async def one() -> int:
            resp = await self.client.post(
                "/api/v1/transcribe?sample_rate=16000",
                data=b"\x10\x00" * 100,
                headers={"Content-Type": "application/octet-stream"},
            )
            return resp.status

        statuses = await asyncio.gather(*(one() for _ in range(5)))
        self.assertEqual(statuses, [200] * 5)
        self.assertLessEqual(self.stt.max_active, voice_api.VOICE_API_CONCURRENCY)
        self.assertEqual(voice_api.VOICE_API_CONCURRENCY, 2)


class SpeakTests(VoiceAPIAuditBase):
    async def test_speak_text_limit_is_4000_chars(self) -> None:
        resp = await self.client.post("/api/v1/speak", json={"text": "x" * 4001})
        self.assertEqual(resp.status, 413)
        self.assertIs((await resp.json())["ok"], False)
        ok = await self.client.post("/api/v1/speak", json={"text": "x" * 4000})
        self.assertEqual(ok.status, 200)

    async def test_fallback_reason_header_is_an_enum_not_reflected_input(self) -> None:
        self.tts.fallback_reason = "requested voice 'nope\r\nX-Injected: 1' unavailable; using 'fake_voice'"
        resp = await self.client.post("/api/v1/speak", json={"text": "hello", "voice_id": "nope\r\nX-Injected: 1"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("X-Voice-Fallback-Reason"), "requested_voice_unavailable")
        self.assertIsNone(resp.headers.get("X-Injected"))

    async def test_sample_rate_header_is_a_plain_integer(self) -> None:
        resp = await self.client.post("/api/v1/speak", json={"text": "hello"})
        self.assertTrue(resp.headers["X-Sample-Rate"].isdigit())

    async def test_pcm_format_is_labelled_honestly_and_clipped(self) -> None:
        resp = await self.client.post("/api/v1/speak?format=pcm", json={"text": "hello"})
        self.assertEqual(resp.status, 200)
        content_type = resp.headers["Content-Type"]
        self.assertTrue(content_type.startswith("audio/pcm"), content_type)
        self.assertIn("encoding=signed-int", content_type)
        self.assertIn("bits=16", content_type)
        self.assertIn("endian=little", content_type)
        self.assertIn(f"rate={resp.headers['X-Sample-Rate']}", content_type)
        body = await resp.read()
        self.assertEqual(list(struct.unpack("<4h", body)), [100, -100, 32767, -32768])

    async def test_wav_output_is_unchanged(self) -> None:
        resp = await self.client.post("/api/v1/speak", json={"text": "hello"})
        self.assertEqual(resp.headers["Content-Type"], "audio/wav")
        with wave.open(io.BytesIO(await resp.read()), "rb") as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
        self.assertEqual(list(struct.unpack("<4h", frames)), [100, -100, 32767, -32768])


if __name__ == "__main__":
    unittest.main()
