from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter


class SessionGatewayHTTPAdapter(RuntimeAdapter):
    """
    Generic session-oriented backend adapter over HTTP.

    This is Qantara's first concrete backend contract target. It stays
    deployment-agnostic by relying on a small configurable HTTP shape.
    """

    def __init__(self, config: AdapterConfig | None = None) -> None:
        super().__init__(config or AdapterConfig(kind="session_gateway_http", name="session-gateway-http"))
        self.base_url = self.config.options.get("base_url") or os.environ.get("QANTARA_BACKEND_BASE_URL", "").rstrip("/")
        self.auth_token = self.config.options.get("auth_token") or os.environ.get("QANTARA_BACKEND_TOKEN")
        self.timeout_seconds = float(self.config.options.get("timeout_seconds") or os.environ.get("QANTARA_BACKEND_TIMEOUT", "30"))

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _parse_stream_line(line: str) -> dict[str, Any] | None:
        payload = line.strip()
        if not payload:
            return None
        if payload.startswith("data: "):
            payload = payload[6:]
        elif payload.startswith("data:"):
            payload = payload[5:]
        payload = payload.strip()
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("session gateway backend base URL is not configured")

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method,
                self._url(path),
                json=payload,
                headers=self._headers(),
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"backend request failed: {response.status} {body}".strip())
                if not body:
                    return {}
                return json.loads(body)

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

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                self._url(f"/sessions/{session_handle}/turns/{turn_handle}/events"),
                headers=self._headers(),
            ) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError(f"backend stream failed: {response.status} {body}".strip())

                buffer = ""
                async for chunk in response.content:
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        event = self._parse_stream_line(line)
                        if event is not None:
                            yield event
                if buffer.strip():
                    event = self._parse_stream_line(buffer)
                    if event is not None:
                        yield event

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
