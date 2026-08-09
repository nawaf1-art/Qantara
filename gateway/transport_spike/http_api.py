from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import socket as _sock
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import aiohttp as _aiohttp
from aiohttp import web

from gateway.transport_spike.auth import (
    ADMIN_TOKEN_KEY,
    AUTH_TOKEN_KEY,
    api_auth_login_handler,
    api_auth_logout_handler,
    api_auth_status_handler,
    has_valid_auth_token,
    require_bearer_token,
)
from gateway.transport_spike.common import CLIENT_SETUP_DIR, CLIENT_SPIKE_DIR, CLIENT_TRANSLATE_DIR, IDENTITY_DIR
from gateway.transport_spike.runtime import APP_RUNTIME_KEY, GatewayRuntime
from gateway.transport_spike.voice_api import mount_voice_api
from qantara.http_safety import (
    read_bounded_response_bytes,
    read_bounded_response_json,
)
from qantara.security import bridge_subprocess_environment

_TEST_URL_RATE_LIMIT_WINDOW_S = 10.0
_TEST_URL_RATE_LIMIT_MAX_CALLS = 8
_TEST_URL_RATE_LIMIT_MAX_CLIENTS = 1024
MAX_CONFIGURATION_URL_CHARS = 2048
MAX_CONFIGURATION_IDENTIFIER_CHARS = 256
MAX_SETUP_PROBE_STDOUT_BYTES = 1024 * 1024
MAX_SETUP_PROBE_STDERR_BYTES = 256 * 1024
_test_url_call_log: dict[str, deque[float]] = {}


class SetupProbeOutputLimitError(RuntimeError):
    """Raised when a setup helper emits more output than Qantara will retain."""


@dataclass(frozen=True, slots=True)
class SafeOutboundURL:
    """A validated URL pinned to one address with its original authority."""

    url: str
    host_header: str
    server_hostname: str


def _check_test_url_rate_limit(client_ip: str) -> bool:
    now = time.monotonic()
    if len(_test_url_call_log) >= _TEST_URL_RATE_LIMIT_MAX_CLIENTS and client_ip not in _test_url_call_log:
        cutoff = now - _TEST_URL_RATE_LIMIT_WINDOW_S
        stale = [key for key, calls in _test_url_call_log.items() if not calls or calls[-1] < cutoff]
        for key in stale:
            _test_url_call_log.pop(key, None)
        while len(_test_url_call_log) >= _TEST_URL_RATE_LIMIT_MAX_CLIENTS:
            _test_url_call_log.pop(next(iter(_test_url_call_log)), None)
    log = _test_url_call_log.setdefault(client_ip, deque())
    cutoff = now - _TEST_URL_RATE_LIMIT_WINDOW_S
    while log and log[0] < cutoff:
        log.popleft()
    if len(log) >= _TEST_URL_RATE_LIMIT_MAX_CALLS:
        return False
    log.append(now)
    return True


async def cleanup_bridge(app: web.Application) -> None:
    runtime: GatewayRuntime = app[APP_RUNTIME_KEY]
    await runtime.close()


