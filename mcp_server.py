from __future__ import annotations

import os
from typing import Any

import aiohttp
from mcp.server.fastmcp import FastMCP


def _gateway_base_url() -> str:
    return os.environ.get("QANTARA_GATEWAY_URL", "http://127.0.0.1:8765").strip().rstrip("/")


def _gateway_token() -> str:
    return (
        os.environ.get("QANTARA_GATEWAY_TOKEN")
        or os.environ.get("QANTARA_AUTH_TOKEN")
        or ""
    ).strip()


async def _gateway_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    token = _gateway_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = aiohttp.ClientTimeout(total=float(os.environ.get("QANTARA_MCP_SERVER_TIMEOUT", "30")))
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        url = f"{_gateway_base_url()}{path}"
        async with session.request(method, url, json=payload) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = {"error": await resp.text()}
            if resp.status >= 400:
                detail = data.get("error") or data
                raise RuntimeError(f"gateway returned {resp.status}: {detail}")
            return data


mcp = FastMCP(
    "qantara-voice",
    instructions="Control a local Qantara browser voice session. Audio remains in Qantara; MCP is control-plane only.",
    log_level=os.environ.get("QANTARA_MCP_SERVER_LOG_LEVEL", "ERROR"),
    host=os.environ.get("QANTARA_MCP_SERVER_HOST", "127.0.0.1"),
    port=int(os.environ.get("QANTARA_MCP_SERVER_PORT", "8766")),
    streamable_http_path=os.environ.get("QANTARA_MCP_SERVER_PATH", "/mcp"),
)


@mcp.tool(name="voice_get_status")
async def voice_get_status() -> dict[str, Any]:
    """Return active Qantara browser voice sessions and playback state."""
    return await _gateway_request("GET", "/api/control/voice/status")


@mcp.tool(name="voice_speak")
async def voice_speak(
    text: str,
    session_id: str | None = None,
    client_session_id: str | None = None,
    voice_id: str | None = None,
    interrupt: bool = False,
) -> dict[str, Any]:
    """Speak text through an active Qantara browser voice session."""
    return await _gateway_request(
        "POST",
        "/api/control/voice/speak",
        {
            "text": text,
            "session_id": session_id,
            "client_session_id": client_session_id,
            "voice_id": voice_id,
            "interrupt": interrupt,
        },
    )


@mcp.tool(name="voice_interrupt")
async def voice_interrupt(
    session_id: str | None = None,
    client_session_id: str | None = None,
) -> dict[str, Any]:
    """Stop active Qantara playback or generation for a browser voice session."""
    return await _gateway_request(
        "POST",
        "/api/control/voice/interrupt",
        {
            "session_id": session_id,
            "client_session_id": client_session_id,
        },
    )


@mcp.tool(name="voice_set_voice")
async def voice_set_voice(
    voice_id: str,
    session_id: str | None = None,
    client_session_id: str | None = None,
) -> dict[str, Any]:
    """Set the playback voice for a Qantara browser voice session."""
    return await _gateway_request(
        "POST",
        "/api/control/voice/set_voice",
        {
            "voice_id": voice_id,
            "session_id": session_id,
            "client_session_id": client_session_id,
        },
    )


def main() -> None:
    transport = os.environ.get("QANTARA_MCP_SERVER_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", "streamable-http", "http"}:
        raise SystemExit(f"unsupported QANTARA_MCP_SERVER_TRANSPORT: {transport}")
    mcp.run("streamable-http" if transport == "http" else transport)


if __name__ == "__main__":
    main()
