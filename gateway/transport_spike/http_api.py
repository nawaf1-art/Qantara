from __future__ import annotations

import asyncio
import json
import os
import socket as _sock
import time
from collections import deque
from typing import Any

import aiohttp as _aiohttp
from aiohttp import web

from gateway.transport_spike.auth import ADMIN_TOKEN_KEY, AUTH_TOKEN_KEY, require_bearer_token
from gateway.transport_spike.common import CLIENT_SETUP_DIR, CLIENT_SPIKE_DIR, CLIENT_TRANSLATE_DIR, IDENTITY_DIR
from gateway.transport_spike.runtime import APP_RUNTIME_KEY, GatewayRuntime

_TEST_URL_RATE_LIMIT_WINDOW_S = 10.0
_TEST_URL_RATE_LIMIT_MAX_CALLS = 8
_test_url_call_log: dict[str, deque[float]] = {}


def _check_test_url_rate_limit(client_ip: str) -> bool:
    now = time.monotonic()
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


def ollama_base_url() -> str:
    return os.environ.get("QANTARA_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


async def probe_ollama() -> dict[str, Any]:
    try:
        timeout = _aiohttp.ClientTimeout(total=3)
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{ollama_base_url()}/api/tags") as resp:
                if resp.status != 200:
                    return {"available": False}
                data = await resp.json()
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "")
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
        proc = await asyncio.create_subprocess_exec(openclaw_bin, "health", "--json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        health = json.loads(stdout.decode("utf-8", errors="replace"))
        if not health.get("ok"):
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
        proc = await asyncio.create_subprocess_exec(openclaw_bin, "agents", "list", "--json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=agents_timeout)
        agents_data = json.loads(stdout.decode("utf-8", errors="replace"))
        if isinstance(agents_data, list):
            for a in agents_data:
                agent_id = a.get("id", a.get("name", ""))
                if agent_id:
                    result["agents"].append({"id": agent_id, "name": a.get("identityName", agent_id), "default": a.get("isDefault", False)})
    except Exception:
        pass
    return result


async def probe_openai_port(host: str, port: int) -> dict[str, Any] | None:
    try:
        timeout = _aiohttp.ClientTimeout(total=2)
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"http://{host}:{port}/v1/models") as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json()
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                if models:
                    return {"port": port, "models": models, "url": f"http://{host}:{port}"}
    except Exception:
        pass
    return None


async def probe_openai_compatible() -> dict[str, Any]:
    results = await asyncio.gather(*[probe_openai_port("127.0.0.1", port) for port in [8080, 8000, 1337, 1234]])
    servers = [r for r in results if r is not None]
    return {"available": bool(servers), "servers": servers}


def _assemble_backends(
    ollama_result: dict[str, Any],
    openclaw_result: dict[str, Any],
    openai_result: dict[str, Any],
) -> list[dict[str, Any]]:
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
    backends.append({"type": "custom", "name": "Custom URL", "available": True})
    backends.append({"type": "mock", "name": "Demo", "available": True})
    return backends


async def api_backends_handler(_request: web.Request) -> web.Response:
    ollama_result, openclaw_result, openai_result = await asyncio.gather(probe_ollama(), probe_openclaw(), probe_openai_compatible())
    return web.json_response({"backends": _assemble_backends(ollama_result, openclaw_result, openai_result)})


async def api_backends_stream_handler(request: web.Request) -> web.StreamResponse:
    """SSE-streamed backend detection. Emits probe_started + probe_completed
    events as each parallel probe resolves, then a final `done` event with
    the fully-assembled backends list matching /api/backends exactly. Useful
    for surfacing per-probe progress in the setup page, which otherwise has
    to wait up to 60s on a slow OpenClaw install."""
    response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive"})
    await response.prepare(request)

    async def send_event(event_type: str, data: dict) -> None:
        payload = json.dumps(data).encode("utf-8")
        await response.write(b"event: " + event_type.encode() + b"\ndata: " + payload + b"\n\n")

    probes: dict[str, tuple[str, Any]] = {
        "ollama": ("Ollama", probe_ollama()),
        "openclaw": ("OpenClaw", probe_openclaw()),
        "openai_compatible": ("OpenAI-Compatible", probe_openai_compatible()),
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
        )
        await send_event("done", {"backends": backends})
    except Exception as exc:
        await send_event("error", {"message": str(exc)})
    await response.write_eof()
    return response


async def api_status_handler(request: web.Request) -> web.Response:
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
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


async def unload_previous_model(runtime: GatewayRuntime) -> None:
    binding = runtime.default_binding()
    if not binding.url or not binding.model:
        return
    timeout = _aiohttp.ClientTimeout(total=5)
    try:
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            if binding.backend_type == "ollama":
                await session.post(f"{binding.url}/api/generate", json={"model": binding.model, "keep_alive": 0})
            elif binding.backend_type in ("openai_compatible", "openai"):
                base = binding.url[:-3] if binding.url.endswith("/v1") else binding.url
                await session.post(f"{base}/api/v0/models/unload", json={"model": binding.model})
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
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            if binding.backend_type == "ollama":
                # Ollama's canonical preload: empty prompt + keep_alive
                # loads the model into RAM without generating output.
                ollama_url = ollama_base_url()
                async with session.post(
                    f"{ollama_url}/api/generate",
                    json={"model": binding.model, "keep_alive": "10m", "prompt": ""},
                ) as resp:
                    if resp.status >= 400:
                        result["error"] = f"ollama preload returned {resp.status}"
                    else:
                        await resp.read()
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
                ) as resp:
                    if resp.status >= 400:
                        result["error"] = f"openai warmup returned {resp.status}"
                    else:
                        await resp.read()
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
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    result = await warmup_current_backend(runtime)
    return web.json_response(result)