async def _communicate_with_timeout(
    proc: asyncio.subprocess.Process,
    timeout: float,
) -> tuple[bytes, bytes]:
    stdout_stream = getattr(proc, "stdout", None)
    stderr_stream = getattr(proc, "stderr", None)
    if stdout_stream is None or stderr_stream is None:
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.communicate()
            raise
        if len(stdout) > MAX_SETUP_PROBE_STDOUT_BYTES:
            raise SetupProbeOutputLimitError(
                "setup probe stdout exceeded the configured limit"
            )
        if len(stderr) > MAX_SETUP_PROBE_STDERR_BYTES:
            raise SetupProbeOutputLimitError(
                "setup probe stderr exceeded the configured limit"
            )
        return stdout, stderr

    async def read_stream(
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
                raise SetupProbeOutputLimitError(
                    f"setup probe {label} exceeded the configured limit"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    tasks = [
        asyncio.create_task(proc.wait()),
        asyncio.create_task(
            read_stream(
                stdout_stream,
                limit=MAX_SETUP_PROBE_STDOUT_BYTES,
                label="stdout",
            )
        ),
        asyncio.create_task(
            read_stream(
                stderr_stream,
                limit=MAX_SETUP_PROBE_STDERR_BYTES,
                label="stderr",
            )
        ),
    ]
    try:
        _, stdout, stderr = await asyncio.wait_for(
            asyncio.gather(*tasks),
            timeout=timeout,
        )
        return stdout, stderr
    except BaseException:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await proc.wait()
        raise


def ollama_base_url() -> str:
    return os.environ.get("QANTARA_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


async def probe_ollama() -> dict[str, Any]:
    try:
        timeout = _aiohttp.ClientTimeout(total=3)
        async with _aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(f"{ollama_base_url()}/api/tags", allow_redirects=False) as resp:
                if resp.status != 200:
                    return {"available": False}
                data = await read_bounded_response_json(resp)
                if not isinstance(data, dict):
                    return {"available": False}
                models = []
                for m in data.get("models", []):
                    if not isinstance(m, dict):
                        continue
                    name = m.get("name") or m.get("model") or ""
                    if name:
                        size_bytes = m.get("size", 0)
                        models.append({"name": name, "size_gb": round(size_bytes / (1024 ** 3), 1) if size_bytes else None, "family": m.get("details", {}).get("family", ""), "param_size": m.get("details", {}).get("parameter_size", "")})
                return {"available": True, "models": models}
    except Exception:
        return {"available": False}


async def probe_openclaw() -> dict[str, Any]:
    import shutil

    result: dict[str, Any] = {"available": False, "installed": False, "gateway_running": False, "agents": []}
    openclaw_bin = os.environ.get("QANTARA_OPENCLAW_BIN", "openclaw")
    if not shutil.which(openclaw_bin):
        return result
    result["installed"] = True
    try:
        proc = await asyncio.create_subprocess_exec(
            openclaw_bin,
            "health",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=bridge_subprocess_environment(),
        )
        stdout, _ = await _communicate_with_timeout(proc, 15)
        health = json.loads(stdout.decode("utf-8", errors="replace"))
        if not isinstance(health, dict) or not health.get("ok"):
            return result
        result["gateway_running"] = True
    except Exception:
        return result
    # Availability is a gateway-health signal, not an agent-list signal. On
    # installs with many running agents, `openclaw agents list --json` can
    # take 20-30s; we probe for it with a generous timeout but don't block
    # the setup page's "OpenClaw detected" badge on it.
    result["available"] = result["gateway_running"]
    agents_timeout = float(os.environ.get("QANTARA_OPENCLAW_AGENTS_TIMEOUT", "60"))
    try:
        proc = await asyncio.create_subprocess_exec(
            openclaw_bin,
            "agents",
            "list",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=bridge_subprocess_environment(),
        )
        stdout, _ = await _communicate_with_timeout(proc, agents_timeout)
        agents_data = json.loads(stdout.decode("utf-8", errors="replace"))
        if isinstance(agents_data, list):
            for a in agents_data:
                if not isinstance(a, dict):
                    continue
                agent_id = a.get("id", a.get("name", ""))
                if agent_id:
                    result["agents"].append({"id": agent_id, "name": a.get("identityName", agent_id), "default": a.get("isDefault", False)})
    except Exception:
        pass
    return result


async def probe_openai_port(host: str, port: int) -> dict[str, Any] | None:
    try:
        timeout = _aiohttp.ClientTimeout(total=2)
        async with _aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(
                f"http://{host}:{port}/v1/models", allow_redirects=False
            ) as resp:
                if resp.status >= 400:
                    return None
                data = await read_bounded_response_json(resp)
                if not isinstance(data, dict):
                    return None
                model_items = data.get("data", [])
                if not isinstance(model_items, list):
                    return None
                models = [
                    m.get("id", "")
                    for m in model_items
                    if isinstance(m, dict) and m.get("id")
                ]
                if models:
                    return {"port": port, "models": models, "url": f"http://{host}:{port}"}
    except Exception:
        pass
    return None


async def probe_openai_compatible() -> dict[str, Any]:
    results = await asyncio.gather(*[probe_openai_port("127.0.0.1", port) for port in [8080, 8000, 1337, 1234]])
    servers = [r for r in results if r is not None]
    return {"available": bool(servers), "servers": servers}


async def probe_mcp() -> dict[str, Any]:
    transport = os.environ.get("QANTARA_MCP_TRANSPORT", "stdio").strip().lower()
    command = os.environ.get("QANTARA_MCP_COMMAND", "").strip()
    url = os.environ.get("QANTARA_MCP_URL", "").strip().rstrip("/")
    chat_tool = os.environ.get("QANTARA_MCP_CHAT_TOOL", "chat").strip()
    configured = (transport == "stdio" and bool(command)) or (transport == "http" and bool(url))
    result: dict[str, Any] = {
        "available": configured,
        "configured": configured,
        "transport": transport,
        "chat_tool": chat_tool,
        "tools": [],
    }
    if not configured:
        return result
    try:
        from adapters.base import AdapterConfig
        from adapters.mcp_client import MCPClientAdapter

        adapter = MCPClientAdapter(
            AdapterConfig(
                kind="mcp_client",
                name="mcp",
                options={
                    "transport": transport,
                    "command": command,
                    "url": url,
                    "chat_tool": chat_tool,
                    "timeout_seconds": 10,
                },
            )
        )
        result["tools"] = await adapter.list_tools()
        result["available"] = True
        result["chat_tool_found"] = any(tool["name"] == chat_tool for tool in result["tools"])
    except Exception as exc:
        result["available"] = False
        result["error"] = str(exc)
    return result


def _assemble_backends(
    ollama_result: dict[str, Any],
    openclaw_result: dict[str, Any],
    openai_result: dict[str, Any],
    mcp_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    mcp_result = mcp_result or {"available": False, "configured": False}
    backends: list[dict[str, Any]] = []
    oai: dict[str, Any] = {"type": "openai_compatible", "name": "OpenAI-Compatible", "available": True}
    if openai_result["available"]:
        oai["servers"] = openai_result.get("servers", [])
        oai["auto_detected"] = True
    if ollama_result["available"]:
        oai["ollama_url"] = ollama_base_url()
    backends.append(oai)
    if openclaw_result.get("available", False):
        backends.append(
            {
                "type": "openclaw",
                "name": "OpenClaw",
                "available": True,
                "advanced": True,
                "optional": True,
                "description": "Optional host CLI bridge for existing OpenClaw agents",
                "installed": openclaw_result.get("installed", False),
                "gateway_running": openclaw_result.get("gateway_running", False),
                "agents": openclaw_result.get("agents", []),
            }
        )
    backends.append({"type": "ollama", "name": "Ollama (bridge)", "available": ollama_result["available"], "models": ollama_result.get("models", [])} if ollama_result["available"] else {"type": "ollama", "name": "Ollama (bridge)", "available": False})
    backends.append(
        {
            "type": "mcp",
            "name": "Any MCP server",
            "available": True,
            "advanced": True,
            "description": "Agent-style MCP chat tool adapter",
            "configured": mcp_result.get("configured", False),
            "transport": mcp_result.get("transport", "stdio"),
            "chat_tool": mcp_result.get("chat_tool", "chat"),
            "tools": mcp_result.get("tools", []),
            "chat_tool_found": mcp_result.get("chat_tool_found", False),
            "probe_error": mcp_result.get("error"),
        }
    )
    backends.append({"type": "custom", "name": "Custom URL", "available": True})
    backends.append({"type": "mock", "name": "Demo", "available": True})
    return backends


async def api_backends_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    ollama_result, openclaw_result, openai_result, mcp_result = await asyncio.gather(
        probe_ollama(),
        probe_openclaw(),
        probe_openai_compatible(),
        probe_mcp(),
    )
    return web.json_response({"backends": _assemble_backends(ollama_result, openclaw_result, openai_result, mcp_result)})


async def api_backends_stream_handler(request: web.Request) -> web.StreamResponse:
    """SSE-streamed backend detection. Emits probe_started + probe_completed
    events as each parallel probe resolves, then a final `done` event with
    the fully-assembled backends list matching /api/backends exactly. Useful
    for surfacing per-probe progress in the setup page, which otherwise has
    to wait up to 60s on a slow OpenClaw install."""
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive"})
    await response.prepare(request)

    async def send_event(event_type: str, data: dict) -> None:
        payload = json.dumps(data).encode("utf-8")
        await response.write(b"event: " + event_type.encode() + b"\ndata: " + payload + b"\n\n")

    probes: dict[str, tuple[str, Any]] = {
        "ollama": ("Ollama", probe_ollama()),
        "openclaw": ("OpenClaw", probe_openclaw()),
        "openai_compatible": ("OpenAI-Compatible", probe_openai_compatible()),
        "mcp": ("MCP", probe_mcp()),
    }
    tasks: dict[asyncio.Task, str] = {}
    try:
        await send_event("start", {"total": len(probes)})
        for probe_type, (probe_name, coro) in probes.items():
            task = asyncio.create_task(coro)
            tasks[task] = probe_type
            await send_event("probe_started", {"type": probe_type, "name": probe_name})

        results: dict[str, dict[str, Any]] = {}
        pending = set(tasks.keys())
        completed = 0
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                probe_type = tasks[task]
                try:
                    result = task.result()
                except Exception as exc:
                    result = {"available": False, "error": str(exc)}
                results[probe_type] = result
                completed += 1
                await send_event("probe_completed", {"type": probe_type, "result": result, "completed": completed, "total": len(probes)})

        backends = _assemble_backends(
            results.get("ollama", {"available": False}),
            results.get("openclaw", {"available": False}),
            results.get("openai_compatible", {"available": False}),
            results.get("mcp", {"available": False, "configured": False}),
        )
        await send_event("done", {"backends": backends})
    except Exception as exc:
        await send_event("error", {"message": str(exc)})
    await response.write_eof()
    return response


async def api_status_handler(request: web.Request) -> web.Response:
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    if request.app.get(AUTH_TOKEN_KEY) is not None and not has_valid_auth_token(
        request, AUTH_TOKEN_KEY
    ):
        health = runtime.default_binding().health
        return web.json_response(
            {
                "status": health.get("status", "unknown"),
                "authentication_required": True,
            }
        )
    return web.json_response(runtime.status_payload())


async def api_admin_runtime_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(
        request,
        ADMIN_TOKEN_KEY,
        feature_disabled_status=404,
    )
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    runtime.prune_session_store()
    return web.json_response(runtime.admin_payload())


def _binding_request_kwargs(binding: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    host_header = getattr(binding, "outbound_host_header", "")
    server_hostname = getattr(binding, "outbound_server_hostname", "")
    if host_header:
        kwargs["headers"] = {"Host": host_header}
    if server_hostname:
        kwargs["server_hostname"] = server_hostname
    return kwargs


async def unload_previous_model(runtime: GatewayRuntime, binding: Any | None = None) -> None:
    binding = binding or runtime.default_binding()
    if not binding.url or not binding.model:
        return
    timeout = _aiohttp.ClientTimeout(total=5)
    try:
        async with _aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            if binding.backend_type == "ollama":
                async with session.post(
                    f"{binding.url}/api/generate",
                    json={"model": binding.model, "keep_alive": 0},
                    allow_redirects=False,
                    **_binding_request_kwargs(binding),
                ) as response:
                    await read_bounded_response_bytes(response)
            elif binding.backend_type in ("openai_compatible", "openai"):
                base = binding.url[:-3] if binding.url.endswith("/v1") else binding.url
                async with session.post(
                    f"{base}/api/v0/models/unload",
                    json={"model": binding.model},
                    allow_redirects=False,
                    **_binding_request_kwargs(binding),
                ) as response:
                    await read_bounded_response_bytes(response)
    except Exception:
        pass


async def warmup_current_backend(runtime: GatewayRuntime, timeout_s: float = 90.0) -> dict[str, Any]:
    """Preload the configured model so the first voice turn doesn't pay
    the model cold-load tax. Ollama and OpenAI-compatible have
    different primitives for this; non-model backends (mock / custom
    bridges without URL knowledge) become no-ops. Returns a small dict
    the client can render."""
    binding = runtime.default_binding()
    result: dict[str, Any] = {
        "backend_type": binding.backend_type,
        "model": binding.model,
        "warmed": False,
    }
    if binding.backend_type == "mock":
        result["warmed"] = True
        result["note"] = "mock backend has no model to load"
        return result
    if not binding.model:
        result["note"] = "no model configured"
        return result
    started = time.monotonic()
    timeout = _aiohttp.ClientTimeout(total=timeout_s)
    try:
        async with _aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            if binding.backend_type == "ollama":
                # Ollama's canonical preload: empty prompt + keep_alive
                # loads the model into RAM without generating output.
                ollama_url = ollama_base_url()
                async with session.post(
                    f"{ollama_url}/api/generate",
                    json={"model": binding.model, "keep_alive": "10m", "prompt": ""},
                    allow_redirects=False,
                    **_binding_request_kwargs(binding),
                ) as resp:
                    if resp.status >= 400:
                        result["error"] = f"ollama preload returned {resp.status}"
                    else:
                        await read_bounded_response_bytes(resp)
                        result["warmed"] = True
            elif binding.backend_type in ("openai_compatible", "openai"):
                # Send a minimal chat-completions request with max_tokens=1
                # so most servers at least load weights into memory.
                url = binding.url.rstrip("/")
                if not url.endswith("/v1"):
                    url = f"{url}/v1"
                async with session.post(
                    f"{url}/chat/completions",
                    json={
                        "model": binding.model,
                        "messages": [{"role": "user", "content": "."}],
                        "max_tokens": 1,
                    },
                    allow_redirects=False,
                    **_binding_request_kwargs(binding),
                ) as resp:
                    if resp.status >= 400:
                        result["error"] = f"openai warmup returned {resp.status}"
                    else:
                        await read_bounded_response_bytes(resp)
                        result["warmed"] = True
            else:
                # OpenClaw, custom bridges, etc — no general preload primitive
                result["note"] = f"no-op for backend type {binding.backend_type!r}"
                result["warmed"] = True
    except TimeoutError:
        result["error"] = f"warmup timed out after {timeout_s:.0f}s"
    except Exception as exc:
        result["error"] = f"warmup failed: {exc}"
    result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    return result


async def api_warmup_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    result = await warmup_current_backend(runtime)
    return web.json_response(result)


async def api_translation_mode_handler(request: web.Request) -> web.Response:
    from dataclasses import replace

    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid JSON body"}, status=400)

    client_session_id = body.get("client_session_id")
    if not isinstance(client_session_id, str) or not client_session_id.strip():
        return web.json_response({"error": "missing client_session_id"}, status=400)
    client_session_id = client_session_id.strip()
    if len(client_session_id) > MAX_CONFIGURATION_IDENTIFIER_CHARS:
        return web.json_response({"error": "client_session_id is too long"}, status=413)

    translation = _validate_translation_mode(body)
    if isinstance(translation, web.Response):
        return translation
    mode, source, target = translation

    snapshot = runtime.snapshot_for(client_session_id)
    if snapshot is None:
        return web.json_response({"error": "unknown client_session_id"}, status=404)

    active_session = runtime.resolve_active_session(client_session_id=client_session_id)
    if active_session is not None:
        _apply_session_translation(active_session, mode, source, target)

    runtime._session_store[client_session_id] = replace(
        snapshot,
        translation_mode=mode,
        translation_source=source,
        translation_target=target,
        updated_monotonic_ms=runtime._now_ms(),
    )

    return web.json_response({"mode": mode, "source": source, "target": target})


def _validate_translation_mode(body: dict[str, Any]) -> tuple[str | None, str | None, str | None] | web.Response:
    from gateway.transport_spike.prompts import LANGUAGE_NAMES

    mode = body.get("mode")
    if mode not in {"assistant", "directional", "live", None}:
        return web.json_response({"error": f"invalid mode: {mode}"}, status=400)

    source = body.get("source")
    target = body.get("target")
    if mode in {"directional", "live"}:
        if not isinstance(source, str) or not isinstance(target, str):
            return web.json_response({"error": f"{mode} mode requires source and target"}, status=400)
        for code in (source, target):
            if code not in LANGUAGE_NAMES:
                return web.json_response({"error": f"unsupported language: {code}"}, status=400)
    elif (source is not None and not isinstance(source, str)) or (
        target is not None and not isinstance(target, str)
    ):
        return web.json_response({"error": "source and target must be strings"}, status=400)
    return mode, source, target


def _apply_session_translation(
    session: Any,
    mode: str | None,
    source: str | None,
    target: str | None,
) -> None:
    session.translation_mode = mode
    session.translation_source = source
    session.translation_target = target
    session.runtime.save_session_state(session)


async def api_languages_handler(request: web.Request) -> web.Response:
    from gateway.transport_spike.languages_catalog import build_language_catalog

    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    catalog = build_language_catalog(runtime.tts)
    return web.json_response({"languages": catalog})


async def api_tts_handler(request: web.Request) -> web.Response:
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    tts = runtime.tts
    current = tts.kind if tts is not None else "unknown"
    voices = tts.list_available_voices() if tts is not None and tts.available else []
    engines = ["piper", "kokoro", "chatterbox"]
    return web.json_response({"current": current, "engines": engines, "voices": voices})


def _control_target_error(runtime: GatewayRuntime) -> web.Response:
    count = len(runtime.active_voice_sessions())
    if count == 0:
        return web.json_response({"ok": False, "error": "no active browser voice session"}, status=404)
    return web.json_response(
        {"ok": False, "error": "multiple active sessions; provide session_id or client_session_id", "active_session_count": count},
        status=409,
    )


def _resolve_control_session(runtime: GatewayRuntime, body: dict[str, Any]):
    session_id = str(body.get("session_id") or "").strip() or None
    client_session_id = str(body.get("client_session_id") or "").strip() or None
    return runtime.resolve_active_session(session_id=session_id, client_session_id=client_session_id)


async def api_voice_control_session_start_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    session = _resolve_control_session(runtime, body)
    if session is not None:
        return web.json_response(
            {
                "ok": True,
                "status": "active",
                "session": runtime._session_control_payload(session, include_binding=True),
            }
        )
    sessions = runtime.active_voice_sessions()
    if not body.get("session_id") and not body.get("client_session_id") and sessions:
        return _control_target_error(runtime)
    browser_url = str(body.get("browser_url") or "/spike").strip() or "/spike"
    requested_client_session_id = str(body.get("client_session_id") or "").strip() or None
    return web.json_response(
        {
            "ok": True,
            "status": "waiting_for_browser_session",
            "client_session_id": requested_client_session_id,
            "browser_url": browser_url,
            "message": "Open Qantara in a browser and connect a voice session; MCP cannot create microphone capture by itself.",
            "active_session_count": len(sessions),
        },
        status=202,
    )


async def api_voice_control_status_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    sessions = runtime.active_voice_sessions()
    return web.json_response({"ok": True, "active_session_count": len(sessions), "sessions": sessions})


async def api_voice_control_transcript_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    if request.method == "GET":
        body = dict(request.query)
    else:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
    session = _resolve_control_session(runtime, body)
    if session is None:
        return _control_target_error(runtime)
    return web.json_response({"ok": True, **runtime.session_transcript_payload(session)})


async def api_voice_control_speak_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
    text = str(body.get("text") or "").strip()
    if not text:
        return web.json_response({"ok": False, "error": "missing text"}, status=400)
    max_chars = int(os.environ.get("QANTARA_CONTROL_MAX_SPEAK_CHARS", "4000"))
    if len(text) > max_chars:
        return web.json_response({"ok": False, "error": f"text exceeds {max_chars} characters"}, status=413)
    session = _resolve_control_session(runtime, body)
    if session is None:
        return _control_target_error(runtime)
    voice_id = str(body.get("voice_id") or "").strip() or None
    interrupt = bool(body.get("interrupt", False))
    if interrupt:
        from gateway.transport_spike.speech import cancel_active_turn

        session.playback_generation += 1
        session.speech_generation += 1
        await session.emit("playback_queue_cleared", "control", {"reason": "voice_speak_interrupt"})
        await cancel_active_turn(session, "voice_speak_interrupt")
    from gateway.transport_spike.speech import enqueue_control_speech

    generation = session.speech_generation
    enqueue_control_speech(session, text, frozen_generation=generation, voice_id=voice_id)
    await session.emit("voice_speak_queued", "control", {"char_count": len(text), "voice_id": voice_id, "generation": generation})
    return web.json_response(
        {
            "ok": True,
            "status": "queued",
            "session": runtime._session_control_payload(session, include_binding=True),
            "generation": generation,
        }
    )


async def api_voice_control_interrupt_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    session = _resolve_control_session(runtime, body)
    if session is None:
        return _control_target_error(runtime)
    from gateway.transport_spike.speech import cancel_active_turn, safe_send_str

    session.playback_generation += 1
    session.speech_generation += 1
    await session.emit("playback_queue_cleared", "control", {"reason": "voice_interrupt"})
    await cancel_active_turn(session, "voice_interrupt")
    await safe_send_str(session, {"type": "playback_cleared", "generation": session.playback_generation, "source": "control"})
    if session.state in {"speaking", "thinking", "interrupted"}:
        await session.set_state("idle", reason="voice_interrupt")
    return web.json_response(
        {
            "ok": True,
            "status": "interrupted",
            "session": runtime._session_control_payload(session, include_binding=True),
        }
    )


async def api_voice_control_voice_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
    session = _resolve_control_session(runtime, body)
    if session is None:
        return _control_target_error(runtime)
    voice_id = str(body.get("voice_id") or "").strip()
    if not voice_id:
        return web.json_response({"ok": False, "error": "missing voice_id"}, status=400)
    from gateway.transport_spike.speech import apply_voice_selection

    details = apply_voice_selection(session, voice_id)
    await session.emit("session_updated", "control", details)
    return web.json_response({"ok": True, "session": runtime._session_control_payload(session, include_binding=True), **details})


async def api_voice_control_translation_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
    session = _resolve_control_session(runtime, body)
    if session is None:
        return _control_target_error(runtime)
    translation = _validate_translation_mode(body)
    if isinstance(translation, web.Response):
        return translation
    mode, source, target = translation
    _apply_session_translation(session, mode, source, target)
    details = {
        "translation_mode": mode,
        "translation_source": source,
        "translation_target": target,
    }
    from gateway.transport_spike.speech import safe_send_str

    await session.emit("session_updated", "control", details)
    await safe_send_str(session, {"type": "session_updated", **details})
    return web.json_response(
        {
            "ok": True,
            "session": runtime._session_control_payload(session, include_binding=True),
            **details,
        }
    )


async def api_test_mcp_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "invalid JSON object"}, status=400)
    transport_value = body.get("transport") or os.environ.get("QANTARA_MCP_TRANSPORT", "stdio")
    chat_tool_value = body.get("chat_tool") or os.environ.get("QANTARA_MCP_CHAT_TOOL", "chat")
    url_value = body.get("url") or os.environ.get("QANTARA_MCP_URL", "")
    if not all(isinstance(value, str) for value in (transport_value, chat_tool_value, url_value)):
        return web.json_response({"ok": False, "error": "MCP settings must be strings"}, status=400)
    transport = transport_value.strip().lower()
    chat_tool = chat_tool_value.strip()
    command = os.environ.get("QANTARA_MCP_COMMAND", "").strip()
    url = url_value.strip().rstrip("/")
    safe_mcp_url: SafeOutboundURL | None = None
    if len(chat_tool) > MAX_CONFIGURATION_IDENTIFIER_CHARS:
        return web.json_response({"ok": False, "error": "chat tool name is too long"}, status=413)
    if len(url) > MAX_CONFIGURATION_URL_CHARS:
        return web.json_response({"ok": False, "error": "MCP URL is too long"}, status=413)
    if transport not in {"stdio", "http"}:
        return web.json_response({"ok": False, "error": f"unsupported MCP transport: {transport}"}, status=400)
    if transport == "stdio" and not command:
        return web.json_response(
            {"ok": False, "error": "stdio MCP probing requires QANTARA_MCP_COMMAND in the gateway environment"},
            status=400,
        )
    if transport == "http":
        if not url:
            return web.json_response({"ok": False, "error": "missing MCP URL"}, status=400)
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        safe_mcp_url = _safe_outbound_url(url)
        if safe_mcp_url is None:
            return web.json_response({"ok": False, "error": "Only private network MCP URLs are allowed"}, status=403)
        url = safe_mcp_url.url
    try:
        from adapters.base import AdapterConfig
        from adapters.mcp_client import MCPClientAdapter

        adapter = MCPClientAdapter(
            AdapterConfig(
                kind="mcp_client",
                name="mcp",
                options={
                    "transport": transport,
                    "command": command,
                    "url": url,
                    "chat_tool": chat_tool,
                    "timeout_seconds": 10,
                    "outbound_host_header": (
                        safe_mcp_url.host_header if transport == "http" else ""
                    ),
                    "outbound_server_hostname": (
                        safe_mcp_url.server_hostname if transport == "http" else ""
                    ),
                },
            )
        )
        tools = await adapter.list_tools()
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)
    return web.json_response(
        {
            "ok": True,
            "tools": tools,
            "chat_tool_found": any(tool["name"] == chat_tool for tool in tools),
        }
    )


async def api_configure_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid JSON body"}, status=400)
    backend_type_value = body.get("type", "")
    if not isinstance(backend_type_value, str):
        return web.json_response({"error": "'type' must be a string"}, status=400)
    backend_type = backend_type_value.strip().lower()
    if not backend_type:
        return web.json_response({"error": "missing 'type' field"}, status=400)
    if backend_type not in {"mock", "custom", "openai_compatible", "openai", "ollama", "openclaw", "mcp", "mcp_client"}:
        return web.json_response({"error": f"unknown type: {backend_type}"}, status=400)
    raw_url_value = body.get("url", "")
    model_value = body.get("model", "")
    agent_value = body.get("agent", "")
    mcp_chat_tool_value = body.get("mcp_chat_tool") or os.environ.get(
        "QANTARA_MCP_CHAT_TOOL", "chat"
    )
    if not all(
        isinstance(value, str)
        for value in (raw_url_value, model_value, agent_value, mcp_chat_tool_value)
    ):
        return web.json_response({"error": "backend settings must be strings"}, status=400)
    raw_url = raw_url_value.strip().rstrip("/")
    model = model_value.strip()
    agent = agent_value.strip()
    mcp_chat_tool = mcp_chat_tool_value.strip()
    if len(raw_url) > MAX_CONFIGURATION_URL_CHARS:
        return web.json_response({"error": "backend URL is too long"}, status=413)
    if any(
        len(value) > MAX_CONFIGURATION_IDENTIFIER_CHARS
        for value in (model, agent, mcp_chat_tool)
    ):
        return web.json_response({"error": "configuration identifier is too long"}, status=413)
    mcp_transport_value = body.get("mcp_transport") or os.environ.get(
        "QANTARA_MCP_TRANSPORT", "stdio"
    )
    if not isinstance(mcp_transport_value, str):
        return web.json_response({"error": "MCP transport must be a string"}, status=400)
    mcp_transport = mcp_transport_value.strip().lower()
    if backend_type in {"mcp", "mcp_client"} and mcp_transport == "stdio":
        raw_url = ""
    requires_safe_url = (
        backend_type in {"custom", "openai_compatible", "openai", "ollama"}
        or (backend_type in {"mcp", "mcp_client"} and mcp_transport == "http")
    )
    outbound_host_header = ""
    outbound_server_hostname = ""
    if requires_safe_url and raw_url:
        safe_url = _safe_outbound_url(raw_url)
        if safe_url is None:
            return web.json_response({"error": "Only private network URLs are allowed"}, status=403)
        raw_url = safe_url.url
        outbound_host_header = safe_url.host_header
        outbound_server_hostname = safe_url.server_hostname
    previous_binding = runtime.default_binding()
    try:
        binding = await runtime.configure_backend(
            backend_type,
            url=raw_url,
            model=model,
            agent=agent,
            mcp_transport=mcp_transport,
            mcp_command=os.environ.get("QANTARA_MCP_COMMAND", "").strip(),
            mcp_chat_tool=mcp_chat_tool,
            outbound_host_header=outbound_host_header,
            outbound_server_hostname=outbound_server_hostname,
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    await unload_previous_model(runtime, previous_binding)
    tts_engine_value = body.get("tts_engine", "")
    tts_engine = tts_engine_value.strip() if isinstance(tts_engine_value, str) else ""
    if tts_engine and tts_engine in {"piper", "kokoro", "chatterbox"}:
        # TTS live-swap is deferred — persist the preference into process env
        # so the next time the factory is invoked (restart or reconfigure) it
        # picks this engine up. The client surfaces a "restart required" note.
        os.environ["QANTARA_TTS_PROVIDER"] = tts_engine
    # Persist translation preferences on the runtime defaults so newly
    # connecting sessions pick them up. Per-session overrides still flow
    # through /api/translation_mode.
    from gateway.transport_spike.prompts import LANGUAGE_NAMES as _LANGS
    primary_language = body.get("primary_language")
    if not isinstance(primary_language, str):
        primary_language = None
    if primary_language in _LANGS:
        runtime.default_primary_language = primary_language
    translation_mode = body.get("translation_mode")
    if translation_mode is not None and not isinstance(translation_mode, str):
        translation_mode = None
    if translation_mode in {"assistant", "directional", "live", None}:
        runtime.default_translation_mode = translation_mode
    translation_source = body.get("translation_source")
    translation_target = body.get("translation_target")
    if not isinstance(translation_source, str):
        translation_source = None
    if not isinstance(translation_target, str):
        translation_target = None
    if translation_source in _LANGS and translation_target in _LANGS:
        runtime.default_translation_source = translation_source
        runtime.default_translation_target = translation_target
    return web.json_response({"ok": True, "type": backend_type, "adapter_kind": binding.adapter_kind, "url": binding.url, "health": binding.health, "managed_bridge": binding.managed_bridge_type, "binding_id": binding.binding_id, "tts_engine_pref": tts_engine or None})


def _is_lan_ip(addr: Any) -> bool:
    """True only for addresses that are genuinely on a private LAN / loopback.

    ``ipaddress.is_private`` is NOT a safe allowlist: it reports True for the
    link-local range (169.254.0.0/16, which includes the cloud metadata
    endpoint 169.254.169.254, plus fe80::/10) and for the unspecified address
    (0.0.0.0 / ::, which routes to localhost on Linux). Reject those classes
    explicitly, unwrap IPv4-mapped IPv6 so ::ffff:169.254.169.254 cannot smuggle
    a metadata IP past the guard, and treat loopback as always safe (IPv6 ::1 is
    flagged is_reserved, so it must be allowed before the reserved check).
    """
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    if addr.is_loopback:
        return True
    if addr.is_unspecified or addr.is_link_local or addr.is_multicast or addr.is_reserved:
        return False
    return addr.is_private


def is_safe_url(url: str) -> bool:
    return _resolve_safe_url(url) is not None


def _resolve_safe_url(url: str) -> SafeOutboundURL | None:
    import ipaddress as _ipa
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        host = parsed.hostname or ""
        if not host:
            return None
        port = parsed.port
        try:
            candidates = [_ipa.ip_address(host)]
        except ValueError:
            if host not in {"localhost"} and "." in host and not host.endswith((".local", ".lan", ".home.arpa")):
                return None
            resolved = _sock.getaddrinfo(host, port, _sock.AF_UNSPEC, _sock.SOCK_STREAM)
            candidates = [_ipa.ip_address(sockaddr[0]) for _, _, _, _, sockaddr in resolved]
        if not candidates or not all(_is_lan_ip(addr) for addr in candidates):
            return None
        # Prefer IPv4 when both families are available. Many local model
        # servers listen only on 127.0.0.1/private IPv4 even though mDNS or
        # localhost resolution returns ::1 first; pinning that first record
        # would make an otherwise valid LAN backend appear unreachable.
        selected = next(
            (candidate for candidate in candidates if candidate.version == 4),
            candidates[0],
        )
        selected_host = selected.compressed
        if selected.version == 6:
            selected_host = f"[{selected_host}]"
        if port is not None:
            selected_host = f"{selected_host}:{port}"
        return SafeOutboundURL(
            url=parsed._replace(netloc=selected_host).geturl(),
            host_header=parsed.netloc,
            server_hostname=host,
        )
    except Exception:
        return None


def _safe_outbound_url(raw_url: str) -> SafeOutboundURL | None:
    """SSRF-validate ``raw_url`` and return it with the resolved IP pinned into
    the netloc, or ``None`` if it is not a private/loopback target.

    Pinning the validated IP (rather than forwarding the original hostname)
    closes the DNS-rebinding window: ``/api/configure`` and ``/api/test-mcp``
    previously validated a hostname and then handed the *hostname* to the
    adapter, which re-resolved it at connect time — letting a hostname that
    first resolves private flip to a public/metadata IP on the real request.
    """
    candidate = raw_url if raw_url.startswith(("http://", "https://")) else f"http://{raw_url}"
    resolved = _resolve_safe_url(candidate)
    return resolved


_ORIGIN_PROTECTED_PATHS = frozenset({"/ws", "/api/discovery/scan"})
_ORIGIN_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_LOCAL_HOST_SUFFIXES = (".local", ".lan", ".home.arpa")
_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}\.?$)(?!-)(?:[a-z0-9-]{1,63}(?<!-)\.)*[a-z0-9-]{1,63}(?<!-)\.?$",
    re.IGNORECASE,
)


