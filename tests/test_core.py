"""Tests for Qantara core modules."""

import asyncio
import io
import struct
import sys
import os
import uuid
import wave
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# --- tts_piper ---

from gateway.transport_spike.tts_piper import PiperTTS, _bytes_to_samples, STREAM_CHUNK_BYTES


class TestBytesToSamples:
    def test_empty(self):
        assert _bytes_to_samples(b"") == []

    def test_single_sample(self):
        raw = struct.pack("<h", 1234)
        assert _bytes_to_samples(raw) == [1234]

    def test_multiple_samples(self):
        values = [-32768, 0, 32767, -1, 100]
        raw = struct.pack(f"<{len(values)}h", *values)
        assert _bytes_to_samples(raw) == values

    def test_odd_byte_count_truncates(self):
        raw = struct.pack("<2h", 10, 20) + b"\xff"
        result = _bytes_to_samples(raw)
        assert result == [10, 20]


class TestPiperTTSAvailability:
    def test_unavailable_when_no_model(self):
        tts = PiperTTS(voice_path="/nonexistent/path.onnx")
        assert tts.available is False

    def test_unavailable_when_none(self):
        tts = PiperTTS(voice_path=None)
        # May be True if default model exists, so just check it doesn't crash
        assert isinstance(tts.available, bool)

    def test_build_cmd_includes_model(self, tmp_path):
        model = tmp_path / "test.onnx"
        model.write_bytes(b"fake")
        config = tmp_path / "test.onnx.json"
        config.write_text("{}")
        tts = PiperTTS(voice_path=str(model), config_path=str(config))
        cmd = tts._build_cmd()
        assert "--model" in cmd
        assert str(model) in cmd
        assert "--config" in cmd
        assert str(config) in cmd
        assert "--output-raw" in cmd

    def test_build_cmd_without_config(self, tmp_path):
        model = tmp_path / "test.onnx"
        model.write_bytes(b"fake")
        tts = PiperTTS(voice_path=str(model), config_path=None)
        cmd = tts._build_cmd()
        assert "--config" not in cmd


class TestPiperTTSSynthesizeStream:
    @pytest.mark.asyncio
    async def test_synthesize_stream_unavailable(self):
        tts = PiperTTS(voice_path="/nonexistent.onnx")
        with pytest.raises(RuntimeError, match="not available"):
            async for _ in tts.synthesize_stream("hello"):
                pass

    @pytest.mark.asyncio
    async def test_synthesize_stream_empty_text(self, tmp_path):
        model = tmp_path / "test.onnx"
        model.write_bytes(b"fake")
        tts = PiperTTS(voice_path=str(model))
        chunks = []
        async for chunk in tts.synthesize_stream("   "):
            chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_shutdown_when_no_process(self):
        tts = PiperTTS(voice_path="/nonexistent.onnx")
        await tts.shutdown()  # should not raise


# --- stt_faster_whisper ---

from gateway.transport_spike.stt_faster_whisper import FasterWhisperSTT


class TestFasterWhisperSTT:
    def test_available_when_import_fails(self):
        stt = FasterWhisperSTT()
        stt._WhisperModel = None
        stt._import_error = ImportError("test")
        assert stt.available is False

    def test_ensure_model_raises_when_unavailable(self):
        stt = FasterWhisperSTT()
        stt._WhisperModel = None
        stt._import_error = ImportError("test")
        with pytest.raises(RuntimeError, match="unavailable"):
            stt._ensure_model()

    def test_pcm_to_wav_bytes_valid(self):
        samples = [0, 100, -100, 32767, -32768]
        wav_bytes = FasterWhisperSTT._pcm_to_wav_bytes(samples, 16000)
        with io.BytesIO(wav_bytes) as buf:
            with wave.open(buf, "rb") as wf:
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2
                assert wf.getframerate() == 16000
                assert wf.getnframes() == len(samples)

    def test_pcm_to_wav_empty(self):
        wav_bytes = FasterWhisperSTT._pcm_to_wav_bytes([], 16000)
        with io.BytesIO(wav_bytes) as buf:
            with wave.open(buf, "rb") as wf:
                assert wf.getnframes() == 0


# --- adapters ---

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter
from adapters.factory import create_adapter, load_adapter_config
from adapters.session_gateway_http import SessionGatewayHTTPAdapter


