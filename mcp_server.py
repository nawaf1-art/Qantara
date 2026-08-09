from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp
from mcp.server.fastmcp import FastMCP

from qantara.http_safety import read_bounded_response_text

REPO_ROOT = Path(__file__).resolve().parent


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
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
        trust_env=False,
    ) as session:
        url = f"{_gateway_base_url()}{path}"
        async with session.request(
            method,
            url,
            json=payload,
            allow_redirects=False,
        ) as resp:
            body = await read_bounded_response_text(resp)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                if resp.status < 400:
                    raise RuntimeError("gateway returned invalid JSON") from None
                data = {"error": body}
            if resp.status >= 400:
                detail = (data.get("error") or data) if isinstance(data, dict) else data
                detail = str(detail)[:4096]
                raise RuntimeError(f"gateway returned {resp.status}: {detail}")
            if not isinstance(data, dict):
                raise RuntimeError("gateway returned a non-object JSON response")
            return data


def _json_resource(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


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


@mcp.tool(name="voice_session_start")
async def voice_session_start(
    session_id: str | None = None,
    client_session_id: str | None = None,
    browser_url: str = "/spike",
) -> dict[str, Any]:
    """Return an active browser session or instructions for opening one."""
    return await _gateway_request(
        "POST",
        "/api/control/voice/session_start",
        {
            "session_id": session_id,
            "client_session_id": client_session_id,
            "browser_url": browser_url,
        },
    )


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


@mcp.tool(name="voice_get_transcript")
async def voice_get_transcript(
    session_id: str | None = None,
    client_session_id: str | None = None,
) -> dict[str, Any]:
    """Return the recent transcript and event timeline for a browser voice session."""
    return await _gateway_request(
        "POST",
        "/api/control/voice/transcript",
        {
            "session_id": session_id,
            "client_session_id": client_session_id,
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


@mcp.tool(name="voice_set_translation_mode")
async def voice_set_translation_mode(
    mode: str | None,
    source: str | None = None,
    target: str | None = None,
    session_id: str | None = None,
    client_session_id: str | None = None,
) -> dict[str, Any]:
    """Set translation mode for an active Qantara browser voice session."""
    return await _gateway_request(
        "POST",
        "/api/control/voice/set_translation_mode",
        {
            "mode": mode,
            "source": source,
            "target": target,
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


@mcp.resource(
    "qantara://voices",
    name="qantara_voices",
    description="Configured Qantara TTS engine and available voices.",
    mime_type="application/json",
)
async def qantara_voices() -> str:
    return _json_resource(await _gateway_request("GET", "/api/tts"))


@mcp.resource(
    "qantara://languages",
    name="qantara_languages",
    description="Qantara launch language catalog and TTS availability.",
    mime_type="application/json",
)
async def qantara_languages() -> str:
    return _json_resource(await _gateway_request("GET", "/api/languages"))


@mcp.resource(
    "qantara://avatars",
    name="qantara_avatars",
    description="Qantara avatar preset catalog.",
    mime_type="application/json",
)
async def qantara_avatars() -> str:
    path = REPO_ROOT / "identity" / "avatar-packs" / "presets.json"
    return path.read_text(encoding="utf-8")


@mcp.resource(
    "qantara://sessions",
    name="qantara_sessions",
    description="Active Qantara browser voice sessions.",
    mime_type="application/json",
)
async def qantara_sessions() -> str:
    return _json_resource(await _gateway_request("GET", "/api/control/voice/status"))


@mcp.resource(
    "qantara://sessions/{session_id}/status",
    name="qantara_session_status",
    description="Status for one Qantara browser voice session.",
    mime_type="application/json",
)
async def qantara_session_status(session_id: str) -> str:
    status = await _gateway_request("GET", "/api/control/voice/status")
    sessions = status.get("sessions", [])
    matched = [session for session in sessions if session.get("session_id") == session_id]
    return _json_resource({"ok": bool(matched), "session": matched[0] if matched else None})


@mcp.resource(
    "qantara://sessions/{session_id}/transcript",
    name="qantara_session_transcript",
    description="Recent transcript and event timeline for one Qantara browser voice session.",
    mime_type="application/json",
)
async def qantara_session_transcript(session_id: str) -> str:
    quoted = quote(session_id, safe="")
    return _json_resource(await _gateway_request("GET", f"/api/control/voice/transcript?session_id={quoted}"))


@mcp.resource(
    "qantara://mesh/peers",
    name="qantara_mesh_peers",
    description="Configured Qantara mesh peer status.",
    mime_type="application/json",
)
async def qantara_mesh_peers() -> str:
    return _json_resource(await _gateway_request("GET", "/api/mesh/peers"))


def _is_loopback_host(host: str) -> bool:
    host = (host or "").strip().strip("[]")
    if host in {"127.0.0.1", "::1", "localhost", ""}:
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _require_safe_http_binding(transport: str, host: str) -> None:
    """Refuse to expose the MCP control plane on a non-loopback interface.

    The MCP HTTP/streamable-http transport serves voice control tools
    (voice_speak, voice_interrupt, voice_set_voice, ...) with no inbound
    authentication, so binding it to a LAN-reachable address lets any device on
    the network drive the user's live microphone session. Require an explicit
    QANTARA_MCP_SERVER_ALLOW_INSECURE=1 opt-in for that configuration.
    """
    if transport in {"http", "streamable-http"} and not _is_loopback_host(host):
        opt_in = os.environ.get("QANTARA_MCP_SERVER_ALLOW_INSECURE", "").strip().lower()
        if opt_in not in {"1", "true", "yes", "on"}:
            raise SystemExit(
                f"Refusing to start MCP {transport!r} transport on non-loopback host {host!r}: "
                "the MCP server exposes voice control (speak/interrupt/set_voice) with no inbound "
                "authentication. Bind QANTARA_MCP_SERVER_HOST to 127.0.0.1, or set "
                "QANTARA_MCP_SERVER_ALLOW_INSECURE=1 to override on a trusted network."
            )


def main() -> None:
    transport = os.environ.get("QANTARA_MCP_SERVER_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", "streamable-http", "http"}:
        raise SystemExit(f"unsupported QANTARA_MCP_SERVER_TRANSPORT: {transport}")
    host = os.environ.get("QANTARA_MCP_SERVER_HOST", "127.0.0.1")
    _require_safe_http_binding(transport, host)
    mcp.run("streamable-http" if transport == "http" else transport)


if __name__ == "__main__":
    main()
