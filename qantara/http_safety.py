"""Bounded readers for HTTP responses received from backend services."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_MAX_HTTP_RESPONSE_BYTES = 1024 * 1024


class HTTPResponseLimitError(RuntimeError):
    """Raised when an HTTP response exceeds its configured byte limit."""


async def read_bounded_response_bytes(
    response: Any,
    *,
    limit: int = DEFAULT_MAX_HTTP_RESPONSE_BYTES,
) -> bytes:
    """Read an HTTP response body without buffering more than ``limit`` bytes."""
    if limit < 0:
        raise ValueError("response byte limit must be non-negative")

    content = getattr(response, "content", None)
    if content is None:
        raise TypeError("response does not expose a content stream")

    body = bytearray()
    reader = getattr(content, "read", None)
    if callable(reader):
        while True:
            remaining = limit - len(body)
            chunk = await reader(min(64 * 1024, remaining + 1))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > limit:
                raise HTTPResponseLimitError(
                    f"HTTP response exceeded the {limit}-byte limit"
                )
    else:
        async for chunk in content:
            body.extend(chunk)
            if len(body) > limit:
                raise HTTPResponseLimitError(
                    f"HTTP response exceeded the {limit}-byte limit"
                )

    return bytes(body)


def decode_response_bytes(response: Any, body: bytes) -> str:
    """Decode response bytes using its declared charset, falling back to UTF-8."""
    encoding = getattr(response, "charset", None) or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def read_bounded_response_text(
    response: Any,
    *,
    limit: int = DEFAULT_MAX_HTTP_RESPONSE_BYTES,
) -> str:
    """Read and decode a response body with a strict byte limit."""
    body = await read_bounded_response_bytes(response, limit=limit)
    return decode_response_bytes(response, body)


async def read_bounded_response_json(
    response: Any,
    *,
    limit: int = DEFAULT_MAX_HTTP_RESPONSE_BYTES,
) -> Any:
    """Read and parse a JSON response body with a strict byte limit."""
    body = await read_bounded_response_bytes(response, limit=limit)
    return json.loads(body)
