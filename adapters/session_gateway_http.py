from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter, UnknownSessionError
from qantara.http_safety import (
    DEFAULT_MAX_HTTP_RESPONSE_BYTES,
    read_bounded_response_text,
)
from qantara.streaming import iter_text_lines, sse_error_object

MAX_BACKEND_JSON_BYTES = DEFAULT_MAX_HTTP_RESPONSE_BYTES
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_IDLE_TIMEOUT_SECONDS = 90.0
# Upper bound for the best-effort cancel sent after an idle timeout.
MAX_TIMEOUT_CANCEL_SECONDS = 5.0


class BackendIdleTimeoutError(RuntimeError):
    """The backend sent nothing on the event stream for the idle timeout."""


def _float_option(*values: Any, fallback: float) -> float:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return fallback


class SessionGatewayHTTPAdapter(RuntimeAdapter):
    """
    Generic session-oriented backend adapter over HTTP.

    Implements the client side of protocols/session-gateway-http.md. It stays
    deployment-agnostic by relying on a small configurable HTTP shape.

    Timeouts: short JSON requests use ``timeout_seconds`` as a total bound.
    The event stream has no total bound; it fails only when the backend is
    silent for ``idle_timeout_seconds`` (backends send keep-alives while they
    work), and the adapter then asks the backend to cancel the turn.
    """

    def __init__(self, config: AdapterConfig | None = None) -> None:
        super().__init__(config or AdapterConfig(kind="session_gateway_http", name="session-gateway-http"))
        options = self.config.options
        self.base_url = (options.get("base_url") or os.environ.get("QANTARA_BACKEND_BASE_URL", "")).rstrip("/")
        self.auth_token = options.get("auth_token") or os.environ.get("QANTARA_BACKEND_TOKEN")
        self.timeout_seconds = _float_option(
            options.get("timeout_seconds"),
            os.environ.get("QANTARA_BACKEND_TIMEOUT"),
            fallback=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        self.connect_timeout_seconds = _float_option(
            options.get("connect_timeout_seconds"),
            os.environ.get("QANTARA_BACKEND_CONNECT_TIMEOUT"),
            fallback=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        )
        self.idle_timeout_seconds = _float_option(
            options.get("idle_timeout_seconds"),
            os.environ.get("QANTARA_BACKEND_IDLE_TIMEOUT"),
            fallback=DEFAULT_IDLE_TIMEOUT_SECONDS,
        )
        self.outbound_host_header = str(
            options.get("outbound_host_header") or ""
        )
        self.outbound_server_hostname = str(
            options.get("outbound_server_hostname") or ""
        )
        # One HTTP client per adapter (and event loop), reused across the
        # session/turn/events/cancel requests of every turn.
        self._http: aiohttp.ClientSession | None = None
        self._http_loop: asyncio.AbstractEventLoop | None = None

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if self.outbound_host_header:
            headers["Host"] = self.outbound_host_header
        return headers

    def _request_kwargs(self) -> dict[str, str]:
        if self.outbound_server_hostname:
            return {"server_hostname": self.outbound_server_hostname}
        return {}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _client(self) -> aiohttp.ClientSession:
        loop = asyncio.get_running_loop()
        if self._http is None or self._http.closed or self._http_loop is not loop:
            self._http = aiohttp.ClientSession(trust_env=False)
            self._http_loop = loop
        return self._http

    async def aclose(self) -> None:
        http, self._http = self._http, None
        self._http_loop = None
        if http is not None and not http.closed:
            await http.close()

    @staticmethod
    def _parse_stream_line(line: str) -> dict[str, Any] | None:
        payload = line.strip()
        if not payload or payload.startswith(":"):
            return None
        if payload.startswith("error:"):
            error = sse_error_object(payload[6:].strip())["error"]
            return {"type": "turn_failed", "message": str(error.get("message") or error)}
        if payload.startswith("event:"):
            return None
        if payload.startswith("data:"):
            payload = payload[5:]
        payload = payload.strip()
        if not payload:
            return None
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict):
            return None
        if "type" not in event and event.get("error"):
            error = event["error"]
            message = error.get("message") if isinstance(error, dict) else error
            return {"type": "turn_failed", "message": str(message or "backend error")}
        return event

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("session gateway backend base URL is not configured")

        timeout = aiohttp.ClientTimeout(total=timeout_seconds or self.timeout_seconds)
        async with self._client().request(
            method,
            self._url(path),
            json=payload,
            headers=self._headers(),
            allow_redirects=False,
            timeout=timeout,
            **self._request_kwargs(),
        ) as response:
            body = await read_bounded_response_text(
                response,
                limit=MAX_BACKEND_JSON_BYTES,
            )
            if response.status >= 400:
                message = f"backend request failed: {response.status} {body}".strip()
                if response.status == 404 and "unknown session" in body.lower():
                    raise UnknownSessionError(message)
                raise RuntimeError(message)
            if not body:
                return {}
            data = json.loads(body)
            if not isinstance(data, dict):
                raise RuntimeError("backend response must be a JSON object")
            return data

    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        data = await self._request_json("POST", "/sessions", {"client_context": client_context or {}})
        session_handle = data.get("session_handle")
        if not session_handle:
            raise RuntimeError("backend did not return session_handle")
        return session_handle

    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        data = await self._request_json(
            "POST",
            f"/sessions/{session_handle}/turns",
            {"transcript": transcript, "turn_context": turn_context or {}},
        )
        turn_handle = data.get("turn_handle")
        if not turn_handle:
            raise RuntimeError("backend did not return turn_handle")
        return turn_handle

    async def stream_assistant_output(
        self,
        session_handle: str,
        turn_handle: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self.available:
            raise RuntimeError("session gateway backend base URL is not configured")

        # No total bound: long agent turns are fine as long as the backend
        # keeps the stream alive. Silence longer than the idle timeout fails.
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=self.connect_timeout_seconds,
            sock_read=self.idle_timeout_seconds,
        )
        try:
            async with self._client().get(
                self._url(f"/sessions/{session_handle}/turns/{turn_handle}/events"),
                headers=self._headers(),
                allow_redirects=False,
                timeout=timeout,
                **self._request_kwargs(),
            ) as response:
                if response.status >= 400:
                    body = await read_bounded_response_text(
                        response,
                        limit=MAX_BACKEND_JSON_BYTES,
                    )
                    message = f"backend stream failed: {response.status} {body}".strip()
                    if response.status == 404 and "unknown session" in body.lower():
                        raise UnknownSessionError(message)
                    raise RuntimeError(message)

                async for line in iter_text_lines(response.content):
                    event = self._parse_stream_line(line)
                    if event is not None:
                        yield event
        except aiohttp.ConnectionTimeoutError as exc:
            raise RuntimeError(
                f"backend connection timed out after {self.connect_timeout_seconds:g} s"
            ) from exc
        except (aiohttp.ServerTimeoutError, TimeoutError):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    self.cancel_turn(session_handle, turn_handle, {"reason": "idle_timeout"}),
                    timeout=min(MAX_TIMEOUT_CANCEL_SECONDS, self.timeout_seconds),
                )
            raise BackendIdleTimeoutError(
                f"backend sent no events for {self.idle_timeout_seconds:g} s; the turn was cancelled "
                "(raise QANTARA_BACKEND_IDLE_TIMEOUT for backends that stay silent longer)"
            ) from None

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"/sessions/{session_handle}/turns/{turn_handle}/cancel",
            {"cancel_context": cancel_context or {}},
        )

    async def check_health(self) -> AdapterHealth:
        if not self.available:
            return AdapterHealth(
                status="degraded_but_usable",
                degraded=True,
                detail="QANTARA_BACKEND_BASE_URL is not configured",
            )

        try:
            data = await self._request_json("GET", "/health")
        except Exception as exc:
            return AdapterHealth(
                status="degraded_but_usable",
                degraded=True,
                detail=str(exc),
            )

        status = data.get("status", "ok")
        detail = data.get("detail")
        return AdapterHealth(status=status, detail=detail, degraded=status != "ok")
