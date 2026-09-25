from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from gateway.mesh.protocol import MeshMessage, decode_message, sign_frame, verify_frame

LOGGER = logging.getLogger(__name__)

OnMessageHandler = Callable[[MeshMessage, tuple[str, int]], Awaitable[None]]

# One mesh frame is a few hundred bytes; anything past this is not a peer.
MAX_FRAME_BYTES = 64 * 1024
# A sleeping or firewalled peer must not stall the voice loop (audit Q-12).
DEFAULT_CONNECT_TIMEOUT_S = 0.5

# Indirection so tests can simulate unreachable peers without real traffic.
_open_connection = asyncio.open_connection


class MeshServer:
    """JSONL-over-TCP server. One instance per Qantara node — accepts
    inbound peer connections, decodes frames, hands them to the
    registered on_message handler."""

    def __init__(
        self,
        host: str,
        port: int,
        on_message: OnMessageHandler,
        token: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._on_message = on_message
        self._token = token or None
        self._server: asyncio.base_events.Server | None = None
        # Open inbound connections. stop() must close these explicitly:
        # wait_closed() waits for connection handlers to finish, and a
        # handler blocks in readline() until its peer hangs up.
        self._connections: set[asyncio.StreamWriter] = set()
        # Closing connections is not enough on its own. asyncio attaches the
        # transport at accept time -- so wait_closed() already counts the
        # connection -- but the handler task registers itself in
        # _connections only once its body is scheduled. A stop() landing in
        # that gap would close nothing and then hang on a handler that goes
        # on to park in readline(). This flag closes the gap: a handler that
        # starts after stop() bails out instead of reading.
        self._closing = False

    @property
    def sockets(self):  # type: ignore[no-untyped-def]
        return self._server.sockets if self._server else []

    async def start(self) -> None:
        self._closing = False
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port, limit=MAX_FRAME_BYTES,
        )

    async def stop(self) -> None:
        if self._server is not None:
            # Everything up to wait_closed() is synchronous, so it cannot
            # interleave with a handler's own await-free registration block.
            # A handler therefore either registered before the snapshot below
            # (and is closed here) or observes _closing and bails out.
            self._closing = True
            self._server.close()
            for writer in list(self._connections):
                writer.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        addr = writer.get_extra_info("peername") or ("<unknown>", 0)
        self._connections.add(writer)
        if self._closing:
            # stop() already took its snapshot; do not park in readline(),
            # or wait_closed() would never return.
            self._connections.discard(writer)
            writer.close()
            return
        try:
            while not reader.at_eof():
                try:
                    line = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError, ConnectionError, OSError) as exc:
                    # Oversized line (StreamReader limit) or a broken socket.
                    LOGGER.debug("mesh: closing connection from %s: %s", addr, exc)
                    break
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = self._decode(text)
                except Exception as exc:  # noqa: BLE001 - untrusted input must never raise out
                    # Close rather than keep reading: a well-behaved peer never
                    # sends these, and dropping line by line lets one socket
                    # flood the log (audit ME-10).
                    LOGGER.debug("mesh: closing connection from %s after bad frame: %s", addr, exc)
                    break
                try:
                    await self._on_message(msg, addr)
                except Exception:
                    LOGGER.exception("mesh: on_message handler raised; dropping frame")
        finally:
            self._connections.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _decode(self, text: str) -> MeshMessage:
        raw = json.loads(text)
        if self._token is not None:
            raw = verify_frame(raw, self._token)
        return decode_message(raw)


class MeshPeer:
    """Outbound peer connection. One instance per remote peer we want
    to send to. Connects on demand, reconnects on drop (caller's
    responsibility — reconnection policy lives in the MeshController)."""

    def __init__(
        self,
        host: str,
        port: int,
        token: str | None = None,
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    ) -> None:
        self._host = host
        self._port = port
        self._token = token or None
        self._connect_timeout_s = connect_timeout_s
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self._writer is not None and not self._writer.is_closing():
                return
            _, writer = await asyncio.wait_for(
                _open_connection(self._host, self._port),
                timeout=self._connect_timeout_s,
            )
            self._writer = writer

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def send(self, msg: MeshMessage) -> None:
        async with self._lock:
            writer = self._writer
            if writer is None or writer.is_closing():
                raise ConnectionError(f"mesh peer {self._host}:{self._port} not connected")
            frame = msg.to_dict()
            if self._token is not None:
                frame = sign_frame(frame, self._token)
            line = (json.dumps(frame) + "\n").encode("utf-8")
            writer.write(line)
            await writer.drain()

    async def close(self) -> None:
        # Deliberately lock-free: a send() stuck in drain() on an unresponsive
        # peer holds the lock, and close() must still be able to tear down.
        writer, self._writer = self._writer, None
        if writer is None:
            return
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=self._connect_timeout_s)
        except Exception:
            writer.transport.abort()

    def abort(self) -> None:
        """Drop the connection immediately, discarding unsent data."""
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.transport.abort()