async def api_translation_mode_handler(request: web.Request) -> web.Response:
    from dataclasses import replace

    from gateway.transport_spike.prompts import LANGUAGE_NAMES

    auth_error = require_bearer_token(request, AUTH_TOKEN_KEY)
    if auth_error is not None:
        return auth_error
    runtime: GatewayRuntime = request.app[APP_RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    client_session_id = body.get("client_session_id")
    if not client_session_id:
        return web.json_response({"error": "missing client_session_id"}, status=400)

    mode = body.get("mode")
    if mode not in {"assistant", "directional", "live", None}:
        return web.json_response({"error": f"invalid mode: {mode}"}, status=400)

    source = body.get("source")
    target = body.get("target")
    if mode in {"directional", "live"}:
        if not source or not target:
            return web.json_response({"error": f"{mode} mode requires source and target"}, status=400)
        for code in (source, target):
            if code not in LANGUAGE_NAMES:
                return web.json_response({"error": f"unsupported language: {code}"}, status=400)

    snapshot = runtime.snapshot_for(client_session_id)
    if snapshot is None:
        return web.json_response({"error": "unknown client_session_id"}, status=404)

    runtime._session_store[client_session_id] = replace(
        snapshot,
        translation_mode=mode,
        translation_source=source,
        translation_target=target,
        updated_monotonic_ms=runtime._now_ms(),
    )

    return web.json_response({"mode": mode, "source": source, "target": target})


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
    backend_type = str(body.get("type", "")).strip().lower()
    if not backend_type:
        return web.json_response({"error": "missing 'type' field"}, status=400)
    if backend_type not in {"mock", "custom", "openai_compatible", "openai", "ollama", "openclaw"}:
        return web.json_response({"error": f"unknown type: {backend_type}"}, status=400)
    raw_url = str(body.get("url", "")).strip().rstrip("/")
    if (
        backend_type in {"custom", "openai_compatible", "openai", "ollama"}
        and raw_url
        and not is_safe_url(raw_url if raw_url.startswith(("http://", "https://")) else f"http://{raw_url}")
    ):
        return web.json_response({"error": "Only private network URLs are allowed"}, status=403)
    await unload_previous_model(runtime)
    try:
        binding = await runtime.configure_backend(
            backend_type,
            url=raw_url,
            model=str(body.get("model", "")).strip(),
            agent=str(body.get("agent", "")).strip(),
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    tts_engine = body.get("tts_engine", "").strip()
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
    if primary_language in _LANGS:
        runtime.default_primary_language = primary_language
    translation_mode = body.get("translation_mode")
    if translation_mode in {"assistant", "directional", "live", None}:
        runtime.default_translation_mode = translation_mode
    translation_source = body.get("translation_source")
    translation_target = body.get("translation_target")
    if translation_source in _LANGS and translation_target in _LANGS:
        runtime.default_translation_source = translation_source
        runtime.default_translation_target = translation_target
    return web.json_response({"ok": True, "type": backend_type, "adapter_kind": binding.adapter_kind, "url": binding.url, "health": binding.health, "managed_bridge": binding.managed_bridge_type, "binding_id": binding.binding_id, "tts_engine_pref": tts_engine or None})


def is_safe_url(url: str) -> bool:
    import ipaddress as _ipa
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host in ("localhost", "127.0.0.1", "::1"):
            return True
        addr = _ipa.ip_address(host)
        return addr.is_private or addr.is_loopback
    except (ValueError, TypeError):
        try:
            resolved = _sock.getaddrinfo(host, None, _sock.AF_UNSPEC, _sock.SOCK_STREAM)
            return len(resolved) > 0 and all(_ipa.ip_address(sockaddr[0]).is_private or _ipa.ip_address(sockaddr[0]).is_loopback for _, _, _, _, sockaddr in resolved)
        except Exception:
            return False


async def api_test_url_handler(request: web.Request) -> web.Response:
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
    raw_url = (body.get("url") or "").strip().rstrip("/")
    if not raw_url:
        return web.json_response({"ok": False, "error": "missing url"}, status=400)
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "http://" + raw_url
    if not is_safe_url(raw_url):
        return web.json_response({"ok": False, "error": "Only private network URLs are allowed"}, status=403)
    base = raw_url[:-3] if raw_url.endswith("/v1") else raw_url
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


async def index_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/setup/index.html")


async def setup_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/setup/index.html")


async def spike_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/spike/index.html")


async def translate_handler(_request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/translate/index.html")


async def api_mesh_peers_handler(request: web.Request) -> web.Response:
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
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/backends", api_backends_handler)
    app.router.add_get("/api/backends/stream", api_backends_stream_handler)
    app.router.add_get("/api/status", api_status_handler)
    app.router.add_get("/api/admin/runtime", api_admin_runtime_handler)
    app.router.add_get("/api/tts", api_tts_handler)
    app.router.add_get("/api/languages", api_languages_handler)
    app.router.add_post("/api/translation_mode", api_translation_mode_handler)
    app.router.add_post("/api/configure", api_configure_handler)
    app.router.add_post("/api/warmup", api_warmup_handler)
    app.router.add_post("/api/test-url", api_test_url_handler)
    app.router.add_get("/api/mesh/peers", api_mesh_peers_handler)
    app.router.add_get("/api/mesh/status", api_mesh_status_handler)
    app.router.add_get("/setup", setup_handler)
    app.router.add_static("/setup", CLIENT_SETUP_DIR, show_index=True)
    app.router.add_get("/spike", spike_handler)
    app.router.add_static("/spike", CLIENT_SPIKE_DIR, show_index=True)
    app.router.add_get("/translate", translate_handler)
    app.router.add_static("/translate", CLIENT_TRANSLATE_DIR, show_index=True)
    app.router.add_static("/identity", IDENTITY_DIR, show_index=False)
