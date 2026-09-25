"""Environment check for Qantara.

Run: ``qantara doctor`` / ``qantara-doctor`` (installed), or from a source
checkout ``python scripts/doctor.py`` / ``make doctor``. Add ``--mesh`` to
inspect a running gateway's mesh peers (``make doctor ARGS=--mesh``).

Reports pass/warn/fail for each check. Does not install or download anything
and does not import heavy speech libraries. Exit code 0 when every critical
check passes.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import ipaddress
import os
import platform
import shutil
import socket
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
MAX_GATEWAY_RESPONSE_BYTES = 1024 * 1024
MIN_AIOHTTP = (3, 14)
KOKORO_MAX_PYTHON = (3, 12)  # every kokoro release declares Requires-Python <3.13
MIN_AUTH_TOKEN_LENGTH = 24  # mirrors gateway/transport_spike/auth.py
CPU_TORCH_HINT = "pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cpu"


def _color(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


OK = _color("32", "ok")
WARN = _color("33", "warn")
FAIL = _color("31", "fail")


def row(status: str, name: str, detail: str = "") -> None:
    print(f"  [{status}] {name}{(' — ' + detail) if detail else ''}")


def _version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in text.split("+", 1)[0].split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _dist_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Checks. Each returns False only for a critical failure.
# ---------------------------------------------------------------------------


def check_python() -> bool:
    current = sys.version_info[:2]
    if current < (3, 11):
        row(FAIL, "Python", f"{platform.python_version()} — need 3.11 or newer")
        return False
    if current > KOKORO_MAX_PYTHON:
        row(
            WARN,
            "Python",
            f"{platform.python_version()} — Kokoro TTS needs Python 3.11 or 3.12; "
            "use `python3.12 -m venv .venv` for Kokoro, or Piper TTS on this interpreter",
        )
        return True
    row(OK, "Python", platform.python_version())
    return True


def check_aiohttp() -> bool:
    version = _dist_version("aiohttp")
    if version is None:
        row(FAIL, "aiohttp", 'not installed — run: pip install -e .  (or pip install "qantara[speech]")')
        return False
    if _version_tuple(version) < MIN_AIOHTTP:
        wanted = ".".join(map(str, MIN_AIOHTTP))
        row(FAIL, "aiohttp", f"{version} — Qantara requires aiohttp>={wanted},<4")
        return False
    row(OK, "aiohttp", version)
    return True


def _port() -> tuple[int | None, str]:
    raw = os.environ.get("QANTARA_SPIKE_PORT", "").strip() or "8765"
    try:
        value = int(raw, 10)
    except ValueError:
        return None, f"QANTARA_SPIKE_PORT must be an integer, got {raw!r}"
    if not 0 < value < 65536:
        return None, f"QANTARA_SPIKE_PORT must be between 1 and 65535, got {value}"
    return value, ""


def check_port() -> bool:
    port, error = _port()
    if port is None:
        row(FAIL, "Gateway port", error)
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", port)) != 0:
            row(OK, f"Port {port} free")
        else:
            row(WARN, f"Port {port}", "in use — set QANTARA_SPIKE_PORT or --port to override")
    return True


def check_stt() -> bool:
    kind = os.environ.get("QANTARA_STT_PROVIDER", "").strip().lower() or "faster_whisper"
    if kind not in {"faster_whisper", "faster-whisper", "whisper"}:
        row(FAIL, "STT provider", f"unsupported QANTARA_STT_PROVIDER={kind!r}")
        return False
    if _has_module("faster_whisper"):
        model = os.environ.get("QANTARA_WHISPER_MODEL", "").strip() or "default model"
        row(OK, "STT faster-whisper", f"importable ({model}; downloads on first use)")
    else:
        row(WARN, "STT faster-whisper", 'not installed — pip install -e ".[speech]"; voice input is disabled')
    return True


def _check_piper(selected: bool) -> bool:
    status_if_missing = FAIL if selected else WARN
    if not _has_module("piper"):
        row(status_if_missing, "TTS piper", "piper-tts is not installed in this environment (pip install piper-tts)")
        return not selected
    voice_env = os.environ.get("QANTARA_PIPER_MODEL", "").strip()
    voices_dir = PACKAGE_ROOT / "models" / "piper"
    count = sum(1 for _ in voices_dir.glob("*.onnx")) if voices_dir.is_dir() else 0
    if voice_env and Path(voice_env).is_file():
        row(OK, "TTS piper", f"importable; QANTARA_PIPER_MODEL voice present (+{count} in models/piper)")
    elif count:
        row(OK, "TTS piper", f"importable; {count} voice(s) in models/piper")
    else:
        row(
            status_if_missing,
            "TTS piper",
            "importable but no voices — run scripts/fetch_piper_voices.sh or set QANTARA_PIPER_MODEL",
        )
        return not selected
    return True


def _check_kokoro(selected: bool) -> bool:
    status_if_missing = FAIL if selected else WARN
    if sys.version_info[:2] > KOKORO_MAX_PYTHON:
        row(status_if_missing, "TTS kokoro", f"unavailable on Python {platform.python_version()} (needs 3.11/3.12)")
        return not selected
    if not _has_module("kokoro"):
        row(status_if_missing, "TTS kokoro", 'not installed — pip install -e ".[speech]"')
        return not selected
    voice = os.environ.get("QANTARA_KOKORO_VOICE", "af_heart")
    row(OK, "TTS kokoro", f"importable (voice {voice}; model downloads on first use)")
    return True


def check_tts() -> bool:
    kind = os.environ.get("QANTARA_TTS_PROVIDER", "").strip().lower()
    if kind == "piper":
        return _check_piper(selected=True)
    if kind == "kokoro":
        return _check_kokoro(selected=True)
    if kind == "chatterbox":
        if _has_module("chatterbox"):
            row(OK, "TTS chatterbox", "importable")
            return True
        row(FAIL, "TTS chatterbox", 'not installed — pip install -e ".[chatterbox]"')
        return False
    if kind:
        row(FAIL, "TTS provider", f"unsupported QANTARA_TTS_PROVIDER={kind!r}")
        return False
    # Unset: report both engines so the operator can choose one explicitly.
    piper_ok = _check_piper(selected=False)
    kokoro_ok = _check_kokoro(selected=False)
    if not (_has_module("piper") or (_has_module("kokoro") and sys.version_info[:2] <= KOKORO_MAX_PYTHON)):
        row(WARN, "TTS", "no speech engine importable — replies will not be spoken")
    return piper_ok and kokoro_ok


def check_torch() -> bool:
    version = _dist_version("torch")
    if version is None:
        return True
    if sys.platform == "darwin" or "+cpu" in version:
        row(OK, "PyTorch", f"{version} (CPU build)" if "+cpu" in version else version)
        return True
    cuda_packages = sorted(
        {
            (dist.metadata["Name"] or "")
            for dist in importlib.metadata.distributions()
            if (dist.metadata["Name"] or "").lower().startswith("nvidia-")
        }
    )
    if cuda_packages or "+cu" in version:
        row(
            WARN,
            "PyTorch",
            f"{version} is a CUDA build ({len(cuda_packages)} nvidia-* packages, several GB). "
            f"On CPU-only machines reinstall the CPU build: {CPU_TORCH_HINT}",
        )
    else:
        row(OK, "PyTorch", version)
    return True


def _is_loopback(host: str) -> bool:
    value = host.strip().strip("[]").lower()
    if value in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def check_exposure() -> bool:
    host = os.environ.get("QANTARA_SPIKE_HOST", "").strip() or "127.0.0.1"
    cert = os.environ.get("QANTARA_TLS_CERT", "").strip()
    key = os.environ.get("QANTARA_TLS_KEY", "").strip()
    token = os.environ.get("QANTARA_AUTH_TOKEN", "").strip()
    ok = True

    if cert or key:
        if cert and key and Path(cert).is_file() and Path(key).is_file():
            row(OK, "TLS", "certificate and key files present")
        else:
            row(FAIL, "TLS", "QANTARA_TLS_CERT and QANTARA_TLS_KEY must both point to existing files")
            ok = False

    if _is_loopback(host):
        row(OK, "Bind", f"{host} (loopback only)")
        if token and len(token) < MIN_AUTH_TOKEN_LENGTH:
            row(FAIL, "Auth token", f"QANTARA_AUTH_TOKEN must be at least {MIN_AUTH_TOKEN_LENGTH} characters")
            ok = False
        return ok

    if not token:
        row(
            FAIL,
            "Auth token",
            f"binding {host} exposes the gateway beyond loopback; set QANTARA_AUTH_TOKEN "
            f"(>= {MIN_AUTH_TOKEN_LENGTH} chars) — non-loopback requests are refused without it",
        )
        ok = False
    elif len(token) < MIN_AUTH_TOKEN_LENGTH:
        row(FAIL, "Auth token", f"QANTARA_AUTH_TOKEN must be at least {MIN_AUTH_TOKEN_LENGTH} characters")
        ok = False
    else:
        row(OK, "Auth token", "set for non-loopback bind")
    if not (cert and key):
        row(
            WARN,
            "TLS",
            f"binding {host} without QANTARA_TLS_CERT/KEY — browsers block the microphone on plain "
            "HTTP from other devices; terminate TLS here or in a reverse proxy (ops/Caddyfile)",
        )
    return ok


def check_optional_bin(name: str, label: str, purpose: str) -> bool:
    if shutil.which(name) is None:
        row(WARN, label, f"`{name}` not on PATH — optional, {purpose}")
    else:
        row(OK, label, "available")
    return True


def cmd_default() -> int:
    print("Qantara doctor\n--------------")
    critical = [
        check_python(),
        check_aiohttp(),
        check_port(),
        check_stt(),
        check_tts(),
        check_torch(),
        check_exposure(),
    ]
    check_optional_bin("docker", "Docker", "used only for `docker compose up`")
    check_optional_bin("ollama", "Ollama CLI", "needed for --backend ollama on this machine")
    check_optional_bin("openclaw", "OpenClaw CLI", "needed for --backend openclaw")
    ready = all(critical)
    print("--------------")
    print("ready" if ready else "not ready — fix fail items above")
    return 0 if ready else 1


def cmd_mesh() -> int:
    import json
    import time
    import urllib.request

    class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    def read_json_response(response):
        body = response.read(MAX_GATEWAY_RESPONSE_BYTES + 1)
        if len(body) > MAX_GATEWAY_RESPONSE_BYTES:
            raise RuntimeError("gateway response exceeded the configured limit")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise RuntimeError("gateway returned a non-object JSON response")
        return data

    port, error = _port()
    if port is None:
        print(f"mesh: {error}")
        return 2
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )
    token = os.environ.get("QANTARA_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def fetch(path: str) -> dict:
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
        with opener.open(request, timeout=2) as resp:
            return read_json_response(resp)

    try:
        status = fetch("/api/mesh/status")
    except Exception as exc:
        print(f"mesh: cannot reach gateway on :{port} — {exc}")
        return 2
    if not status.get("enabled"):
        print("mesh: disabled (set QANTARA_MESH_ROLE to enable)")
        return 0
    print(f"mesh: enabled (role={status['role']}, node_id={status['node_id']})")
    print(f"  mesh_port: {status['mesh_port']}  service_type: {status['service_type']}")
    peers = fetch("/api/mesh/peers").get("peers", [])
    if not peers:
        print("  peers: none")
        return 0
    print(f"  peers: {len(peers)}")
    for p in peers:
        try:
            t = time.monotonic()
            sock = socket.create_connection((p["host"], p["port"]), timeout=1.0)
            sock.close()
            latency_ms = (time.monotonic() - t) * 1000
            print(f"    {p['node_id']:20s} {p['host']}:{p['port']}  role={p['role']}  rtt={latency_ms:.1f}ms")
        except Exception as exc:
            print(f"    {p['node_id']:20s} {p['host']}:{p['port']}  role={p['role']}  UNREACHABLE ({exc})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qantara doctor", description="Check the local Qantara environment.")
    parser.add_argument("--mesh", action="store_true", help="inspect a running gateway's mesh status and peers")
    args = parser.parse_args(argv)
    return cmd_mesh() if args.mesh else cmd_default()


if __name__ == "__main__":
    raise SystemExit(main())
