"""Environment check for Qantara.

Run: python3 scripts/doctor.py (or `make doctor`)

Verifies the local environment can run Qantara and reports pass/warn/fail for
each check. Does not install anything. Exit code 0 if all critical checks pass.
"""

from __future__ import annotations

import platform
import shutil
import socket
import sys
from pathlib import Path

OK = "\033[32mok\033[0m"
WARN = "\033[33mwarn\033[0m"
FAIL = "\033[31mfail\033[0m"


def row(status: str, name: str, detail: str = "") -> None:
    print(f"  [{status}] {name}{(' — ' + detail) if detail else ''}")


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 11):
        row(OK, "Python", f"{platform.python_version()}")
        return True
    row(FAIL, "Python", f"{platform.python_version()} — need 3.11 or newer")
    return False


def check_aiohttp() -> bool:
    try:
        import aiohttp  # noqa: F401

        row(OK, "aiohttp", aiohttp.__version__)
        return True
    except ImportError:
        row(FAIL, "aiohttp", "not installed — run: make spike-install")
        return False


def check_port(port: int = 8765) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        if result != 0:
            row(OK, f"Port {port} free")
            return True
        row(WARN, f"Port {port}", "in use — set QANTARA_SPIKE_PORT to override")
        return True


def check_docker() -> bool:
    if shutil.which("docker") is None:
        row(WARN, "Docker", "not found — optional, used only for `docker compose up`")
        return True
    row(OK, "Docker", "available")
    return True


def check_optional_backend_bin(name: str, label: str) -> bool:
    if shutil.which(name) is None:
        row(WARN, label, f"`{name}` not on PATH — optional for this backend")
        return True
    row(OK, label, "available")
    return True


def check_models_dir() -> bool:
    repo_root = Path(__file__).resolve().parent.parent
    models_piper = repo_root / "models" / "piper"
    if models_piper.exists() and any(models_piper.iterdir()):
        row(OK, "Piper voices", f"{sum(1 for _ in models_piper.glob('*.onnx'))} voice(s) found")
        return True
    row(WARN, "Piper voices", "no .onnx files in models/piper — Piper voices will be unavailable")
    return True


def check_tls_env() -> bool:
    import os

    cert = os.environ.get("QANTARA_TLS_CERT")
    key = os.environ.get("QANTARA_TLS_KEY")
    if cert and key:
        if Path(cert).is_file() and Path(key).is_file():
            row(OK, "TLS", "cert + key present")
        else:
            row(WARN, "TLS", "env vars set but files not found")
    else:
        row(OK, "TLS", "loopback (default) — set QANTARA_TLS_CERT/KEY for LAN")
    return True


def cmd_default() -> int:
    print("Qantara doctor\n--------------")
    checks = [
        check_python(),
        check_aiohttp(),
        check_port(8765),
        check_docker(),
        check_optional_backend_bin("ollama", "Ollama CLI"),
        check_optional_backend_bin("openclaw", "OpenClaw CLI"),
        check_models_dir(),
        check_tls_env(),
    ]
    critical_ok = checks[0] and checks[1]
    print("--------------")
    print("ready" if critical_ok else "not ready — fix fail items above")
    return 0 if critical_ok else 1


def cmd_mesh() -> int:
    import argparse as _  # noqa: F401
    import json
    import os
    import time
    import urllib.request

    port = os.environ.get("QANTARA_SPIKE_PORT", "8765")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/mesh/status", timeout=2) as resp:
            status = json.loads(resp.read())
    except Exception as exc:
        print(f"mesh: cannot reach gateway on :{port} — {exc}")
        return 2
    if not status.get("enabled"):
        print("mesh: disabled (set QANTARA_MESH_ROLE to enable)")
        return 0
    print(f"mesh: enabled (role={status['role']}, node_id={status['node_id']})")
    print(f"  mesh_port: {status['mesh_port']}  service_type: {status['service_type']}")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/mesh/peers", timeout=2) as resp:
        peers_payload = json.loads(resp.read())
    peers = peers_payload.get("peers", [])
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh", action="store_true")
    args = parser.parse_args()
    if args.mesh:
        sys.exit(cmd_mesh())
    sys.exit(cmd_default())
