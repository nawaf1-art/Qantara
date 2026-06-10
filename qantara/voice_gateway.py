"""Programmatic entry point for the Qantara gateway.

This is a thin facade over the gateway server: the same aiohttp application
that `make spike-run` serves, constructed in-process so any Python program
can embed Qantara. Configuration beyond host/port flows through the same
QANTARA_* environment variables documented in docs/CONFIGURATION.md.
"""

from __future__ import annotations

from aiohttp import web


class VoiceGateway:
    """The Qantara voice gateway as an embeddable object.

    Args:
        host: Interface to bind. Keep the loopback default unless you have
            set QANTARA_AUTH_TOKEN — exposing the gateway on a LAN without a
            token logs a startup warning.
        port: TCP port for the HTTP/WebSocket server.
        runtime: Optional pre-built GatewayRuntime. When omitted, the runtime
            is created from environment configuration on first use.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        runtime: object | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._runtime = runtime

    def create_app(self) -> web.Application:
        """Build the gateway aiohttp application without starting a server.

        Use this to mount Qantara inside an existing aiohttp deployment or
        an aiohttp test harness.
        """
        from gateway.transport_spike.server import create_app

        return create_app(self._runtime)

    def run(self) -> None:
        """Start the gateway and block until interrupted.

        TLS is picked up from QANTARA_TLS_CERT / QANTARA_TLS_KEY when set,
        matching the standalone server behavior.
        """
        from gateway.transport_spike.server import create_ssl_context

        web.run_app(
            self.create_app(),
            host=self.host,
            port=self.port,
            ssl_context=create_ssl_context(),
        )
