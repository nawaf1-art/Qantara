import asyncio
import json
import math
import os
import re
import ssl
import sys
import time
import unicodedata
import uuid
from typing import Any

import aiohttp as _aiohttp
from aiohttp import WSMsgType, web

CURRENT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
CLIENT_SPIKE_DIR = os.path.join(REPO_ROOT, "client", "transport-spike")
CLIENT_SETUP_DIR = os.path.join(REPO_ROOT, "client", "setup")
IDENTITY_DIR = os.path.join(REPO_ROOT, "identity")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from adapters.base import AdapterConfig
from adapters.factory import create_adapter, load_adapter_config
from providers.factory import create_stt_provider, create_tts_provider


PCM_KIND = 0x01
TARGET_SAMPLE_RATE = 16000
TONE_HZ = 440.0
TONE_SECONDS = 1.25
FRAME_SAMPLES = 1920  # ~80ms at 24kHz — larger frames reduce playback gaps/buzzing
DEFAULT_HOST = os.environ.get("QANTARA_SPIKE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("QANTARA_SPIKE_PORT", "8765"))
TLS_CERT_FILE = os.environ.get("QANTARA_TLS_CERT")
TLS_KEY_FILE = os.environ.get("QANTARA_TLS_KEY")
DEFAULT_SPEECH_RATE = float(os.environ.get("QANTARA_DEFAULT_SPEECH_RATE", "1.2"))


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Session:
    def __init__(self, websocket: web.WebSocketResponse) -> None:
        self.websocket = websocket
        self.session_id = str(uuid.uuid4())
        self.connection_id = str(uuid.uuid4())
        self.started_monotonic_ms = round(time.monotonic() * 1000, 3)
        self.runtime_session_handle = None
        self.turn_id = None
        self.frames_in = 0
        self.frames_out = 0
        self.playback_generation = 0
        self.last_vad_state = "silence"
        self.recent_pcm: list[int] = []
        self.recent_pcm_limit = TARGET_SAMPLE_RATE * 6
        self.last_tts_started_ms: float | None = None
        self.current_turn_handle: str | None = None
        self.current_turn_task: asyncio.Task | None = None
        self.speech_task: asyncio.Task | None = None
        self.speech_generation = 0
        self.turns_completed = 0
        self.client_name = "browser-transport-spike"
        self.client_session_id = self.session_id
        self.requested_voice_id: str | None = None
        self.voice_id: str | None = TTS.default_voice_id
        self.speech_rate: float = DEFAULT_SPEECH_RATE

    async def emit(self, event_name: str, source: str, payload: dict) -> None:
        record = {
            "event_name": event_name,
            "session_id": self.session_id,
            "connection_id": self.connection_id,
            "turn_id": self.turn_id,
            "ts_monotonic_ms": round(time.monotonic() * 1000, 3),
            "ts_wall_time": utc_now(),
            "source": source,
            "payload": payload,
        }
        print(json.dumps(record), flush=True)


ADAPTER_CONFIG = load_adapter_config()
ADAPTER = create_adapter(ADAPTER_CONFIG)
STT = create_stt_provider()
TTS = create_tts_provider()
LAST_ADAPTER_HEALTH = {"status": "unknown", "detail": "health pending"}

# --- In-process configuration state for 0.1.4 setup experience ---

_current_config: dict[str, Any] = {
    "type": ADAPTER_CONFIG.kind,
    "url": os.environ.get("QANTARA_BACKEND_BASE_URL", ""),
    "model": os.environ.get("QANTARA_OLLAMA_MODEL", ""),
    "agent": "",
}

# --- Managed backend bridge subprocess ---

_BRIDGE_SCRIPTS: dict[str, str] = {
    "ollama": os.path.join(REPO_ROOT, "gateway", "ollama_session_backend", "server.py"),
    "openclaw": os.path.join(REPO_ROOT, "gateway", "openclaw_session_backend", "server.py"),
}
_managed_bridge_proc: asyncio.subprocess.Process | None = None
_managed_bridge_type: str | None = None
MANAGED_BRIDGE_PORT = 19120


async def _stop_managed_bridge() -> None:
    """Stop the currently running managed bridge subprocess, if any."""
    global _managed_bridge_proc, _managed_bridge_type
    if _managed_bridge_proc is None:
        return
    try:
        _managed_bridge_proc.terminate()
        try:
            await asyncio.wait_for(_managed_bridge_proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            _managed_bridge_proc.kill()
            await _managed_bridge_proc.wait()
    except ProcessLookupError:
        pass
    _managed_bridge_proc = None
    _managed_bridge_type = None


async def _start_managed_bridge(bridge_type: str, env_overrides: dict[str, str] | None = None) -> None:
    """Start a managed bridge subprocess, replacing any existing one."""
    global _managed_bridge_proc, _managed_bridge_type
    await _stop_managed_bridge()

    script = _BRIDGE_SCRIPTS.get(bridge_type)
    if script is None or not os.path.isfile(script):
        return

    env = os.environ.copy()
    env["QANTARA_REAL_BACKEND_PORT"] = str(MANAGED_BRIDGE_PORT)
    env["QANTARA_REAL_BACKEND_HOST"] = "127.0.0.1"
    if env_overrides:
        env.update(env_overrides)

    _managed_bridge_proc = await asyncio.create_subprocess_exec(
        sys.executable, script,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _managed_bridge_type = bridge_type


async def _health_check_bridge(url: str, retries: int = 8, delay: float = 0.4) -> dict[str, Any]:
    """Poll bridge health endpoint until ready or retries exhausted."""
    timeout = _aiohttp.ClientTimeout(total=2)
    for attempt in range(retries):
        try:
            async with _aiohttp.ClientSession(timeout=timeout) as cs:
                async with cs.get(f"{url}/health") as resp:
                    if resp.status < 500:
                        return {"status": "ok", "detail": "bridge healthy"}
        except Exception:
            pass
        await asyncio.sleep(delay)
    return {"status": "degraded", "detail": "bridge not ready after retries"}


async def _cleanup_bridge(_app: web.Application) -> None:
    """Cleanup hook: stop managed bridge on app shutdown."""
    await _stop_managed_bridge()


def _ollama_base_url() -> str:
    """Return the Ollama base URL, preferring QANTARA_OLLAMA_BASE_URL env var."""
    return os.environ.get("QANTARA_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


async def _probe_ollama() -> dict[str, Any]:
    """Probe Ollama for available models with size info."""
    url = f"{_ollama_base_url()}/api/tags"
    try:
        timeout = _aiohttp.ClientTimeout(total=3)
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {"available": False}
                data = await resp.json()
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "")
                    if not name:
                        continue
                    size_bytes = m.get("size", 0)
                    size_gb = round(size_bytes / (1024 ** 3), 1) if size_bytes else None
                    family = m.get("details", {}).get("family", "")
                    param_size = m.get("details", {}).get("parameter_size", "")
                    models.append({
                        "name": name,
                        "size_gb": size_gb,
                        "family": family,
                        "param_size": param_size,
                    })
                return {"available": True, "models": models}
    except Exception:
        return {"available": False}


async def _probe_openclaw() -> dict[str, Any]:
    """Probe OpenClaw: check installation, gateway health, and list agents."""
    import shutil
    result: dict[str, Any] = {"available": False, "installed": False, "gateway_running": False, "agents": []}

    openclaw_bin = os.environ.get("QANTARA_OPENCLAW_BIN", "openclaw")
    if not shutil.which(openclaw_bin):
        return result
    result["installed"] = True

    # Check gateway health
    try:
        proc = await asyncio.create_subprocess_exec(
            openclaw_bin, "health", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        health = json.loads(stdout.decode("utf-8", errors="replace"))
        if health.get("ok"):
            result["gateway_running"] = True
        else:
            return result
    except Exception:
        return result

    # List agents (openclaw agents list can be slow due to channel probes)
    try:
        proc = await asyncio.create_subprocess_exec(
            openclaw_bin, "agents", "list", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        agents_data = json.loads(stdout.decode("utf-8", errors="replace"))
        if isinstance(agents_data, list):
            for a in agents_data:
                agent_id = a.get("id", a.get("name", ""))
                if agent_id:
                    result["agents"].append({
                        "id": agent_id,
                        "name": a.get("identityName", agent_id),
                        "default": a.get("isDefault", False),
                    })
    except Exception:
        pass

    result["available"] = result["gateway_running"] and len(result["agents"]) > 0
    return result


async def _probe_openai_port(host: str, port: int) -> dict[str, Any] | None:
    """Probe a single port for an OpenAI-compatible server."""
    url = f"http://{host}:{port}/v1/models"
    try:
        timeout = _aiohttp.ClientTimeout(total=2)
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json()
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                if models:
                    return {"port": port, "models": models, "url": f"http://{host}:{port}"}
    except Exception:
        pass
    return None


async def _probe_openai_compatible() -> dict[str, Any]:
    """Probe common ports for OpenAI-compatible servers (not Ollama)."""
    ports = [8080, 8000, 1337, 1234]
    tasks = [_probe_openai_port("127.0.0.1", p) for p in ports]
    results = await asyncio.gather(*tasks)
    servers = [r for r in results if r is not None]
    if servers:
        return {"available": True, "servers": servers}
    return {"available": False}


async def api_backends_handler(_request: web.Request) -> web.Response:
    """GET /api/backends — detect available backends."""
    ollama_result, openclaw_result, openai_result = await asyncio.gather(
        _probe_ollama(), _probe_openclaw(), _probe_openai_compatible()
    )

    backends: list[dict[str, Any]] = []

    # Ollama
    if ollama_result["available"]:
        backends.append({
            "type": "ollama",
            "name": "Ollama",
            "available": True,
            "models": ollama_result.get("models", []),
        })
    else:
        backends.append({"type": "ollama", "name": "Ollama", "available": False})

    # OpenClaw
    oc: dict[str, Any] = {"type": "openclaw", "name": "OpenClaw", "available": openclaw_result["available"]}
    oc["installed"] = openclaw_result.get("installed", False)
    oc["gateway_running"] = openclaw_result.get("gateway_running", False)
    oc["agents"] = openclaw_result.get("agents", [])
    backends.append(oc)

    # OpenAI-compatible (auto-detected on common ports)
    oai: dict[str, Any] = {
        "type": "openai_compatible",
        "name": "OpenAI-Compatible",
        "available": True,  # Always selectable — user can enter any URL
    }
    if openai_result["available"]:
        oai["servers"] = openai_result.get("servers", [])
        oai["auto_detected"] = True
    backends.append(oai)

    # Custom URL (always available)
    backends.append({"type": "custom", "name": "Custom URL", "available": True})

    # Demo/Mock (always available, last)
    backends.append({"type": "mock", "name": "Demo", "available": True})

    return web.json_response({"backends": backends})


async def api_status_handler(_request: web.Request) -> web.Response:
    """GET /api/status — return current backend configuration and health."""
    return web.json_response({
        "type": _current_config["type"],
        "model": _current_config["model"],
        "agent": _current_config["agent"],
        "url": _current_config["url"],
        "adapter_kind": ADAPTER.adapter_kind,
        "health": LAST_ADAPTER_HEALTH,
        "managed_bridge": _managed_bridge_type,
    })


async def api_configure_handler(request: web.Request) -> web.Response:
    """POST /api/configure — switch backend adapter in-process.

    Accepted body shapes:
      {"type":"ollama","model":"qwen2.5:7b"}
      {"type":"openclaw","agent":"spectra"}
      {"type":"custom","url":"http://..."}
      {"type":"mock"}
    """
    global ADAPTER, ADAPTER_CONFIG, _current_config

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    backend_type = body.get("type", "").strip().lower()
    if not backend_type:
        return web.json_response({"error": "missing 'type' field"}, status=400)

    url = body.get("url", "").strip().rstrip("/")
    model = body.get("model", "").strip()
    agent = body.get("agent", "").strip()

    bridge_url = f"http://127.0.0.1:{MANAGED_BRIDGE_PORT}"

    # Map user-facing type to adapter kind + url, manage bridge subprocess
    if backend_type == "mock":
        adapter_kind = "mock"
        url = ""
        await _stop_managed_bridge()
    elif backend_type == "ollama":
        adapter_kind = "session_gateway_http"
        env_overrides: dict[str, str] = {}
        ollama_url = os.environ.get("QANTARA_OLLAMA_BASE_URL")
        if ollama_url:
            env_overrides["QANTARA_OLLAMA_BASE_URL"] = ollama_url
        if model:
            env_overrides["QANTARA_OLLAMA_MODEL"] = model
        await _start_managed_bridge("ollama", env_overrides=env_overrides)
        await _health_check_bridge(bridge_url)
        url = url or bridge_url
    elif backend_type == "openclaw":
        adapter_kind = "session_gateway_http"
        env_overrides = {}
        if agent:
            env_overrides["QANTARA_OPENCLAW_AGENT_ID"] = agent
        await _start_managed_bridge("openclaw", env_overrides=env_overrides)
        await _health_check_bridge(bridge_url)
        url = url or bridge_url
    elif backend_type in ("openai_compatible", "openai"):
        if not url:
            return web.json_response(
                {"error": "openai_compatible type requires 'url'"}, status=400
            )
        adapter_kind = "openai_compatible"
        await _stop_managed_bridge()
    elif backend_type == "custom":
        if not url:
            return web.json_response(
                {"error": "custom type requires 'url'"}, status=400
            )
        adapter_kind = "session_gateway_http"
        await _stop_managed_bridge()
    else:
        return web.json_response(
            {"error": f"unknown type: {backend_type}"}, status=400
        )

    # Build new adapter config and swap
    new_config = AdapterConfig(kind=adapter_kind, name=backend_type)
    if adapter_kind == "session_gateway_http":
        new_config.options["base_url"] = url
    elif adapter_kind == "openai_compatible":
        new_config.options["base_url"] = url
        if model:
            new_config.options["model"] = model

    new_adapter = create_adapter(new_config)
    ADAPTER_CONFIG = new_config
    ADAPTER = new_adapter

    _current_config = {
        "type": backend_type,
        "url": url,
        "model": model,
        "agent": agent,
    }

    # Health-check the new adapter
    try:
        health = await ADAPTER.check_health()
        health_result = {"status": health.status, "detail": health.detail}
    except Exception as exc:
        health_result = {"status": "degraded", "detail": str(exc)}

    global LAST_ADAPTER_HEALTH
    LAST_ADAPTER_HEALTH = health_result

    return web.json_response({
        "ok": True,
        "type": backend_type,
        "adapter_kind": adapter_kind,
        "url": url,
        "health": health_result,
    })


async def api_test_url_handler(request: web.Request) -> web.Response:
    """POST /api/test-url — server-side proxy to test an OpenAI-compatible URL.

    Bypasses browser CORS restrictions by probing from the gateway.
    Body: {"url": "http://..."}
    Returns: {"ok": true, "models": [...]} or {"ok": false, "error": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    raw_url = (body.get("url") or "").strip().rstrip("/")
    if not raw_url:
        return web.json_response({"ok": False, "error": "missing url"}, status=400)

    if not raw_url.startswith(("http://", "https://")):
        raw_url = "http://" + raw_url

    # Strip /v1 suffix if present
    base = raw_url
    if base.endswith("/v1"):
        base = base[:-3]

    # Try /v1/models, then /models
    timeout = _aiohttp.ClientTimeout(total=5)
    for prefix in ("/v1", ""):
        try:
            async with _aiohttp.ClientSession(timeout=timeout) as cs:
                async with cs.get(f"{base}{prefix}/models") as resp:
                    if resp.status < 400:
                        data = await resp.json()
                        models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                        return web.json_response({"ok": True, "models": models, "url": base})
        except Exception:
            continue

    return web.json_response({"ok": False, "error": f"Cannot reach {base}. Is the server running?"})


async def refresh_adapter_health(session: Session | None = None) -> None:
    global LAST_ADAPTER_HEALTH
    try:
        health = await ADAPTER.check_health()
        LAST_ADAPTER_HEALTH = {"status": health.status, "detail": health.detail}
        if session is not None:
            try:
                await session.websocket.send_str(
                    json.dumps(
                        {
                            "type": "adapter_status",
                            "adapter_kind": ADAPTER.adapter_kind,
                            "adapter_health": health.status,
                            "adapter_detail": health.detail,
                        }
                    )
                )
            except Exception:
                pass
    except Exception as exc:
        LAST_ADAPTER_HEALTH = {"status": "degraded", "detail": str(exc)}
        if session is not None:
            try:
                await session.websocket.send_str(
                    json.dumps(
                        {
                            "type": "adapter_status",
                            "adapter_kind": ADAPTER.adapter_kind,
                            "adapter_health": "degraded",
                            "adapter_detail": str(exc),
                        }
                    )
                )
            except Exception:
                pass


def websocket_is_writable(session: Session) -> bool:
    return not session.websocket.closed


async def safe_send_str(session: Session, payload: dict) -> bool:
    if not websocket_is_writable(session):
        return False
    try:
        await session.websocket.send_str(json.dumps(payload))
        return True
    except Exception:
        return False


async def safe_send_bytes(session: Session, payload: bytes) -> bool:
    if not websocket_is_writable(session):
        return False
    try:
        await session.websocket.send_bytes(payload)
        return True
    except Exception:
        return False


def encode_pcm_frame(samples: list[int]) -> bytes:
    payload = bytearray(1 + len(samples) * 2)
    payload[0] = PCM_KIND
    offset = 1
    for sample in samples:
        payload[offset:offset + 2] = int(sample).to_bytes(2, "little", signed=True)
        offset += 2
    return bytes(payload)


def normalize_tts_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized

    normalized = normalized.replace("\r", "\n")
    normalized = re.sub(r"`([^`]*)`", r"\1", normalized)
    normalized = normalized.replace("**", "")
    normalized = normalized.replace("__", "")
    normalized = normalized.replace("*", "")

    normalized = re.sub(r"(?m)^\s*[-•]\s+", "", normalized)
    normalized = normalized.replace(" - ", ". ")
    normalized = normalized.replace("\n- ", ". ")
    normalized = normalized.replace("\n", ". ")

    normalized = re.sub(r"([A-Za-z0-9])\s*/\s*([A-Za-z0-9])", r"\1 or \2", normalized)
    normalized = re.sub(
        r"([+-])\s*(\d+)\s*°\s*C",
        lambda m: f"{'minus' if m.group(1) == '-' else 'plus'} {m.group(2)} degrees Celsius",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"(\d+)\s*°\s*C", r"\1 degrees Celsius", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d+)\s*km/h", r"\1 kilometers per hour", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d+(?:\.\d+)?)\s*mm", r"\1 millimeters", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", normalized)

    cleaned_chars: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if category == "So":
            continue
        cleaned_chars.append(char)
    normalized = "".join(cleaned_chars)

    normalized = normalized.replace("↘", " ")
    normalized = re.sub(r"[|]+", ". ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"([!?.,]){2,}", r"\1", normalized)
    normalized = re.sub(r"\s+([!?.,])", r"\1", normalized)
    return normalized.strip()


async def send_tone(session: Session) -> None:
    generation = session.playback_generation
    total_samples = int(TARGET_SAMPLE_RATE * TONE_SECONDS)
    amplitude = 0.22 * 32767

    await session.emit("playback_started", "playback", {"kind": "synthetic_tone"})

    sent_any = False
    first_frame_sent = False
    for offset in range(0, total_samples, FRAME_SAMPLES):
        if generation != session.playback_generation:
            await safe_send_str(session, {"type": "playback_stopped", "reason": "cleared", "kind": "synthetic_tone"})
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
            return
        frame = []
        for i in range(offset, min(offset + FRAME_SAMPLES, total_samples)):
            value = math.sin(2 * math.pi * TONE_HZ * (i / TARGET_SAMPLE_RATE))
            frame.append(int(amplitude * value))
        if not await safe_send_bytes(session, encode_pcm_frame(frame)):
            return
        session.frames_out += 1
        sent_any = True
        if not first_frame_sent:
            first_frame_sent = True
            await safe_send_str(
                session,
                {
                    "type": "playback_metrics",
                    "engine": "synthetic",
                    "kind": "synthetic_tone",
                    "tts_to_first_audio_ms": 0,
                    "synthesis_ms": 0,
                },
            )
            await session.emit(
                "playback_first_frame_sent",
                "playback",
                {"kind": "synthetic_tone", "tts_to_first_audio_ms": 0},
            )
        await session.emit(
            "output_audio_frame_sent",
            "playback",
            {
                "frame_index": session.frames_out,
                "frame_samples": len(frame),
                "sample_rate": TARGET_SAMPLE_RATE,
            },
        )
        await asyncio.sleep(len(frame) / TARGET_SAMPLE_RATE)

    if sent_any:
        await safe_send_str(session, {"type": "playback_stopped", "reason": "tone_complete", "kind": "synthetic_tone"})
        await session.emit("playback_stopped", "playback", {"reason": "tone_complete"})


async def send_pcm_samples(
    session: Session,
    samples: list[int],
    sample_rate: int,
    kind: str,
    engine: str | None = None,
    tts_started_ms: float | None = None,
    synthesis_ms: float | None = None,
    expected_generation: int | None = None,
) -> None:
    generation = session.playback_generation if expected_generation is None else expected_generation
    if generation != session.playback_generation:
        return
    await session.emit("playback_started", "playback", {"kind": kind, "sample_rate": sample_rate})

    sent_any = False
    first_frame_sent = False
    for offset in range(0, len(samples), FRAME_SAMPLES):
        if generation != session.playback_generation:
            await safe_send_str(session, {"type": "playback_stopped", "reason": "cleared", "kind": kind})
            await session.emit("playback_stopped", "playback", {"reason": "cleared"})
            return

        frame = samples[offset:offset + FRAME_SAMPLES]
        if not await safe_send_bytes(session, encode_pcm_frame(frame)):
            return
        session.frames_out += 1
        sent_any = True
        if not first_frame_sent:
            first_frame_sent = True
            first_audio_ms = None
            if tts_started_ms is not None:
                first_audio_ms = round((time.monotonic() * 1000) - tts_started_ms, 3)
            await safe_send_str(
                session,
                {
                    "type": "playback_metrics",
                    "engine": engine or "synthetic",
                    "kind": kind,
                    "tts_to_first_audio_ms": first_audio_ms,
                    "synthesis_ms": synthesis_ms,
                },
            )
            await session.emit(
                "playback_first_frame_sent",
                "playback",
                {
                    "kind": kind,
                    "tts_to_first_audio_ms": first_audio_ms,
                    "synthesis_ms": synthesis_ms,
                },
            )
        await session.emit(
            "output_audio_frame_sent",
            "playback",
            {
                "frame_index": session.frames_out,
                "frame_samples": len(frame),
                "sample_rate": sample_rate,
                "kind": kind,
            },
        )
        await asyncio.sleep(len(frame) / sample_rate)

    if sent_any:
        reason = f"{kind}_complete"
        await safe_send_str(session, {"type": "playback_stopped", "reason": reason, "kind": kind})
        await session.emit("playback_stopped", "playback", {"reason": reason})


async def speak_text(session: Session, text: str, expected_generation: int | None = None) -> None:
    if expected_generation is not None and expected_generation != session.playback_generation:
        return
    spoken_text = normalize_tts_text(text)
    if not spoken_text:
        return
    engine = TTS.kind if TTS.available else "synthetic"
    resolved_voice = None
    fallback_reason = None
    if TTS.available:
        try:
            resolved_voice, fallback_reason = TTS.resolve_voice(session.voice_id)
        except Exception:
            resolved_voice = None
    session.last_tts_started_ms = time.monotonic() * 1000
    await session.emit(
        "tts_chunk_ready",
        "playback",
        {"char_count": len(spoken_text), "engine": engine, "source_char_count": len(text)},
    )
    if not await safe_send_str(
        session,
        {
            "type": "tts_status",
            "engine": engine,
            "available": TTS.available,
            "voice_id": resolved_voice.voice_id if resolved_voice is not None else session.voice_id,
            "requested_voice_id": session.requested_voice_id or session.voice_id,
            "speech_rate": session.speech_rate,
            "sample_rate": resolved_voice.sample_rate if resolved_voice is not None else TARGET_SAMPLE_RATE,
            "reason": fallback_reason if resolved_voice is not None else (None if TTS.available else "tts provider unavailable or no voice configured"),
        },
    ):
        return

    if TTS.available:
        try:
            synthesis_started_ms = time.monotonic() * 1000
            samples, resolved_voice, fallback_reason = await TTS.synthesize(
                spoken_text,
                voice_id=session.voice_id,
                speech_rate=session.speech_rate,
            )
            synthesis_ms = round((time.monotonic() * 1000) - synthesis_started_ms, 3)
            session.voice_id = resolved_voice.voice_id
            await session.emit(
                "tts_chunk_ready",
                "playback",
                {
                    "char_count": len(spoken_text),
                    "engine": TTS.kind,
                    "sample_count": len(samples),
                    "synthesis_ms": synthesis_ms,
                    "voice_id": resolved_voice.voice_id,
                    "requested_voice_id": session.requested_voice_id or resolved_voice.voice_id,
                    "speech_rate": session.speech_rate,
                    "fallback_reason": fallback_reason,
                    "source_char_count": len(text),
                },
            )
            if fallback_reason is not None:
                await safe_send_str(
                    session,
                    {
                        "type": "tts_status",
                        "engine": TTS.kind,
                        "available": True,
                        "voice_id": resolved_voice.voice_id,
                        "requested_voice_id": session.requested_voice_id,
                        "speech_rate": session.speech_rate,
                        "reason": fallback_reason,
                    },
                )
            await send_pcm_samples(
                session,
                samples,
                resolved_voice.sample_rate,
                f"{TTS.kind}_tts",
                engine=TTS.kind,
                tts_started_ms=session.last_tts_started_ms,
                synthesis_ms=synthesis_ms,
                expected_generation=expected_generation,
            )
            return
        except Exception as exc:
            await session.emit(
                "recoverable_error",
                "playback",
                {"component": "tts", "message": str(exc), "engine": TTS.kind},
            )
            await safe_send_str(
                session,
                {
                    "type": "tts_status",
                    "engine": "synthetic",
                    "available": False,
                    "reason": f"{TTS.kind} failed: {exc}",
                },
            )

    # No fallback tone — if TTS fails, silence is better than a buzzing sine wave.


async def _run_speech_segment(
    previous_task: asyncio.Task | None,
    session: Session,
    text: str,
    expected_generation: int,
) -> None:
    if previous_task is not None:
        try:
            await previous_task
        except asyncio.CancelledError:
            return
        except Exception:
            return

    if expected_generation != session.speech_generation:
        return

    await speak_text(session, text, expected_generation=expected_generation)


def enqueue_speech(session: Session, text: str) -> None:
    if not text.strip():
        return

    previous_task = session.speech_task
    generation = session.speech_generation
    session.speech_task = asyncio.create_task(_run_speech_segment(previous_task, session, text, generation))


async def ensure_adapter_session(session: Session) -> None:
    if session.runtime_session_handle is None:
        session.runtime_session_handle = await ADAPTER.start_or_resume_session(
            {
                "client_name": session.client_name,
                "session_id": session.session_id,
                "client_session_id": session.client_session_id,
                "voice_id": session.voice_id,
            }
        )
        health = await ADAPTER.check_health()
        await session.emit(
            "adapter_session_ready",
            "adapter",
            {
                "runtime_session_handle": session.runtime_session_handle,
                "adapter_kind": ADAPTER.adapter_kind,
                "adapter_health": health.status,
            },
        )


def clear_turn_state(session: Session) -> None:
    session.current_turn_handle = None
    session.current_turn_task = None


async def emit_turn_state(session: Session, state: str, reason: str | None = None) -> None:
    payload = {"type": "turn_state", "state": state}
    if reason:
        payload["reason"] = reason
    await safe_send_str(session, payload)


def apply_voice_selection(session: Session, requested_voice_id: str | None) -> dict:
    session.requested_voice_id = requested_voice_id or TTS.default_voice_id
    fallback_reason = None
    sample_rate = None
    try:
        resolved_voice, fallback_reason = TTS.resolve_voice(session.requested_voice_id)
        session.voice_id = resolved_voice.voice_id
        sample_rate = resolved_voice.sample_rate
    except Exception:
        session.voice_id = None
    return {
        "requested_voice_id": session.requested_voice_id,
        "voice_id": session.voice_id,
        "speech_rate": session.speech_rate,
        "sample_rate": sample_rate,
        "available_voices": TTS.list_available_voices(),
        "fallback_reason": fallback_reason,
    }


def apply_speech_rate(session: Session, requested_speech_rate: float | int | str | None) -> float:
    try:
        value = float(requested_speech_rate) if requested_speech_rate is not None else DEFAULT_SPEECH_RATE
    except (TypeError, ValueError):
        value = DEFAULT_SPEECH_RATE
    session.speech_rate = max(0.85, min(1.30, value))
    return session.speech_rate


async def cancel_active_turn(session: Session, reason: str) -> None:
    if (
        session.runtime_session_handle is None
        or session.current_turn_handle is None
        or session.current_turn_task is None
        or session.current_turn_task.done()
    ):
        return

    await session.emit(
        "turn_cancel_requested",
        "adapter",
        {"turn_handle": session.current_turn_handle, "reason": reason},
    )
    try:
        result = await ADAPTER.cancel_turn(
            session.runtime_session_handle,
            session.current_turn_handle,
            {"reason": reason},
        )
        await session.emit(
            "turn_cancel_acknowledged",
            "adapter",
            {"turn_handle": session.current_turn_handle, "result": result},
        )
        await safe_send_str(session, {"type": "cancel_status", "result": result})
    except Exception as exc:
        await session.emit(
            "recoverable_error",
            "adapter",
            {"component": "cancel", "message": str(exc), "turn_handle": session.current_turn_handle},
        )


async def stream_assistant_turn(session: Session, transcript: str) -> None:
    await ensure_adapter_session(session)

    session.turn_id = str(uuid.uuid4())
    session.speech_generation = session.playback_generation
    await emit_turn_state(session, "active")
    await session.emit("turn_submit_started", "adapter", {"turn_id": session.turn_id, "transcript": transcript})
    turn_handle = await ADAPTER.submit_user_turn(
        session.runtime_session_handle,
        transcript,
        {"source": "transport_spike"},
    )
    session.current_turn_handle = turn_handle
    await session.emit("turn_submit_accepted", "adapter", {"turn_id": session.turn_id, "turn_handle": turn_handle})

    buffered = ""
    spoken_prefix = ""
    saw_final = False
    try:
        await session.emit("assistant_output_started", "adapter", {"turn_handle": turn_handle})
        async for event in ADAPTER.stream_assistant_output(session.runtime_session_handle, turn_handle):
            event_type = event["type"]
            if event_type == "assistant_text_delta":
                buffered += event["text"]
                await session.emit(
                    "assistant_output_delta",
                    "adapter",
                    {"turn_handle": turn_handle, "delta_chars": len(event["text"]), "buffered_chars": len(buffered)},
                )
                if not await safe_send_str(session, {"type": "assistant_text_delta", "text": event["text"]}):
                    return
                if not spoken_prefix:
                    candidate = buffered.strip()
                    if candidate and (candidate.endswith((".", "!", "?")) or len(candidate) >= 48):
                        spoken_prefix = buffered
                        enqueue_speech(session, candidate)
            elif event_type == "assistant_text_final":
                saw_final = True
                await session.emit(
                    "assistant_output_completed",
                    "adapter",
                    {"turn_handle": turn_handle, "final_chars": len(event["text"])},
                )
                if not await safe_send_str(session, {"type": "assistant_text_final", "text": event["text"]}):
                    return
                remaining = event["text"]
                if spoken_prefix and event["text"].startswith(spoken_prefix):
                    remaining = event["text"][len(spoken_prefix):]
                enqueue_speech(session, remaining.strip())
            elif event_type == "cancel_acknowledged":
                await session.emit("turn_cancel_acknowledged", "adapter", {"turn_handle": turn_handle})
                await safe_send_str(session, {"type": "cancel_status", "result": {"status": "acknowledged"}})
                return
            elif event_type == "turn_failed":
                await session.emit(
                    "recoverable_error",
                    "adapter",
                    {"component": "turn", "turn_handle": turn_handle, "message": event.get("message", "turn failed")},
                )
                await safe_send_str(session, {"type": "turn_failed", "message": event.get("message", "turn failed")})
                return
            elif event_type == "turn_completed":
                session.turns_completed += 1
                await session.emit("assistant_output_completed", "adapter", {"turn_handle": turn_handle, "completed_via": "turn_completed"})

        if not saw_final and buffered:
            await session.emit(
                "assistant_output_completed",
                "adapter",
                {"turn_handle": turn_handle, "final_chars": len(buffered), "completed_via": "buffer_flush"},
            )
            await safe_send_str(session, {"type": "assistant_text_final", "text": buffered})
            remaining = buffered
            if spoken_prefix and buffered.startswith(spoken_prefix):
                remaining = buffered[len(spoken_prefix):]
            enqueue_speech(session, remaining.strip())
    finally:
        await emit_turn_state(session, "idle")
        clear_turn_state(session)


async def start_assistant_turn(session: Session, transcript: str) -> None:
    if session.current_turn_task is not None and not session.current_turn_task.done():
        await session.emit(
            "recoverable_error",
            "gateway",
            {"component": "control", "message": "turn already active"},
        )
        await safe_send_str(session, {"type": "turn_rejected", "reason": "turn already active"})
        return

    session.current_turn_task = asyncio.create_task(stream_assistant_turn(session, transcript))


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024, heartbeat=30.0)
    await ws.prepare(request)

    session = Session(ws)
    await session.emit("session_created", "gateway", {})
    await session.emit("session_connected", "gateway", {})
    await session.emit("session_ready", "gateway", {"sample_rate": TARGET_SAMPLE_RATE})

    try:
      async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            payload = json.loads(msg.data)
            message_type = payload.get("type")

            if message_type == "session_init":
                session.client_name = payload.get("client_name") or session.client_name
                session.client_session_id = payload.get("client_session_id") or session.client_session_id
                apply_speech_rate(session, payload.get("speech_rate"))
                voice_details = apply_voice_selection(session, payload.get("voice_id"))
                await session.emit(
                    "session_ready",
                    "gateway",
                    {
                        "client_name": session.client_name,
                        "client_session_id": session.client_session_id,
                        **voice_details,
                    },
                )
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "session_ready",
                            "session_id": session.session_id,
                            "client_session_id": session.client_session_id,
                            "adapter_kind": ADAPTER.adapter_kind,
                            "adapter_health": LAST_ADAPTER_HEALTH["status"],
                            "adapter_detail": LAST_ADAPTER_HEALTH["detail"],
                            **voice_details,
                        }
                    )
                )
                asyncio.create_task(refresh_adapter_health(session))
            elif message_type == "session_update":
                apply_speech_rate(session, payload.get("speech_rate"))
                voice_details = apply_voice_selection(session, payload.get("voice_id"))
                await session.emit("session_updated", "gateway", voice_details)
                await ws.send_str(json.dumps({"type": "session_updated", **voice_details}))
            elif message_type == "mic_stream_started":
                await session.emit(
                    "mic_stream_started",
                    "browser",
                    {"sample_rate": payload.get("sample_rate", TARGET_SAMPLE_RATE)},
                )
            elif message_type == "mic_stream_stopped":
                await session.emit("mic_stream_stopped", "browser", {})
            elif message_type == "request_tone":
                await session.emit("assistant_output_started", "gateway", {"kind": "synthetic_tone"})
                await send_tone(session)
                await session.emit("assistant_output_completed", "gateway", {"kind": "synthetic_tone"})
            elif message_type == "clear_playback":
                session.playback_generation += 1
                session.speech_generation += 1
                await session.emit("playback_queue_cleared", "browser", {})
                await cancel_active_turn(session, "playback_cleared")
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "playback_cleared",
                            "generation": session.playback_generation,
                        }
                    )
                )
            elif message_type in {"submit_mock_turn", "submit_turn"}:
                transcript = payload.get("text", "").strip()
                if not transcript:
                    await session.emit("recoverable_error", "gateway", {"component": "control", "message": "empty mock turn"})
                else:
                    await start_assistant_turn(session, transcript)
            elif message_type == "transcribe_recent_audio":
                await session.emit(
                    "transcription_requested",
                    "browser",
                    {
                        "available_samples": len(session.recent_pcm),
                        "engine": STT.kind if STT.available else "fallback",
                        "submit_turn": bool(payload.get("submit_turn")),
                    },
                )
                if not session.recent_pcm:
                    await session.websocket.send_str(json.dumps({"type": "transcript_result", "text": "", "engine": "none"}))
                elif STT.available:
                    try:
                        text = await STT.transcribe(session.recent_pcm, TARGET_SAMPLE_RATE)
                        await session.emit(
                            "final_transcript_ready",
                            "speech",
                            {"char_count": len(text), "engine": STT.kind},
                        )
                        await session.websocket.send_str(
                            json.dumps({"type": "transcript_result", "text": text, "engine": STT.kind})
                        )
                        if payload.get("submit_turn") and text.strip():
                            await start_assistant_turn(session, text.strip())
                        session.recent_pcm.clear()
                    except Exception as exc:
                        await session.emit(
                            "recoverable_error",
                            "speech",
                            {"component": "stt", "message": str(exc), "engine": STT.kind},
                        )
                        await session.websocket.send_str(
                            json.dumps({"type": "transcript_result", "text": "", "engine": STT.kind, "error": str(exc)})
                        )
                else:
                    fallback = f"[stt unavailable] captured {len(session.recent_pcm)} samples"
                    await session.emit(
                        "final_transcript_ready",
                        "speech",
                        {"char_count": len(fallback), "engine": "fallback"},
                    )
                    await session.websocket.send_str(
                        json.dumps({"type": "transcript_result", "text": fallback, "engine": "fallback"})
                    )
                    session.recent_pcm.clear()
            elif message_type == "endpoint_candidate":
                await session.emit(
                    "endpoint_timer_started",
                    "browser",
                    {"silence_ms": payload.get("silence_ms")},
                )
            elif message_type == "vad_state":
                session.last_vad_state = payload.get("state", "unknown")
                event_name = "speech_start_detected" if session.last_vad_state == "speech" else "speech_end_detected"
                await session.emit(
                    event_name,
                    "browser",
                    {"state": session.last_vad_state, "rms": payload.get("rms")},
                )
            else:
                await session.emit("recoverable_error", "gateway", {"component": "control", "message": f"unknown control {message_type}"})

        elif msg.type == WSMsgType.BINARY:
            if not msg.data:
                continue
            kind = msg.data[0]
            if kind != PCM_KIND:
                await session.emit("recoverable_error", "gateway", {"component": "transport", "message": f"unknown binary kind {kind}"})
                continue

            session.frames_in += 1
            samples = (len(msg.data) - 1) // 2
            for i in range(1, len(msg.data), 2):
                session.recent_pcm.append(int.from_bytes(msg.data[i:i + 2], "little", signed=True))
            if len(session.recent_pcm) > session.recent_pcm_limit:
                session.recent_pcm = session.recent_pcm[-session.recent_pcm_limit:]
            await session.emit(
                "input_audio_frame_received",
                "gateway",
                {
                    "frame_index": session.frames_in,
                    "frame_bytes": len(msg.data),
                    "frame_samples": samples,
                    "sample_rate": TARGET_SAMPLE_RATE,
                },
            )

        elif msg.type == WSMsgType.ERROR:
            await session.emit("terminal_error", "gateway", {"message": str(ws.exception())})

    finally:
        await cancel_active_turn(session, "socket_disconnected")
        if session.current_turn_task is not None and not session.current_turn_task.done():
            session.current_turn_task.cancel()
        close_payload = {
            "close_code": ws.close_code,
            "exception": str(ws.exception()) if ws.exception() else "",
            "session_duration_ms": round((time.monotonic() * 1000) - session.started_monotonic_ms, 3),
        }
        await session.emit("socket_disconnected", "gateway", close_payload)
        await session.emit(
            "session_closed",
            "gateway",
            {
                **close_payload,
                "frames_in": session.frames_in,
                "frames_out": session.frames_out,
                "turns_completed": session.turns_completed,
                "playback_generation": session.playback_generation,
            },
        )

    return ws


async def index_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/setup/index.html")


async def setup_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/setup/index.html")


async def spike_handler(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/spike/index.html")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/api/backends", api_backends_handler)
    app.router.add_get("/api/status", api_status_handler)
    app.router.add_post("/api/configure", api_configure_handler)
    app.router.add_post("/api/test-url", api_test_url_handler)
    app.router.add_get("/setup", setup_handler)
    app.router.add_static("/setup", CLIENT_SETUP_DIR, show_index=True)
    app.router.add_get("/spike", spike_handler)
    app.router.add_static("/spike", CLIENT_SPIKE_DIR, show_index=True)
    app.router.add_static("/identity", IDENTITY_DIR, show_index=False)
    app.on_cleanup.append(_cleanup_bridge)
    return app


def create_ssl_context() -> ssl.SSLContext | None:
    if not TLS_CERT_FILE or not TLS_KEY_FILE:
        return None

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(TLS_CERT_FILE, TLS_KEY_FILE)
    return context


if __name__ == "__main__":
    web.run_app(
        create_app(),
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        ssl_context=create_ssl_context(),
    )
