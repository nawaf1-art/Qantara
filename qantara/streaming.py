"""Incremental parsers and writers for streaming HTTP bodies.

The line bound below is owned here, not by aiohttp: callers may pass an
``aiohttp.StreamReader`` (``response.content``) directly and it is read with
``iter_any()``, so aiohttp's ~128 KiB ``readline()`` limit never applies.
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import json
import re
import time
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
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

    # aiohttp.StreamReader iterates with readline(), which enforces its own
    # smaller line limit. Read raw chunks instead so this bound applies.
    iter_any = getattr(chunks, "iter_any", None)
    source: AsyncIterable[bytes] = iter_any() if callable(iter_any) else chunks

    async for chunk in source:
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


def sse_error_object(payload: str) -> dict[str, Any]:
    """Normalize an SSE error payload (JSON or plain text) to ``{"error": {...}}``."""
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        inner = parsed.get("error", parsed)
        if isinstance(inner, dict):
            return {"error": inner}
        if isinstance(inner, str) and inner:
            return {"error": {"message": inner}}
        return {"error": parsed}
    return {"error": {"message": payload or "stream error"}}


async def iter_sse_json_objects(
    chunks: AsyncIterable[bytes],
) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON objects from single-line Server-Sent Events.

    Error frames are surfaced as ``{"error": {...}}`` objects so callers treat
    them as failures: llama.cpp-style ``error:`` field lines and
    ``event: error`` frames followed by ``data:``.
    """
    event_name = ""
    async for line in iter_text_lines(chunks):
        payload = line.strip()
        if not payload:
            event_name = ""
            continue
        if payload.startswith(":"):
            continue
        if payload.startswith("event:"):
            event_name = payload[6:].strip().lower()
            continue
        if payload.startswith("error:"):
            yield sse_error_object(payload[6:].strip())
            continue
        if not payload.startswith("data:"):
            continue
        payload = payload[5:].strip()
        if payload == "[DONE]":
            return
        if not payload:
            continue
        if event_name == "error":
            yield sse_error_object(payload)
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


_REASONING_TAG_RE = re.compile(r"<(/?)(?:think|thinking)>", re.IGNORECASE)
_REASONING_CLOSE_RE = re.compile(r"</(?:think|thinking)>", re.IGNORECASE)
_REASONING_TAGS = ("<think>", "<thinking>", "</think>", "</thinking>")
_CLOSE_TAGS = ("</think>", "</thinking>")


def _partial_tag_start(text: str, tags: tuple[str, ...]) -> int:
    """Return where a possibly incomplete tag starts at the end of text, or -1."""
    index = text.rfind("<")
    if index < 0:
        return -1
    suffix = text[index:].lower()
    if any(len(suffix) < len(tag) and tag.startswith(suffix) for tag in tags):
        return index
    return -1