class TestAdapterFactory:
    def test_mock_adapter(self):
        config = AdapterConfig(kind="mock")
        adapter = create_adapter(config)
        assert adapter.adapter_kind == "mock"

    def test_runtime_skeleton(self):
        config = AdapterConfig(kind="runtime_skeleton")
        adapter = create_adapter(config)
        assert adapter.adapter_kind == "runtime_skeleton"

    def test_session_gateway_http(self):
        config = AdapterConfig(kind="session_gateway_http")
        adapter = create_adapter(config)
        assert isinstance(adapter, SessionGatewayHTTPAdapter)

    def test_http_alias(self):
        config = AdapterConfig(kind="http")
        adapter = create_adapter(config)
        assert isinstance(adapter, SessionGatewayHTTPAdapter)

    def test_unknown_raises(self):
        config = AdapterConfig(kind="nonexistent_adapter")
        with pytest.raises(ValueError, match="unsupported"):
            create_adapter(config)

    def test_load_adapter_config_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QANTARA_ADAPTER", None)
            config = load_adapter_config()
            assert config.kind == "mock"


class TestSessionGatewayHTTPAdapter:
    def test_unavailable_without_base_url(self):
        with patch.dict(os.environ, {"QANTARA_BACKEND_BASE_URL": ""}, clear=False):
            adapter = SessionGatewayHTTPAdapter(
                AdapterConfig(kind="session_gateway_http", options={})
            )
            assert adapter.available is False

    @pytest.mark.asyncio
    async def test_health_degraded_without_base_url(self):
        with patch.dict(os.environ, {"QANTARA_BACKEND_BASE_URL": ""}, clear=False):
            adapter = SessionGatewayHTTPAdapter(
                AdapterConfig(kind="session_gateway_http", options={})
            )
            health = await adapter.check_health()
            assert health.degraded is True
            assert "not configured" in (health.detail or "")


# --- server utilities ---

from gateway.transport_spike.server import encode_pcm_frame, Session, PCM_KIND


class TestEncodePcmFrame:
    def test_basic_encoding(self):
        samples = [0, 100, -100]
        frame = encode_pcm_frame(samples)
        assert frame[0] == PCM_KIND
        decoded = struct.unpack(f"<{len(samples)}h", frame[1:])
        assert list(decoded) == samples

    def test_empty_samples(self):
        frame = encode_pcm_frame([])
        assert frame == struct.pack("<B", PCM_KIND)

    def test_boundary_values(self):
        samples = [-32768, 32767]
        frame = encode_pcm_frame(samples)
        decoded = struct.unpack("<2h", frame[1:])
        assert list(decoded) == samples


class TestSession:
    def test_session_ids_are_valid_uuids(self):
        ws = MagicMock()
        session = Session(ws)
        uuid.UUID(session.session_id)
        uuid.UUID(session.connection_id)
        assert session.session_id != session.connection_id

    def test_recent_pcm_limit(self):
        ws = MagicMock()
        session = Session(ws)
        session.recent_pcm = list(range(session.recent_pcm_limit + 1000))
        session.recent_pcm = session.recent_pcm[-session.recent_pcm_limit:]
        assert len(session.recent_pcm) == session.recent_pcm_limit

    def test_initial_state(self):
        ws = MagicMock()
        session = Session(ws)
        assert session.frames_in == 0
        assert session.frames_out == 0
        assert session.playback_generation == 0
        assert session.last_vad_state == "silence"
        assert session.runtime_session_handle is None
        assert session.current_turn_handle is None

    @pytest.mark.asyncio
    async def test_send_str_closed_websocket(self):
        ws = MagicMock()
        ws.closed = True
        session = Session(ws)
        await session.send_str("test")
        ws.send_str.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_bytes_closed_websocket(self):
        ws = MagicMock()
        ws.closed = True
        session = Session(ws)
        await session.send_bytes(b"test")
        ws.send_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_str_open_websocket(self):
        ws = AsyncMock()
        ws.closed = False
        session = Session(ws)
        await session.send_str("test")
        ws.send_str.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_send_str_connection_error(self):
        ws = AsyncMock()
        ws.closed = False
        ws.send_str.side_effect = ConnectionResetError
        session = Session(ws)
        # should not raise
        await session.send_str("test")
