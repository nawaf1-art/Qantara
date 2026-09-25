"""Async client for a running gateway's voice control API.

Drive an active browser voice session from Python — speak text, stop
playback, or inspect sessions — through ``/api/control/voice/*``:

    import asyncio
    from qantara.control import VoiceControl

    async def main() -> None:
        async with VoiceControl("http://127.0.0.1:8765", token="...") as voice:
            print(await voice.status())
            await voice.speak("Hello from Python", interrupt=True)

    asyncio.run(main())

The gateway only speaks through a connected browser session; the client
cannot capture a microphone by itself. When several sessions are active,
pass ``session_id`` or ``client_session_id`` to pick one. The token is the
gateway's ``QANTARA_AUTH_TOKEN`` (omit it for a loopback gateway without one).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from qantara.http_safety import read_bounded_response_text

__all__ = ["VoiceControl", "VoiceControlError"]


class VoiceControlError(RuntimeError):
    """The gateway rejected a control request or returned an invalid reply."""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


class VoiceControl:
    """Minimal async client mirroring ``/api/control/voice/*``.

    Args:
        base_url: Gateway origin, e.g. ``http://127.0.0.1:8765``.
        token: Bearer token (``QANTARA_AUTH_TOKEN``); optional on loopback.
        timeout: Total per-request timeout in seconds.
        session: Optional caller-owned ``aiohttp.ClientSession`` to reuse.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        token: str | None = None,
        *,
        timeout: float = 30.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        parts = urlsplit(base_url.strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("base_url must be an http(s) URL such as http://127.0.0.1:8765")
        if parts.username or parts.password:
            raise ValueError("base_url must not embed credentials; pass token= instead")
        self.base_url = base_url.strip().rstrip("/")
        self._token = (token or "").strip() or None
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> VoiceControl:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
        self._session = None

    def _client(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # trust_env=False: never route control traffic via proxy env vars.
            self._session = aiohttp.ClientSession(timeout=self._timeout, trust_env=False)
            self._owns_session = True
        return self._session

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        async with self._client().request(
            method,
            f"{self.base_url}{path}",
            json=payload,
            headers=headers,
            allow_redirects=False,
        ) as response:
            body = await read_bounded_response_text(response)
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                raise VoiceControlError(
                    f"gateway returned non-JSON response ({response.status})", status=response.status
                ) from None
            if response.status >= 400 or (isinstance(data, dict) and data.get("ok") is False):
                detail = data.get("error") if isinstance(data, dict) else None
                raise VoiceControlError(
                    f"gateway returned {response.status}: {detail or 'request failed'}",
                    status=response.status,
                    payload=data,
                )
            if not isinstance(data, dict):
                raise VoiceControlError("gateway returned a non-object JSON response", status=response.status)
            return data

    @staticmethod
    def _target(session_id: str | None, client_session_id: str | None) -> dict[str, Any]:
        target: dict[str, Any] = {}
        if session_id:
            target["session_id"] = session_id
        if client_session_id:
            target["client_session_id"] = client_session_id
        return target

    async def status(self) -> dict[str, Any]:
        """Return ``{"ok": True, "active_session_count": N, "sessions": [...]}``."""
        return await self._request("GET", "/api/control/voice/status")

    async def speak(
        self,
        text: str,
        voice_id: str | None = None,
        interrupt: bool = False,
        *,
        session_id: str | None = None,
        client_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Queue ``text`` for playback; ``interrupt=True`` cancels current speech first."""
        if not text or not text.strip():
            raise ValueError("text must not be empty")
        payload: dict[str, Any] = {"text": text, "interrupt": bool(interrupt)}
        if voice_id:
            payload["voice_id"] = voice_id
        payload.update(self._target(session_id, client_session_id))
        return await self._request("POST", "/api/control/voice/speak", payload)

    async def interrupt(
        self,
        *,
        session_id: str | None = None,
        client_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Stop playback and cancel the active turn."""
        return await self._request(
            "POST", "/api/control/voice/interrupt", self._target(session_id, client_session_id)
        )
