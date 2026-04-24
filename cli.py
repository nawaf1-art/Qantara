"""Qantara CLI — single-command launcher for the voice gateway.

Usage examples:
    python cli.py --backend mock
    python cli.py --backend ollama
    python cli.py --backend ollama --model qwen2.5:7b
    python cli.py --backend openclaw --agent main
    python cli.py --backend http://my-service:8080

Falls back to QANTARA_* env vars when no flags are provided.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time

from config import load_config

# ---------------------------------------------------------------------------
# Resolve repo root so imports work when invoked as `python cli.py`
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# ---------------------------------------------------------------------------
# Bridge script paths (relative to repo root)
# ---------------------------------------------------------------------------
_BRIDGE_SCRIPTS: dict[str, str] = {
    "ollama": os.path.join(REPO_ROOT, "gateway", "ollama_session_backend", "server.py"),
    "openclaw": os.path.join(REPO_ROOT, "gateway", "openclaw_session_backend", "server.py"),
}

MANAGED_BRIDGE_PORT = 19120


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qantara",
        description="Start the Qantara voice gateway with a single command.",
    )
    parser.add_argument(
        "--backend",
        default=None,
        help=(
            "Backend to use: mock, ollama, openclaw, or an HTTP URL. "
            "Falls back to QANTARA_BACKEND env var, then config file."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name for Ollama backend (e.g. qwen2.5:7b).",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Agent ID for the advanced OpenClaw bridge (e.g. main).",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host for the gateway server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for the gateway server.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to qantara.yml config file.",
    )
    return parser


def _apply_config_defaults(args: argparse.Namespace) -> None:
    """Fill in missing args from env vars, then config file, then defaults.

    Precedence (highest wins): env vars > CLI flags > config file > defaults.
    CLI flags are already in args (None if not provided).
    """
    # Load config file (uses QANTARA_CONFIG env var or repo-root qantara.yml)
    config_path = args.config or None
    cfg = load_config(config_path)

    # For each arg: env var wins, then CLI flag, then config file, then default.
    # args.<field> is None when the user didn't pass the flag.

    if args.backend is None:
        env_val = os.environ.get("QANTARA_BACKEND", "")
        if env_val:
            args.backend = env_val
        elif cfg["backend"]["type"]:
            args.backend = cfg["backend"]["type"]
        else:
            args.backend = ""
    else:
        # CLI flag was given — but env var still wins
        env_val = os.environ.get("QANTARA_BACKEND", "")
        if env_val:
            args.backend = env_val

    if args.model is None:
        env_val = os.environ.get("QANTARA_OLLAMA_MODEL", "")
        if env_val:
            args.model = env_val
        elif cfg["backend"]["model"]:
            args.model = cfg["backend"]["model"]
        else:
            args.model = ""
    else:
        env_val = os.environ.get("QANTARA_OLLAMA_MODEL", "")
        if env_val:
            args.model = env_val

    if args.agent is None:
        env_val = os.environ.get("QANTARA_OPENCLAW_AGENT_ID", "")
        if env_val:
            args.agent = env_val
        elif cfg["backend"]["agent"]:
            args.agent = cfg["backend"]["agent"]
        else:
            args.agent = ""
    else:
        env_val = os.environ.get("QANTARA_OPENCLAW_AGENT_ID", "")
        if env_val:
            args.agent = env_val

    if args.host is None:
        env_val = os.environ.get("QANTARA_SPIKE_HOST", "")
        if env_val:
            args.host = env_val
        elif cfg["server"]["host"]:
            args.host = cfg["server"]["host"]
        else:
            args.host = "127.0.0.1"
    else:
        env_val = os.environ.get("QANTARA_SPIKE_HOST", "")
        if env_val:
            args.host = env_val

    if args.port is None:
        env_val = os.environ.get("QANTARA_SPIKE_PORT", "")
        if env_val:
            args.port = int(env_val)
        elif cfg["server"]["port"]:
            args.port = int(cfg["server"]["port"])
        else:
            args.port = 8765
    else:
        env_val = os.environ.get("QANTARA_SPIKE_PORT", "")
        if env_val:
            args.port = int(env_val)

    # Propagate STT/TTS config values into env vars if not already set
    if cfg["voice"]["stt"] and not os.environ.get("QANTARA_STT_PROVIDER"):
        os.environ["QANTARA_STT_PROVIDER"] = cfg["voice"]["stt"]
    if cfg["voice"]["tts"] and not os.environ.get("QANTARA_TTS_PROVIDER"):
        os.environ["QANTARA_TTS_PROVIDER"] = cfg["voice"]["tts"]

    # Propagate backend URL from config if not set via env or CLI
    if cfg["backend"]["url"] and not os.environ.get("QANTARA_BACKEND_BASE_URL"):
        # Store for later use by _apply_env — only used when backend type matches
        args._config_backend_url = cfg["backend"]["url"]
    else:
        args._config_backend_url = ""


# ---------------------------------------------------------------------------
# Backend classification
# ---------------------------------------------------------------------------
def _classify_backend(backend: str) -> tuple[str, str]:
    """Return (backend_type, url) from the --backend value.

    backend_type is one of: mock, ollama, openclaw, openai_compatible, custom.
    url is the backend URL (empty for mock, ollama, openclaw unless overridden).
    """
    value = backend.strip()
    lower = value.lower()

    if not lower or lower == "mock":
        return "mock", ""
    if lower == "ollama":
        return "ollama", ""
    if lower == "openclaw":
        return "openclaw", ""
    if lower in ("openai", "openai_compatible", "openai-compatible"):
        return "openai_compatible", ""
    if lower.startswith("http://") or lower.startswith("https://"):
        # HTTP URLs → OpenAI-compatible adapter (most common use case)
        return "openai_compatible", value.rstrip("/")

    # Unrecognised — treat as literal and let the user know
    print(f"[qantara] warning: unrecognised backend '{value}', treating as custom URL", flush=True)
    return "custom", value


# ---------------------------------------------------------------------------
# Environment setup — sets env vars before gateway module is imported
# ---------------------------------------------------------------------------
def _apply_env(backend_type: str, url: str, args: argparse.Namespace) -> None:
    """Set QANTARA_* environment variables so the gateway picks up the config."""

    if backend_type == "mock":
        os.environ["QANTARA_ADAPTER"] = "mock"

    elif backend_type == "ollama":
        os.environ["QANTARA_ADAPTER"] = "session_gateway_http"
        if not os.environ.get("QANTARA_BACKEND_BASE_URL"):
            os.environ["QANTARA_BACKEND_BASE_URL"] = f"http://127.0.0.1:{MANAGED_BRIDGE_PORT}"
        if args.model:
            os.environ.setdefault("QANTARA_OLLAMA_MODEL", args.model)
        # Propagate config backend.url as the Ollama upstream URL for the bridge.
        # Env var QANTARA_OLLAMA_BASE_URL still wins if already set.
        if not os.environ.get("QANTARA_OLLAMA_BASE_URL"):
            config_url = getattr(args, "_config_backend_url", "")
            if config_url:
                os.environ["QANTARA_OLLAMA_BASE_URL"] = config_url

    elif backend_type == "openclaw":
        os.environ["QANTARA_ADAPTER"] = "session_gateway_http"
        if not os.environ.get("QANTARA_BACKEND_BASE_URL"):
            os.environ["QANTARA_BACKEND_BASE_URL"] = f"http://127.0.0.1:{MANAGED_BRIDGE_PORT}"
        if args.agent:
            os.environ.setdefault("QANTARA_OPENCLAW_AGENT_ID", args.agent)

    elif backend_type == "custom":
        os.environ["QANTARA_ADAPTER"] = "session_gateway_http"
        if not os.environ.get("QANTARA_BACKEND_BASE_URL"):
            config_url = getattr(args, "_config_backend_url", "")
            os.environ["QANTARA_BACKEND_BASE_URL"] = url or config_url

    # Gateway host/port
    os.environ["QANTARA_SPIKE_HOST"] = args.host
    os.environ["QANTARA_SPIKE_PORT"] = str(args.port)


# ---------------------------------------------------------------------------
# Bridge subprocess management
# ---------------------------------------------------------------------------
_bridge_proc: asyncio.subprocess.Process | None = None


async def _start_bridge(backend_type: str, args: argparse.Namespace) -> None:
    """Start the appropriate bridge subprocess for ollama/openclaw."""
    global _bridge_proc

    script = _BRIDGE_SCRIPTS.get(backend_type)
    if script is None or not os.path.isfile(script):
        print(f"[qantara] error: bridge script not found for '{backend_type}'", flush=True)
        sys.exit(1)

    env = os.environ.copy()
    env["QANTARA_REAL_BACKEND_PORT"] = str(MANAGED_BRIDGE_PORT)
    env["QANTARA_REAL_BACKEND_HOST"] = "127.0.0.1"
    if backend_type == "ollama" and args.model:
        env["QANTARA_OLLAMA_MODEL"] = args.model
    if backend_type == "openclaw" and args.agent:
        env["QANTARA_OPENCLAW_AGENT_ID"] = args.agent

    print(f"[qantara] starting {backend_type} bridge on port {MANAGED_BRIDGE_PORT}...", flush=True)
    _bridge_proc = await asyncio.create_subprocess_exec(
        sys.executable, script,
        env=env,
        stdout=None,  # inherit parent stdout so bridge logs are visible
        stderr=None,  # inherit parent stderr
    )


async def _wait_for_bridge(timeout: float = 8.0) -> bool:
    """Poll bridge health endpoint until ready or timeout."""
    import aiohttp

    url = f"http://127.0.0.1:{MANAGED_BRIDGE_PORT}/health"
    deadline = time.monotonic() + timeout
    client_timeout = aiohttp.ClientTimeout(total=2)
    while time.monotonic() < deadline:
        try:
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url) as resp:
                    if resp.status < 500:
                        return True
        except Exception:
            pass
        await asyncio.sleep(0.4)
    return False


async def _stop_bridge() -> None:
    """Gracefully stop the bridge subprocess."""
    global _bridge_proc
    if _bridge_proc is None:
        return
    try:
        _bridge_proc.terminate()
        try:
            await asyncio.wait_for(_bridge_proc.wait(), timeout=5)
        except TimeoutError:
            _bridge_proc.kill()
            await _bridge_proc.wait()
    except ProcessLookupError:
        pass
    _bridge_proc = None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def _run(args: argparse.Namespace) -> None:
    backend_type, url = _classify_backend(args.backend)

    # Apply env vars before importing the gateway module (it reads env at import time)
    _apply_env(backend_type, url, args)

    # Start bridge subprocess if needed
    if backend_type in ("ollama", "openclaw"):
        await _start_bridge(backend_type, args)
        ready = await _wait_for_bridge()
        if not ready:
            print(f"[qantara] warning: {backend_type} bridge did not become healthy in time", flush=True)
            print("[qantara] continuing anyway — the bridge may still be loading...", flush=True)

    # Now import the gateway — it reads QANTARA_* env vars at module level
    from gateway.transport_spike.server import create_app, create_ssl_context

    label = backend_type
    if backend_type == "ollama" and args.model:
        label = f"ollama ({args.model})"
    elif backend_type == "openclaw" and args.agent:
        label = f"openclaw ({args.agent})"
    elif backend_type == "custom":
        label = f"custom ({url})"

    print(f"[qantara] backend: {label}", flush=True)
    print(f"[qantara] gateway: http://{args.host}:{args.port}", flush=True)

    from aiohttp import web

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port, ssl_context=create_ssl_context())
    await site.start()

    # Wait until cancelled (SIGINT/SIGTERM)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()

    print("\n[qantara] shutting down...", flush=True)
    await runner.cleanup()
    await _stop_bridge()
    print("[qantara] stopped.", flush=True)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Merge: env vars > CLI flags > config file > defaults
    _apply_config_defaults(args)

    if not args.backend:
        args.backend = "mock"

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
