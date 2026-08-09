from __future__ import annotations

import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from adapters.base import AdapterConfig
from adapters.openai_compatible import OpenAICompatibleAdapter
from adapters.session_gateway_http import SessionGatewayHTTPAdapter
from qantara.http_safety import (
    DEFAULT_MAX_HTTP_RESPONSE_BYTES,
    HTTPResponseLimitError,
    read_bounded_response_json,
    read_bounded_response_text,
)


class _ChunkedResponse:
    charset = "utf-8"

    def __init__(self, chunks: list[bytes]) -> None:
        self.content = self._chunks(chunks)

    async def _chunks(self, chunks: list[bytes]):
        for chunk in chunks:
            yield chunk


class OutboundHTTPSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_reader_handles_split_json(self) -> None:
        response = _ChunkedResponse([b'{"status":', b'"ok"}'])
        self.assertEqual(
            await read_bounded_response_json(response),
            {"status": "ok"},
        )

    async def test_bounded_reader_rejects_oversized_async_stream(self) -> None:
        response = _ChunkedResponse([b"1234", b"5"])
        with self.assertRaises(HTTPResponseLimitError):
            await read_bounded_response_text(response, limit=4)

    async def test_session_gateway_does_not_follow_redirect(self) -> None:
        leaked = False

        async def redirect(_: web.Request) -> web.Response:
            raise web.HTTPFound("/leak")

        async def leak(_: web.Request) -> web.Response:
            nonlocal leaked
            leaked = True
            return web.json_response({"status": "ok"})

        app = web.Application()
        app.router.add_get("/health", redirect)
        app.router.add_get("/leak", leak)
        server = TestServer(app)
        await server.start_server()
        try:
            adapter = SessionGatewayHTTPAdapter(
                AdapterConfig(
                    kind="session_gateway_http",
                    name="redirect-test",
                    options={"base_url": str(server.make_url("")).rstrip("/")},
                )
            )
            health = await adapter.check_health()
        finally:
            await server.close()

        self.assertFalse(leaked)
        self.assertTrue(health.degraded)

    async def test_session_gateway_preserves_original_host_after_ip_pin(self) -> None:
        observed_host = ""

        async def health(request: web.Request) -> web.Response:
            nonlocal observed_host
            observed_host = request.host
            return web.json_response({"status": "ok"})

        app = web.Application()
        app.router.add_get("/health", health)
        server = TestServer(app)
        await server.start_server()
        server_port = server.port
        try:
            adapter = SessionGatewayHTTPAdapter(
                AdapterConfig(
                    kind="session_gateway_http",
                    name="virtual-host-test",
                    options={
                        "base_url": str(server.make_url("")).rstrip("/"),
                        "outbound_host_header": f"backend.local:{server_port}",
                        "outbound_server_hostname": "backend.local",
                    },
                )
            )
            health_result = await adapter.check_health()
        finally:
            await server.close()

        self.assertEqual(observed_host, f"backend.local:{server_port}")
        self.assertFalse(health_result.degraded)

    async def test_openai_adapter_does_not_follow_model_redirect(self) -> None:
        leaked = False

        async def redirect(_: web.Request) -> web.Response:
            raise web.HTTPFound("/leak")

        async def leak(_: web.Request) -> web.Response:
            nonlocal leaked
            leaked = True
            return web.json_response({"data": [{"id": "leaked-model"}]})

        app = web.Application()
        app.router.add_get("/v1/models", redirect)
        app.router.add_get("/models", redirect)
        app.router.add_get("/leak", leak)
        server = TestServer(app)
        await server.start_server()
        try:
            adapter = OpenAICompatibleAdapter(
                AdapterConfig(
                    kind="openai_compatible",
                    name="redirect-test",
                    options={"base_url": str(server.make_url("")).rstrip("/")},
                )
            )
            health = await adapter.check_health()
        finally:
            await server.close()

        self.assertFalse(leaked)
        self.assertTrue(health.degraded)

    async def test_openai_adapter_preserves_original_host_after_ip_pin(self) -> None:
        observed_host = ""

        async def models(request: web.Request) -> web.Response:
            nonlocal observed_host
            observed_host = request.host
            return web.json_response({"data": [{"id": "local-model"}]})

        app = web.Application()
        app.router.add_get("/v1/models", models)
        server = TestServer(app)
        await server.start_server()
        server_port = server.port
        try:
            adapter = OpenAICompatibleAdapter(
                AdapterConfig(
                    kind="openai_compatible",
                    name="virtual-host-test",
                    options={
                        "base_url": str(server.make_url("")).rstrip("/"),
                        "outbound_host_header": f"models.local:{server_port}",
                        "outbound_server_hostname": "models.local",
                    },
                )
            )
            health_result = await adapter.check_health()
        finally:
            await server.close()

        self.assertEqual(observed_host, f"models.local:{server_port}")
        self.assertFalse(health_result.degraded)

    async def test_openai_adapter_rejects_oversized_model_response(self) -> None:
        async def oversized(_: web.Request) -> web.Response:
            return web.Response(body=b"x" * (DEFAULT_MAX_HTTP_RESPONSE_BYTES + 1))

        app = web.Application()
        app.router.add_get("/v1/models", oversized)
        server = TestServer(app)
        await server.start_server()
        try:
            adapter = OpenAICompatibleAdapter(
                AdapterConfig(
                    kind="openai_compatible",
                    name="oversized-test",
                    options={"base_url": str(server.make_url("")).rstrip("/")},
                )
            )
            health = await adapter.check_health()
        finally:
            await server.close()

        self.assertTrue(health.degraded)
        self.assertIn("exceeded", health.detail)


if __name__ == "__main__":
    unittest.main()
