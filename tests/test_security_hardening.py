from __future__ import annotations

import asyncio
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from gateway.openclaw_session_backend.server import (
    OpenClawOutputLimitError,
)
from gateway.openclaw_session_backend.server import (
    _read_bounded_stream as _read_openclaw_stream,
)
from gateway.transport_spike.http_api import _communicate_with_timeout
from gateway.transport_spike.runtime import GatewayRuntime, _bridge_environment
from providers.tts.piper import (
    PiperOutputLimitError,
    PiperTTSProvider,
    PiperVoiceSpec,
)
from providers.tts.piper import (
    _read_bounded_stream as _read_piper_stream,
)
from qantara.security import sanitize_public_url


class _HangingProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False
        self.communicate_calls = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            await asyncio.Future()
        self.returncode = -9
        return b"", b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _HangingPiperProcess(_HangingProcess):
    async def communicate(self, _input: bytes | None = None) -> tuple[bytes, bytes]:
        return await super().communicate()


class _StreamProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"") -> None:
        self.returncode: int | None = None
        self.killed = False
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class SecurityHardeningTests(unittest.IsolatedAsyncioTestCase):
    def test_default_event_output_redacts_content_and_credentials(self) -> None:
        record = {
            "event_name": "final_transcript_ready",
            "session_id": "session-1",
            "payload": {
                "transcript": "private spoken words",
                "text": "private model answer",
                "authorization": "Bearer secret-token-value",
                "api_key": "sk-secret-value",
                "backend_url": "http://user:pass@127.0.0.1:11434/v1?token=hidden",
                "error": "provider echoed another-secret-value",
                "char_count": 20,
                "engine": "fake",
            },
        }
        output = io.StringIO()
        with redirect_stdout(output):
            GatewayRuntime._print_event(record)
        serialized = output.getvalue()
        parsed = json.loads(serialized)

        self.assertNotIn("private spoken words", serialized)
        self.assertNotIn("private model answer", serialized)
        self.assertNotIn("secret-token-value", serialized)
        self.assertNotIn("sk-secret-value", serialized)
        self.assertNotIn("hidden", serialized)
        self.assertNotIn("another-secret-value", serialized)
        self.assertIn("http://127.0.0.1:11434/v1", serialized)
        self.assertEqual(parsed["payload"]["char_count"], 20)
        self.assertEqual(parsed["payload"]["engine"], "fake")

    def test_managed_bridge_environment_excludes_gateway_secrets(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QANTARA_AUTH_TOKEN": "voice-secret",
                "QANTARA_ADMIN_TOKEN": "admin-secret",
                "QANTARA_MESH_TOKEN": "mesh-secret",
                "QANTARA_OPENAI_API_KEY": "provider-key",
            },
            clear=True,
        ):
            env = _bridge_environment({"QANTARA_AUTH_TOKEN": "override-secret"})

        self.assertNotIn("QANTARA_AUTH_TOKEN", env)
        self.assertNotIn("QANTARA_ADMIN_TOKEN", env)
        self.assertNotIn("QANTARA_MESH_TOKEN", env)
        self.assertEqual(env["QANTARA_OPENAI_API_KEY"], "provider-key")

    def test_public_url_removes_userinfo_query_and_fragment(self) -> None:
        self.assertEqual(
            sanitize_public_url("http://user:pass@127.0.0.1:11434/v1?token=secret#part"),
            "http://127.0.0.1:11434/v1",
        )

    async def test_subprocess_timeout_kills_and_reaps_child(self) -> None:
        proc = _HangingProcess()
        with self.assertRaises(TimeoutError):
            await _communicate_with_timeout(proc, 0.001)  # type: ignore[arg-type]
        self.assertTrue(proc.killed)
        self.assertEqual(proc.communicate_calls, 2)

    async def test_setup_probe_capture_stops_at_configured_limit(self) -> None:
        proc = _StreamProcess(b"12345")
        with patch(
            "gateway.transport_spike.http_api.MAX_SETUP_PROBE_STDOUT_BYTES",
            4,
        ):
            with self.assertRaisesRegex(RuntimeError, "stdout exceeded"):
                await _communicate_with_timeout(proc, 1)  # type: ignore[arg-type]

    async def test_openclaw_stream_capture_stops_at_configured_limit(self) -> None:
        stream = asyncio.StreamReader()
        stream.feed_data(b"12345")
        stream.feed_eof()
        with self.assertRaises(OpenClawOutputLimitError):
            await _read_openclaw_stream(stream, limit=4, label="stdout")

    async def test_piper_stream_capture_stops_at_configured_limit(self) -> None:
        stream = asyncio.StreamReader()
        stream.feed_data(b"12345")
        stream.feed_eof()
        with self.assertRaises(PiperOutputLimitError):
            await _read_piper_stream(stream, limit=4, label="audio")

    async def test_piper_timeout_kills_and_reaps_child(self) -> None:
        provider = object.__new__(PiperTTSProvider)
        provider.command = ["piper"]
        provider.timeout_seconds = 0.001
        voice = PiperVoiceSpec(
            voice_id="test",
            label="Test",
            sample_rate=16000,
            locale="en-US",
            model_path="synthetic.onnx",
        )
        provider.resolve_voice = lambda _voice_id: (voice, None)  # type: ignore[method-assign]
        proc = _HangingPiperProcess()
        with (
            patch.dict(
                os.environ,
                {
                    "QANTARA_AUTH_TOKEN": "gateway-secret",
                    "PATH": os.environ.get("PATH", ""),
                },
                clear=True,
            ),
            patch(
                "providers.tts.piper.asyncio.create_subprocess_exec",
                return_value=proc,
            ) as create_process,
        ):
            with self.assertRaisesRegex(RuntimeError, "piper timed out"):
                await provider.synthesize("synthetic input")
        self.assertTrue(proc.killed)
        self.assertEqual(proc.communicate_calls, 2)
        child_env = create_process.call_args.kwargs["env"]
        self.assertNotIn("QANTARA_AUTH_TOKEN", child_env)


if __name__ == "__main__":
    unittest.main()
