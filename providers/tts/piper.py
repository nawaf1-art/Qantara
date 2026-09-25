from __future__ import annotations

import array
import asyncio
import contextlib
import importlib
import importlib.util
import os
import re
import sys
import threading
from dataclasses import dataclass, replace
from typing import Any

from providers.tts.base import TTSProvider, VoiceSpec
from providers.tts.routing import ensure_voice_for_text
from providers.voice_registry import (
    default_registry_path,
    filter_registry_voices,
)
from qantara.security import bridge_subprocess_environment

MAX_PIPER_AUDIO_BYTES = 64 * 1024 * 1024
MAX_PIPER_STDERR_BYTES = 256 * 1024


class PiperOutputLimitError(RuntimeError):
    pass


async def _read_bounded_stream(
    stream: asyncio.StreamReader,
    *,
    limit: int,
    label: str,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await stream.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise PiperOutputLimitError(
                f"piper {label} exceeded the configured limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _communicate_bounded(
    proc: asyncio.subprocess.Process,
    input_data: bytes,
    *,
    timeout: float,
) -> tuple[bytes, bytes]:
    stdin = getattr(proc, "stdin", None)
    stdout_stream = getattr(proc, "stdout", None)
    stderr_stream = getattr(proc, "stderr", None)
    if stdin is None or stdout_stream is None or stderr_stream is None:
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_data), timeout=timeout
            )
        except BaseException:
            if proc.returncode is None:
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.communicate()
            raise
        if len(stdout) > MAX_PIPER_AUDIO_BYTES:
            raise PiperOutputLimitError(
                "piper audio exceeded the configured limit"
            )
        if len(stderr) > MAX_PIPER_STDERR_BYTES:
            raise PiperOutputLimitError(
                "piper stderr exceeded the configured limit"
            )
        return stdout, stderr

    async def write_input() -> None:
        try:
            stdin.write(input_data)
            await stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        stdin.close()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            await stdin.wait_closed()

    tasks = [
        asyncio.create_task(write_input()),
        asyncio.create_task(
            _read_bounded_stream(
                stdout_stream,
                limit=MAX_PIPER_AUDIO_BYTES,
                label="audio",
            )
        ),
        asyncio.create_task(
            _read_bounded_stream(
                stderr_stream,
                limit=MAX_PIPER_STDERR_BYTES,
                label="stderr",
            )
        ),
        asyncio.create_task(proc.wait()),
    ]
    try:
        _, stdout, stderr, _ = await asyncio.wait_for(
            asyncio.gather(*tasks), timeout=timeout
        )
        return stdout, stderr
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await proc.communicate()
        raise


@dataclass(frozen=True, kw_only=True)
class PiperVoiceSpec(VoiceSpec):
    model_path: str
    config_path: str | None = None


_FALSY = {"0", "false", "no", "off"}
_MODEL_LOCALE_RE = re.compile(r"^([a-z]{2,3})_([A-Z]{2})-")


def _module_importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def decode_pcm16le(data: bytes) -> list[int]:
    """Decode little-endian signed 16-bit PCM without a per-sample loop."""
    usable = len(data) - (len(data) % 2)
    samples = array.array("h")
    samples.frombytes(data[:usable])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples.tolist()


def _default_model_path() -> str | None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidate = os.path.join(repo_root, "models", "piper", "en_US-lessac-medium.onnx")
    return candidate if os.path.exists(candidate) else None


def _default_config_path(model_path: str | None) -> str | None:
    if not model_path:
        return None
    candidate = f"{model_path}.json"
    return candidate if os.path.exists(candidate) else None


def _voice_id_for_model_path(model_path: str) -> str:
    stem = os.path.basename(model_path)
    if stem.endswith(".onnx"):
        stem = stem[: -len(".onnx")]
    # Keep the registry id for the stock English voice.
    return "lessac" if stem == "en_US-lessac-medium" else stem


def _locale_for_model_path(model_path: str) -> str:
    match = _MODEL_LOCALE_RE.match(os.path.basename(model_path))
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return "en-US"


