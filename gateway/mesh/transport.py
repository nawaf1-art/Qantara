from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from gateway.mesh.protocol import MeshMessage, decode_message

LOGGER = logging.getLogger(__name__)

OnMessageHandler = Callable[[MeshMessage, tuple[str, int]], Awaitable[None]]


class MeshServer:
    """JSONL-over-TCP server. One instance per Qantara node — accepts
    inbound peer connections, decodes frames, hands them to the
    registered on_message handler."""

    def __init__(
        self,
        host: str,
        port: int,
        on_message: OnMessageHandler,
    ) -> None:
        self._host = host
        self._port = port
        self._on_message = on_message
        self._server: asyncio.base_events.Server | None = None

    @property
    def sockets(self):  # type: ignore[no-untyped-def]
        return self._server.sockets if self._server else []

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_connection, self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        addr = writer.get_extra_info("peername") or ("<unknown>", 0)
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    raw = json.loads(text)
                    msg = decode_message(raw)
                except (ValueError, json.JSONDecodeError) as exc:
                    LOGGER.debug("mesh: dropping malformed frame from %s: %s", addr, exc)
                    continue
                try:
                    await self._on_message(msg, addr)
                except Exception:
                    LOGGER.exception("mesh: on_message handler raised; dropping frame")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


class MeshPeer:
    """Outbound peer connection. One instance per remote peer we want
    to send to. Connects on demand, reconnects on drop (caller's
    responsibility — reconnection policy lives in the MeshController)."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self._writer is not None and not self._writer.is_closing():
                return
            _, writer = await asyncio.open_connection(self._host, self._port)
            self._writer = writer

    async def send(self, msg: MeshMessage) -> None:
        async with self._lock:
            if self._writer is None or self._writer.is_closing():
                raise ConnectionError(f"mesh peer {self._host}:{self._port} not connected")
            line = (json.dumps(msg.to_dict()) + "\n").encode("utf-8")
            self._writer.write(line)
            await self._writer.drain()

    async def close(self) -> None:
        async with self._lock:
            if self._writer is None:
                return
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