def _parse_authority(raw_authority: str) -> tuple[str, int | None] | None:
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(f"//{raw_authority.strip()}")
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return None
        host = (parsed.hostname or "").rstrip(".").lower()
        if not host:
            return None
        return host, parsed.port
    except ValueError:
        return None


def _request_authority(request: web.Request) -> tuple[str, int | None] | None:
    return _parse_authority(request.headers.get("Host", ""))


def _host_allowed(request: web.Request) -> bool:
    authority = _request_authority(request)
    if authority is None:
        return False
    host, _ = authority

    configured = os.environ.get("QANTARA_ALLOWED_HOSTS", "")
    allowed_hosts: set[str] = set()
    for entry in configured.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parsed = _parse_authority(entry)
        if parsed is not None:
            allowed_hosts.add(parsed[0])
    if host in allowed_hosts:
        return True

    import ipaddress

    try:
        return _is_lan_ip(ipaddress.ip_address(host))
    except ValueError:
        if not _HOSTNAME_PATTERN.fullmatch(host):
            return False
        return host == "localhost" or "." not in host or host.endswith(_LOCAL_HOST_SUFFIXES)


def _origin_allowed(request: web.Request) -> bool:
    """Reject cross-site requests that carry a browser Origin which does not
    match the host the request was sent to.

    This blocks cross-site WebSocket hijacking and cross-site POSTs that ride on
    the HttpOnly auth cookie. Requests with no Origin header are allowed:
    non-browser API clients (which authenticate with a Bearer token) omit it,
    and browsers reliably send Origin on the dangerous cross-origin cases
    (WebSocket handshakes always, cross-origin fetch always). An explicit
    allowlist can be set via QANTARA_ALLOWED_ORIGINS (comma-separated).
    """
    origin = request.headers.get("Origin")
    if not origin:
        return True
    from urllib.parse import urlsplit

    try:
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or parsed_origin.username is not None
            or parsed_origin.password is not None
            or not parsed_origin.hostname
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            return False
        origin_host = parsed_origin.hostname.rstrip(".").lower()
        origin_port = parsed_origin.port
    except ValueError:
        return False

    request_authority = _request_authority(request)
    if request_authority is None:
        return False
    request_host, request_port = request_authority
    same_host = origin_host == request_host
    if same_host:
        if request_port is None:
            if origin_port is None:
                return True
        else:
            effective_origin_port = origin_port or (
                443 if parsed_origin.scheme == "https" else 80
            )
            if effective_origin_port == request_port:
                return True

    configured = os.environ.get("QANTARA_ALLOWED_ORIGINS", "").strip()
    allowed = {
        item.strip().rstrip("/").lower()
        for item in configured.split(",")
        if item.strip()
    }
    return origin.rstrip("/").lower() in allowed