class PiperTTSProvider(TTSProvider):
    kind = "piper"

    def __init__(
        self,
        registry_path: str | None = None,
        voice_path: str | None = None,
        config_path: str | None = None,
        sample_rate: int = 22050,
        *,
        piper_module: Any | None = None,
        in_process: bool | None = None,
    ) -> None:
        self.registry_path = registry_path or os.environ.get("QANTARA_VOICE_REGISTRY") or default_registry_path()
        self.sample_rate = sample_rate
        self.timeout_seconds = float(os.environ.get("QANTARA_PIPER_TIMEOUT", "60"))
        self.command = [sys.executable, "-m", "piper"]
        # Both paths need the piper-tts package: in-process imports it, the
        # subprocess fallback runs `python -m piper` in this interpreter.
        self._piper_module = piper_module
        self._piper_importable = piper_module is not None or _module_importable("piper")
        if in_process is None:
            in_process = os.environ.get("QANTARA_PIPER_IN_PROCESS", "1").strip().lower() not in _FALSY
        self._in_process = bool(in_process) and self._piper_importable
        self._loaded_voices: dict[str, Any] = {}
        self._load_lock = threading.Lock()
        self._preferred_voice_id: str | None = None
        self.voices = self._load_voices(voice_path=voice_path, config_path=config_path)
        self.voice_entries = {
            entry.voice_id: entry for entry in filter_registry_voices("piper", self.registry_path)
        }
        self._default_voice_id = self._resolve_default_voice_id()

    @property
    def available(self) -> bool:
        return self._piper_importable and self._first_available_voice() is not None

    @property
    def in_process(self) -> bool:
        return self._in_process

    @property
    def default_voice_id(self) -> str | None:
        return self._default_voice_id

    def list_available_voices(self) -> list[dict]:
        available = []
        for voice in self.voices.values():
            if os.path.exists(voice.model_path):
                available.append(
                    {
                        "voice_id": voice.voice_id,
                        "label": voice.label,
                        "locale": voice.locale,
                        "sample_rate": voice.sample_rate,
                        "defaults": dict(voice.defaults or {}),
                        "allowed_transforms": list(voice.allowed_transforms or []),
                    }
                )
        return available

    def resolve_voice(self, voice_id: str | None) -> tuple[VoiceSpec, str | None]:
        requested = voice_id or self.default_voice_id
        if requested and requested in self.voices:
            voice = self.voices[requested]
            if os.path.exists(voice.model_path):
                return voice, None

        fallback = self._first_available_voice()
        if fallback is None:
            raise RuntimeError("piper is not available")
        if requested and requested != fallback.voice_id:
            return fallback, f"requested voice '{requested}' unavailable; using '{fallback.voice_id}'"
        return fallback, None

    def _guard_voice(
        self,
        voice: VoiceSpec,
        text: str,
        language: str | None,
    ) -> tuple[VoiceSpec, str | None]:
        installed = [
            v for v in getattr(self, "voices", {}).values() if os.path.exists(v.model_path)
        ]
        return ensure_voice_for_text(voice, installed, text, language, engine=self.kind)

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speech_rate: float | None = None,
        *,
        expressiveness: float | None = None,  # noqa: ARG002 — not used by Piper
        language: str | None = None,
    ) -> tuple[list[int], VoiceSpec, str | None]:
        voice, fallback_reason = self.resolve_voice(voice_id)
        voice, guard_reason = self._guard_voice(voice, text, language)
        if guard_reason:
            fallback_reason = guard_reason
        effective_rate = speech_rate if isinstance(speech_rate, (int, float)) else 1.0
        effective_rate = max(0.85, min(1.30, float(effective_rate)))
        length_scale = 1.0 / effective_rate

        if getattr(self, "_in_process", False):
            try:
                samples, sample_rate = await asyncio.wait_for(
                    asyncio.to_thread(self._synthesize_in_process, voice, text, length_scale),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as exc:
                raise RuntimeError(
                    f"piper timed out after {self.timeout_seconds:g} seconds"
                ) from exc
            if sample_rate and sample_rate != voice.sample_rate:
                voice = replace(voice, sample_rate=int(sample_rate))
            return samples, voice, fallback_reason

        return await self._synthesize_subprocess(voice, text, length_scale, fallback_reason)

    # -- in-process path (piper-tts importable) -----------------------------

    def _piper(self) -> Any:
        if self._piper_module is None:
            self._piper_module = importlib.import_module("piper")
        return self._piper_module

    def _load_piper_voice(self, voice: PiperVoiceSpec) -> Any:
        key = voice.model_path
        loaded = self._loaded_voices.get(key)
        if loaded is not None:
            return loaded
        with self._load_lock:
            loaded = self._loaded_voices.get(key)
            if loaded is None:
                loaded = self._piper().PiperVoice.load(voice.model_path, config_path=voice.config_path)
                self._loaded_voices[key] = loaded
        return loaded

    def _synthesize_in_process(
        self,
        voice: PiperVoiceSpec,
        text: str,
        length_scale: float,
    ) -> tuple[list[int], int | None]:
        piper_voice = self._load_piper_voice(voice)
        syn_config = self._piper().SynthesisConfig(length_scale=length_scale)
        parts: list[bytes] = []
        total = 0
        sample_rate: int | None = None
        for chunk in piper_voice.synthesize(text, syn_config=syn_config):
            if sample_rate is None:
                sample_rate = getattr(chunk, "sample_rate", None)
            data = chunk.audio_int16_bytes
            total += len(data)
            if total > MAX_PIPER_AUDIO_BYTES:
                raise PiperOutputLimitError("piper audio exceeded the configured limit")
            parts.append(data)
        return decode_pcm16le(b"".join(parts)), sample_rate

    # -- subprocess fallback --------------------------------------------------

    async def _synthesize_subprocess(
        self,
        voice: PiperVoiceSpec,
        text: str,
        length_scale: float,
        fallback_reason: str | None,
    ) -> tuple[list[int], VoiceSpec, str | None]:
        cmd = [
            *self.command,
            "--model",
            voice.model_path,
            "--output-raw",
            "--length-scale",
            f"{length_scale:.4f}",
        ]
        if voice.config_path is not None:
            cmd.extend(["--config", voice.config_path])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=bridge_subprocess_environment(),
        )

        try:
            stdout, stderr = await _communicate_bounded(
                proc,
                text.encode("utf-8"),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise RuntimeError(
                f"piper timed out after {self.timeout_seconds:g} seconds"
            ) from exc
        if proc.returncode != 0:
            detail = stderr[:4096].decode("utf-8", errors="replace")
            raise RuntimeError(detail or "piper failed")

        return decode_pcm16le(stdout), voice, fallback_reason

    def _first_available_voice(self) -> PiperVoiceSpec | None:
        for voice in self.voices.values():
            if os.path.exists(voice.model_path):
                return voice
        return None

    def _load_voices(
        self,
        voice_path: str | None,
        config_path: str | None,
    ) -> dict[str, PiperVoiceSpec]:
        voices: dict[str, PiperVoiceSpec] = {}

        for entry in filter_registry_voices("piper", self.registry_path):
            if not entry.model_path:
                continue
            voice = PiperVoiceSpec(
                voice_id=entry.voice_id,
                label=entry.label,
                model_path=entry.model_path,
                config_path=entry.config_path or _default_config_path(entry.model_path),
                sample_rate=entry.sample_rate or self.sample_rate,
                locale=entry.locale,
                defaults=entry.defaults,
                allowed_transforms=entry.allowed_transforms,
            )
            voices[voice.voice_id] = voice

        # An explicit model (constructor or QANTARA_PIPER_MODEL) is honored
        # even when a registry exists: it becomes the default voice.
        override_path = voice_path or os.environ.get("QANTARA_PIPER_MODEL", "").strip() or None
        if override_path:
            override_abs = os.path.abspath(override_path)
            for voice in voices.values():
                if os.path.abspath(voice.model_path) == override_abs:
                    self._preferred_voice_id = voice.voice_id
                    if config_path:
                        voices[voice.voice_id] = replace(voice, config_path=config_path)
                    return voices
            override = self._voice_from_model_path(override_path, config_path)
            self._preferred_voice_id = override.voice_id
            rest = {k: v for k, v in voices.items() if k != override.voice_id}
            return {override.voice_id: override, **rest}

        if voices:
            return voices

        fallback_voice_path = _default_model_path()
        if fallback_voice_path is None:
            return {}
        fallback = self._voice_from_model_path(fallback_voice_path, config_path)
        return {fallback.voice_id: fallback}

    def _voice_from_model_path(self, model_path: str, config_path: str | None) -> PiperVoiceSpec:
        voice_id = _voice_id_for_model_path(model_path)
        return PiperVoiceSpec(
            voice_id=voice_id,
            label="Lessac" if voice_id == "lessac" else voice_id,
            model_path=model_path,
            config_path=config_path or _default_config_path(model_path),
            sample_rate=self.sample_rate,
            locale=_locale_for_model_path(model_path),
            defaults={"rate": 1.0, "pitch": 0, "tone": "neutral"},
            allowed_transforms=["rate"],
        )

    def _resolve_default_voice_id(self) -> str | None:
        env_default = os.environ.get("QANTARA_PIPER_VOICE", "").strip()
        if env_default and env_default in self.voices:
            return env_default
        preferred = self._preferred_voice_id
        if preferred and preferred in self.voices and os.path.exists(self.voices[preferred].model_path):
            return preferred
        available = self._first_available_voice()
        if available is not None:
            return available.voice_id
        return next(iter(self.voices), None)
