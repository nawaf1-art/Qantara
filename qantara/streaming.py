"""Incremental parsers for streaming HTTP response bodies."""

from __future__ import annotations

import codecs
import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any


async def iter_text_lines(chunks: AsyncIterable[bytes]) -> AsyncIterator[str]:
    """Yield complete UTF-8 lines without assuming HTTP chunk boundaries."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buffer = ""

    async for chunk in chunks:
        buffer += decoder.decode(chunk)
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield line.rstrip("\r")

    buffer += decoder.decode(b"", final=True)
    if buffer:
        yield buffer.rstrip("\r")


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