@web.middleware
async def origin_guard_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    if not _host_allowed(request):
        return web.json_response({"error": "request host rejected"}, status=421)
    is_preflight = request.method == "OPTIONS" and bool(
        request.headers.get("Access-Control-Request-Method")
    )
    needs_check = (
        is_preflight
        or request.method not in _ORIGIN_SAFE_METHODS
        or request.path in _ORIGIN_PROTECTED_PATHS
    )
    if needs_check and not _origin_allowed(request):
        return web.json_response({"error": "cross-origin request rejected"}, status=403)
    if is_preflight:
        requested_method = request.headers.get(
            "Access-Control-Request-Method", ""
        ).upper()
        if requested_method not in {"GET", "HEAD", "POST"}:
            return web.json_response(
                {"error": "cross-origin method rejected"}, status=403
            )
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Max-Age": "600",
            },
        )
    return await handler(request)


async def add_security_headers(
    request: web.Request,
    response: web.StreamResponse,
) -> None:
    """Apply browser hardening headers, including to prepared WS/SSE responses."""
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; "
        "img-src 'self' data:; media-src 'self' blob:; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "microphone=(self)")
    origin = request.headers.get("Origin")
    if origin and _origin_allowed(request):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        vary = response.headers.get("Vary", "")
        if "origin" not in {item.strip().lower() for item in vary.split(",")}:
            response.headers["Vary"] = f"{vary}, Origin".lstrip(", ")
    if request.path.startswith("/api/") or request.path == "/ws":
        response.headers["Cache-Control"] = "no-store"


