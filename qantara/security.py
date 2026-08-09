"""Small, shared helpers for privacy-safe diagnostics and public metadata."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)
_CONTENT_KEYS = frozenset(
    {
        "arguments",
        "content",
        "detail",
        "error",
        "message",
        "messages",
        "parameters",
        "prompt",
        "prompts",
        "query",
        "queries",
        "summary",
        "text",
        "transcript",
        "transcripts",
    }
)
_URL_KEYS = frozenset({"uri", "url"})
BRIDGE_SECRET_ENV_NAMES = frozenset(
    {
        "QANTARA_ADMIN_TOKEN",
        "QANTARA_AUTH_TOKEN",
        "QANTARA_GATEWAY_TOKEN",
        "QANTARA_MESH_TOKEN",
    }
)


def _key_matches(key: object, candidates: frozenset[str]) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in candidates or any(
        normalized.startswith(f"{candidate}_") or normalized.endswith(f"_{candidate}")
        for candidate in candidates
    )


def _content_marker(value: object) -> str:
    if isinstance(value, str):
        return f"<redacted:{len(value)} chars>"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<redacted:{len(value)} bytes>"
    if isinstance(value, (list, tuple, set, Mapping)):
        return f"<redacted:{len(value)} items>"
    return "<redacted>"


def redact_for_logging(value: Any, *, key: object | None = None) -> Any:
    """Return a JSON-safe copy with secrets and free-form content removed.

    Runtime event sinks still receive the original event contract. This helper
    is used only by Qantara's default stdout diagnostics so transcripts, model
    output, tool arguments, and credentials are content-free by default.
    """
    if key is not None and _key_matches(key, _SECRET_KEYS):
        return "<redacted>"
    if key is not None and _key_matches(key, _CONTENT_KEYS):
        return _content_marker(value)
    if key is not None and _key_matches(key, _URL_KEYS):
        if isinstance(value, str):
            return sanitize_public_url(value) or "<redacted>"
        return _content_marker(value)
    if isinstance(value, Mapping):
        return {str(item_key): redact_for_logging(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_for_logging(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def sanitize_public_url(raw_url: str) -> str:
    """Strip credentials, query data, and fragments from a displayed URL."""
    if not raw_url:
        return ""
    try:
        parsed = urlsplit(raw_url)
        host = parsed.hostname
        if not parsed.scheme or not host:
            return ""
        display_host = f"[{host}]" if ":" in host else host
        if parsed.port is not None:
            display_host = f"{display_host}:{parsed.port}"
        return urlunsplit((parsed.scheme, display_host, parsed.path, "", ""))
    except ValueError:
        return ""


def bridge_subprocess_environment(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy the environment without gateway-only credentials."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in BRIDGE_SECRET_ENV_NAMES
    }
    if overrides:
        env.update(
            {
                key: value
                for key, value in overrides.items()
                if key not in BRIDGE_SECRET_ENV_NAMES
            }
        )
    return env
