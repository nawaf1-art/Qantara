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
    ADMIN_TOKEN_KEY,
    AUTH_SESSION_TOKEN_KEY,
    AUTH_TOKEN_KEY,
    load_auth_token,
    new_auth_session_token,
)
from gateway.transport_spike.common import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    TLS_CERT_FILE,
    TLS_KEY_FILE,
)
from gateway.transport_spike.http_api import cleanup_bridge, mount_static_routes  # noqa: E402
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


def create_app(runtime: GatewayRuntime | None = None) -> web.Application:
    app = web.Application()
    app[APP_RUNTIME_KEY] = runtime or GatewayRuntime()
    auth_token = load_auth_token("QANTARA_AUTH_TOKEN")
    app[AUTH_TOKEN_KEY] = auth_token
    app[AUTH_SESSION_TOKEN_KEY] = new_auth_session_token(auth_token)
    app[ADMIN_TOKEN_KEY] = load_auth_token("QANTARA_ADMIN_TOKEN")
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/api/discovery/scan", api_discovery_scan_handler)
    mount_static_routes(app)

    bind_host = os.environ.get("QANTARA_SPIKE_HOST", DEFAULT_HOST)
    if _is_non_loopback_bind(bind_host) and auth_token is None:
        LOGGER.warning(
            "qantara gateway is configured to listen on %s without QANTARA_AUTH_TOKEN; "
            "set a strong token before exposing Qantara on a LAN",
            bind_host,
        )

    async def _on_startup(_app: web.Application) -> None:
        await app[APP_RUNTIME_KEY].start_mesh()
        await app[APP_RUNTIME_KEY].start_wyoming()

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(cleanup_bridge)
    return app


def _is_non_loopback_bind(host: str) -> bool:
    if host in {"", "0.0.0.0", "::"}:
        return True
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host not in {"localhost"}


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
