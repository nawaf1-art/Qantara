"""Incremental parsers for streaming HTTP response bodies."""

from __future__ import annotations

import codecs
import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

DEFAULT_MAX_LINE_CHARS = 1024 * 1024


class StreamLimitError(ValueError):
    """Raised when a peer sends a stream line beyond the configured bound."""


def _consume_text_piece(
    piece: str,
    parts: list[str],
    pending_chars: int,
    max_line_chars: int,
) -> tuple[list[str], int]:
    start = 0
    completed_lines: list[str] = []
    while True:
        newline = piece.find("\n", start)
        if newline < 0:
            fragment = piece[start:]
            if pending_chars + len(fragment) > max_line_chars:
                raise StreamLimitError(
                    f"stream line exceeds {max_line_chars} characters"
                )
            if fragment:
                parts.append(fragment)
                pending_chars += len(fragment)
            return completed_lines, pending_chars

        fragment = piece[start:newline]
        if pending_chars + len(fragment) > max_line_chars:
            raise StreamLimitError(
                f"stream line exceeds {max_line_chars} characters"
            )
        if fragment:
            parts.append(fragment)
        completed_lines.append("".join(parts).rstrip("\r"))
        parts.clear()
        pending_chars = 0
        start = newline + 1


async def iter_text_lines(
    chunks: AsyncIterable[bytes],
    *,
    max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
) -> AsyncIterator[str]:
    """Yield bounded UTF-8 lines without assuming HTTP chunk boundaries."""
    if max_line_chars < 1:
        raise ValueError("max_line_chars must be positive")
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    parts: list[str] = []
    pending_chars = 0

    async for chunk in chunks:
        lines, pending_chars = _consume_text_piece(
            decoder.decode(chunk), parts, pending_chars, max_line_chars
        )
        for line in lines:
            yield line

    lines, pending_chars = _consume_text_piece(
        decoder.decode(b"", final=True), parts, pending_chars, max_line_chars
    )
    for line in lines:
        yield line
    if pending_chars:
        yield "".join(parts).rstrip("\r")


async def iter_ndjson_objects(
    chunks: AsyncIterable[bytes],
) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON objects from a newline-delimited response stream."""
    async for line in iter_text_lines(chunks):
        payload = line.strip()
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


async def iter_sse_json_objects(
    chunks: AsyncIterable[bytes],
) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON objects from single-line Server-Sent Events."""
    async for line in iter_text_lines(chunks):
        payload = line.strip()
        if not payload or payload.startswith(":"):
            continue
        if payload.startswith("data:"):
            payload = payload[5:].strip()
        else:
            continue
        if payload == "[DONE]":
            return
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event
