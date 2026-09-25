from __future__ import annotations

import ipaddress
import logging
import os
import ssl
import sys

from aiohttp import web

CURRENT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gateway.transport_spike.auth import (  # noqa: E402
    auth_failure_middleware,
    install_auth,
)
from gateway.transport_spike.common import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    TLS_CERT_FILE,
    TLS_KEY_FILE,
)
from gateway.transport_spike.http_api import (  # noqa: E402
    add_security_headers,
    cleanup_bridge,
    mount_static_routes,
    origin_guard_middleware,
)
from gateway.transport_spike.runtime import APP_RUNTIME_KEY, GatewayRuntime, Session  # noqa: E402
from gateway.transport_spike.speech import (  # noqa: E402
    apply_speech_rate,
    apply_voice_selection,
    cancel_active_turn,
    ensure_adapter_session,
    refresh_adapter_health,
    start_assistant_turn,
    stream_assistant_turn,
)
from gateway.transport_spike.websocket_api import (  # noqa: E402
    api_discovery_scan_handler,
    websocket_handler,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "GatewayRuntime",
    "Session",
    "apply_speech_rate",
    "apply_voice_selection",
    "cancel_active_turn",
    "create_app",
    "create_ssl_context",
    "ensure_adapter_session",
    "refresh_adapter_health",
    "start_assistant_turn",
    "stream_assistant_turn",
    "websocket_handler",
]


def create_app(
    runtime: GatewayRuntime | None = None,
    *,
    bind_host: str | None = None,
) -> web.Application:
    """Build the gateway application.

    ``bind_host`` is the interface the caller will listen on; it only drives
    the startup warning. It defaults to QANTARA_SPIKE_HOST so the standalone
    server and the SDK (which passes its ``host`` argument) warn consistently.
    """
    # Keep control-plane JSON small. The one-shot transcription handler clones
    # its request with its separate 32 MiB audio-specific ceiling.
    app = web.Application(client_max_size=1024 * 1024)
    app.middlewares.append(origin_guard_middleware)
    app.middlewares.append(auth_failure_middleware)
    app.on_response_prepare.append(add_security_headers)
    app[APP_RUNTIME_KEY] = runtime or GatewayRuntime()
    auth_token = install_auth(app)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/api/discovery/scan", api_discovery_scan_handler)
    mount_static_routes(app)

    if bind_host is None:
        bind_host = os.environ.get("QANTARA_SPIKE_HOST", DEFAULT_HOST)
    if _is_non_loopback_bind(bind_host) and auth_token is None:
        LOGGER.warning(
            "qantara gateway is configured to listen on %s without QANTARA_AUTH_TOKEN; "
            "only loopback Host headers (plus QANTARA_ALLOWED_HOSTS) are accepted, so "
            "LAN clients receive 421 until you set a strong QANTARA_AUTH_TOKEN",
            bind_host or "all interfaces",
        )

    async def _on_startup(_app: web.Application) -> None:
        await app[APP_RUNTIME_KEY].start_mesh()
        await app[APP_RUNTIME_KEY].start_wyoming()

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(cleanup_bridge)
    return app


def _is_non_loopback_bind(host: str) -> bool:
    host = (host or "").strip().strip("[]")
    if host in {"", "0.0.0.0", "::"}:
        return True
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() not in {"localhost"}


def create_ssl_context() -> ssl.SSLContext | None:
    if not TLS_CERT_FILE or not TLS_KEY_FILE:
        return None
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(TLS_CERT_FILE, TLS_KEY_FILE)
    return context


if __name__ == "__main__":
    web.run_app(
        create_app(bind_host=DEFAULT_HOST),
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        ssl_context=create_ssl_context(),
    )