def _safe_model_probe_base(raw_url: str) -> tuple[str, dict[str, str], str] | None:
    resolved = _resolve_safe_url(raw_url)
    if resolved is None:
        return None
    base = resolved.url[:-3] if resolved.url.endswith("/v1") else resolved.url
    return base, {"Host": resolved.host_header}, resolved.server_hostname


async def api_test_url_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    client_ip = request.remote or "unknown"
    if not _check_test_url_rate_limit(client_ip):
        return web.json_response(
            {"ok": False, "error": "too many requests; retry in a few seconds"},
            status=429,
        )
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "invalid JSON object"}, status=400)
    raw_url_value = body.get("url")
    raw_url = raw_url_value.strip().rstrip("/") if isinstance(raw_url_value, str) else ""
    if not raw_url:
        return web.json_response({"ok": False, "error": "missing url"}, status=400)
    if len(raw_url) > MAX_CONFIGURATION_URL_CHARS:
        return web.json_response({"ok": False, "error": "URL is too long"}, status=413)
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "http://" + raw_url
    safe_probe = _safe_model_probe_base(raw_url)
    if safe_probe is None:
        return web.json_response({"ok": False, "error": "Only private network URLs are allowed"}, status=403)
    base, headers, server_hostname = safe_probe
    timeout = _aiohttp.ClientTimeout(total=5)
    for prefix in ("/v1", ""):
        try:
            async with _aiohttp.ClientSession(timeout=timeout, trust_env=False) as cs:
                # allow_redirects=False: the probed server is only IP-validated
                # at this URL; following a 302 would let it redirect us to a
                # public/metadata host and defeat the SSRF guard.
                async with cs.get(
                    f"{base}{prefix}/models",
                    headers=headers,
                    allow_redirects=False,
                    server_hostname=server_hostname,
                ) as resp:
                    if resp.status < 400:
                        data = await read_bounded_response_json(resp)
                        if not isinstance(data, dict):
                            continue
                        model_items = data.get("data", [])
                        if not isinstance(model_items, list):
                            continue
                        models = [
                            m.get("id", "")
                            for m in model_items
                            if isinstance(m, dict) and m.get("id")
                        ]
                        return web.json_response({"ok": True, "models": models, "url": base})
        except Exception:
            continue
    return web.json_response({"ok": False, "error": f"Cannot reach {base}. Is the server running?"})