class ReasoningTagFilter:
    """Streaming filter that removes inline ``<think>``/``<thinking>`` blocks.

    Some OpenAI-compatible servers (vLLM without a reasoning parser, llama.cpp
    ``--reasoning-format none``, LM Studio) inline chain-of-thought in the
    answer text. Tags may be split across chunks; only a possible partial tag
    (at most 11 characters) is held back while it is undecided.

    ``start_inside=True`` handles chat templates that put the opening tag in
    the prompt, so the stream starts inside reasoning and only a closing tag
    appears: everything before the first closing tag is withheld. If the
    stream ends without one, the held text is released as the answer.

    In the default mode a stray closing tag drops what is still pending and
    sets ``saw_stray_close`` so callers can use ``start_inside`` for later
    turns. Text already returned cannot be recalled.
    """

    def __init__(self, *, start_inside: bool = False) -> None:
        self._state = "leading" if start_inside else "outside"
        self._buffer = ""
        self._strip_leading_whitespace = False
        self.saw_reasoning = False
        self.saw_stray_close = False

    def _emit(self, text: str, out: list[str]) -> None:
        if self._strip_leading_whitespace:
            text = text.lstrip()
            if not text:
                return
            self._strip_leading_whitespace = False
        out.append(text)

    def _close_block(self) -> None:
        self.saw_reasoning = True
        self._state = "outside"
        self._strip_leading_whitespace = True

    def _open_block(self) -> None:
        self.saw_reasoning = True
        self._state = "inside"

    def feed(self, text: str) -> str:
        """Consume a chunk and return the text that is safe to show."""
        if not text:
            return ""
        self._buffer += text
        out: list[str] = []
        while self._buffer:
            if self._state == "inside":
                match = _REASONING_CLOSE_RE.search(self._buffer)
                if match is None:
                    partial = _partial_tag_start(self._buffer, _CLOSE_TAGS)
                    self._buffer = self._buffer[partial:] if partial >= 0 else ""
                    break
                self._buffer = self._buffer[match.end():]
                self._close_block()
                continue

            match = _REASONING_TAG_RE.search(self._buffer)
            if self._state == "leading":
                if match is None:
                    break  # hold until a closing tag or the end of the stream
                before = self._buffer[: match.start()]
                self._buffer = self._buffer[match.end():]
                if match.group(1):
                    self._close_block()
                else:
                    if before.strip():
                        # Visible text came first: it was not a reasoning prefix.
                        self._emit(before, out)
                    self._open_block()
                continue

            if match is None:
                partial = _partial_tag_start(self._buffer, _REASONING_TAGS)
                if partial >= 0:
                    ready, self._buffer = self._buffer[:partial], self._buffer[partial:]
                else:
                    ready, self._buffer = self._buffer, ""
                if ready:
                    self._emit(ready, out)
                break
            before = self._buffer[: match.start()]
            self._buffer = self._buffer[match.end():]
            if match.group(1):
                # Closing tag without an opening one: the pending text was
                # reasoning that started before the stream did.
                self.saw_stray_close = True
                self._close_block()
            else:
                if before:
                    self._emit(before, out)
                self._open_block()
        return "".join(out)

    def flush(self) -> str:
        """Return any held text at the end of the stream."""
        held, self._buffer = self._buffer, ""
        if self._state == "inside" or not held:
            return ""
        out: list[str] = []
        self._emit(held, out)
        return "".join(out)


class NDJSONEventWriter:
    """Serialize events as UTF-8 NDJSON lines, with an optional keep-alive.

    The session bridges use this so a long, silent backend turn still sends a
    line at least every ``keepalive_seconds``. The gateway's idle (socket
    read) timeout then measures silence rather than total turn length. Writes
    are serialized so keep-alives never interleave with real events.
    """

    def __init__(
        self,
        write: Callable[[bytes], Awaitable[Any]],
        *,
        keepalive_seconds: float = 0.0,
        keepalive_event: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._write = write
        self._keepalive_seconds = keepalive_seconds
        self._keepalive_event = keepalive_event
        self._lock = asyncio.Lock()
        self._last_write = time.monotonic()
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    @staticmethod
    def encode(event: dict[str, Any]) -> bytes:
        return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

    async def send(self, event: dict[str, Any]) -> None:
        data = self.encode(event)
        async with self._lock:
            await self._write(data)
            self._last_write = time.monotonic()

    async def _keepalive_loop(self) -> None:
        interval = self._keepalive_seconds
        while not self._closed:
            delay = self._last_write + interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
                continue
            if self._keepalive_event is None:
                return
            try:
                await self.send(self._keepalive_event())
            except Exception:
                return  # peer went away; the handler notices on its next write

    def start(self) -> None:
        if (
            self._task is None
            and not self._closed
            and self._keepalive_seconds > 0
            and self._keepalive_event is not None
        ):
            self._last_write = time.monotonic()
            self._task = asyncio.create_task(self._keepalive_loop())

    async def stop(self) -> None:
        self._closed = True
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def __aenter__(self) -> NDJSONEventWriter:
        self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()