async def index_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/setup/index.html")


async def setup_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/setup/index.html")


async def spike_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/spike/index.html")


async def translate_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/translate/index.html")


async def api_mesh_peers_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    controller = runtime.mesh_controller
    if controller is None:
        return web.json_response({"enabled": False, "peers": []})
    peers = [
        {
            "node_id": p.node_id,
            "role": p.role,
            "host": p.host,
            "port": p.port,
        }
        for p in controller.registry.list_peers()
    ]
    return web.json_response({"enabled": True, "peers": peers})


async def api_mesh_status_handler(request: web.Request) -> web.Response:
    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    controller = runtime.mesh_controller
    if controller is None:
        return web.json_response({"enabled": False, "role": "disabled", "node_id": None})
    cfg = controller.config
    return web.json_response({
        "enabled": True,
        "role": cfg.role,
        "node_id": cfg.node_id,
        "mesh_port": cfg.mesh_port,
        "service_type": cfg.service_type,
        "peer_count": len(controller.registry.list_peers()),
    })


def mount_static_routes(app: web.Application) -> None:
    mount_voice_api(app)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/auth/status", api_auth_status_handler)
    app.router.add_post("/api/auth/login", api_auth_login_handler)
    app.router.add_post("/api/auth/logout", api_auth_logout_handler)
    app.router.add_get("/api/backends", api_backends_handler)
    app.router.add_get("/api/backends/stream", api_backends_stream_handler)
    app.router.add_get("/api/status", api_status_handler)
    app.router.add_get("/api/admin/runtime", api_admin_runtime_handler)
    app.router.add_get("/api/tts", api_tts_handler)
    app.router.add_get("/api/languages", api_languages_handler)
    app.router.add_post("/api/control/voice/session_start", api_voice_control_session_start_handler)
    app.router.add_get("/api/control/voice/status", api_voice_control_status_handler)
    app.router.add_get("/api/control/voice/transcript", api_voice_control_transcript_handler)
    app.router.add_post("/api/control/voice/transcript", api_voice_control_transcript_handler)
    app.router.add_post("/api/control/voice/speak", api_voice_control_speak_handler)
    app.router.add_post("/api/control/voice/interrupt", api_voice_control_interrupt_handler)
    app.router.add_post("/api/control/voice/set_voice", api_voice_control_voice_handler)
    app.router.add_post("/api/control/voice/set_translation_mode", api_voice_control_translation_handler)
    app.router.add_post("/api/translation_mode", api_translation_mode_handler)
    app.router.add_post("/api/configure", api_configure_handler)
    app.router.add_post("/api/warmup", api_warmup_handler)
    app.router.add_post("/api/test-url", api_test_url_handler)
    app.router.add_post("/api/test-mcp", api_test_mcp_handler)
    app.router.add_get("/api/mesh/peers", api_mesh_peers_handler)
    app.router.add_get("/api/mesh/status", api_mesh_status_handler)
    app.router.add_get("/setup", setup_handler)
    app.router.add_static("/setup", CLIENT_SETUP_DIR, show_index=True)
    app.router.add_get("/spike", spike_handler)
    app.router.add_static("/spike", CLIENT_SPIKE_DIR, show_index=True)
    app.router.add_get("/translate", translate_handler)
    app.router.add_static("/translate", CLIENT_TRANSLATE_DIR, show_index=True)
    app.router.add_static("/identity", IDENTITY_DIR, show_index=False)
