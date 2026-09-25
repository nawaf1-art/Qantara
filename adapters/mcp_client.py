from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import uuid
import weakref
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from adapters.base import (
    AdapterConfig,
    AdapterHealth,
    RuntimeAdapter,
    UnknownSessionError,
    make_activity_event,
)

MAX_TURNS_PER_SESSION = 24
MAX_MCP_TOOL_OUTPUT_CHARS = 1024 * 1024
MAX_MCP_ACTIVITY_CHARS = 4096
MAX_MCP_SESSION_ID_CHARS = 256
# Progress notifications are a glanceable strip; excess ones are dropped
# rather than blocking the shared MCP receive loop.
MAX_PENDING_PROGRESS_EVENTS = 32
PING_TIMEOUT_SECONDS = 5.0
CANCEL_NOTIFY_TIMEOUT_SECONDS = 2.0
CLOSE_TIMEOUT_SECONDS = 5.0
# Tool argument names that carry a conversation identity, in preference order.
SESSION_ID_ARGUMENT_KEYS = ("session_id", "sessionId", "conversation_id", "conversationId", "thread_id", "threadId")
# JSON-RPC codes that mean the transport, not the tool, failed.
_MCP_CONNECTION_CLOSED = -32000
_MCP_REQUEST_TIMEOUT = 408

SessionOpener = Callable[[], AbstractAsyncContextManager[Any]]


def _make_mcp_http_client_factory(
    host_header: str,
    server_hostname: str,
) -> Callable[..., Any]:
    import httpx

    class PinnedSNITransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self._transport = httpx.AsyncHTTPTransport(trust_env=False)

        async def handle_async_request(
            self,
            request: httpx.Request,
        ) -> httpx.Response:
            if server_hostname:
                request.extensions["sni_hostname"] = server_hostname
            return await self._transport.handle_async_request(request)

        async def aclose(self) -> None:
            await self._transport.aclose()

    def http_client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        request_headers = dict(headers or {})
        if host_header:
            request_headers["Host"] = host_header
        return httpx.AsyncClient(
            headers=request_headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=False,
            trust_env=False,
            transport=PinnedSNITransport(),
        )

    return http_client_factory


def _leaf_exception(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _mcp_error_code(exc: BaseException) -> int | None:
    error = getattr(exc, "error", None)
    code = getattr(error, "code", None)
    return code if isinstance(code, int) else None


def _readable_error(exc: BaseException) -> str:
    """Turn transport/SDK failures (often ExceptionGroups) into one clear line."""
    leaf = _leaf_exception(exc)
    error = getattr(leaf, "error", None)
    message = getattr(error, "message", None)
    if not isinstance(message, str) or not message:
        message = str(leaf).strip()
    name = type(leaf).__name__
    if not message:
        return name
    if isinstance(leaf, (OSError, EOFError)) or name in _TRANSPORT_ERROR_NAMES:
        return f"{name}: {message}"
    return message


_TRANSPORT_ERROR_NAMES = frozenset({"ClosedResourceError", "BrokenResourceError", "EndOfStream"})


def _is_connection_failure(exc: BaseException) -> bool:
    """True when the MCP connection (not the tool) failed and must be reopened."""
    if isinstance(exc, BaseExceptionGroup):
        return True
    code = _mcp_error_code(exc)
    if code is not None:
        return code in {_MCP_CONNECTION_CLOSED, _MCP_REQUEST_TIMEOUT}
    return isinstance(exc, (OSError, EOFError)) or type(exc).__name__ in _TRANSPORT_ERROR_NAMES


def _make_session_opener(
    *,
    transport: str,
    command: str,
    url: str,
    host_header: str,
    server_hostname: str,
    timeout_seconds: float,
    split_command: Callable[[str], list[str]],
) -> SessionOpener:
    """Build an opener that captures plain configuration, not the adapter.

    The long-lived connection task holds this opener; keeping the adapter
    out of it lets an abandoned adapter be garbage-collected and its
    connection stopped by a finalizer.
    """

    @asynccontextmanager
    async def opener() -> AsyncIterator[Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamablehttp_client
        except ModuleNotFoundError as exc:
            raise RuntimeError("mcp package is not installed; install mcp==1.28.*") from exc

        read_timeout = timedelta(seconds=timeout_seconds)
        if transport == "stdio":
            parts = split_command(command)
            if not parts:
                raise RuntimeError("QANTARA_MCP_COMMAND is required for stdio MCP transport")
            params = StdioServerParameters(command=parts[0], args=parts[1:])
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=read_timeout) as session:
                    yield session
            return

        if transport == "http":
            if not url:
                raise RuntimeError("QANTARA_MCP_URL is required for HTTP MCP transport")
            http_client_factory = _make_mcp_http_client_factory(host_header, server_hostname)
            async with streamablehttp_client(
                url,
                timeout=read_timeout,
                headers={"Host": host_header} if host_header else None,
                httpx_client_factory=http_client_factory,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=read_timeout) as session:
                    yield session
            return

        raise RuntimeError(f"unsupported MCP transport: {transport}")

    return opener


class _MCPConnection:
    """One initialized MCP client session, owned by a dedicated task.

    The MCP SDK's transports and sessions are anyio context managers that
    must be entered and exited in the same task, so a background task holds
    them open until ``close()``; turn tasks only send requests.
    """

    def __init__(self, opener: SessionOpener) -> None:
        self._opener = opener
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.session: Any = None
        self.error: BaseException | None = None
        self.broken = False
        self.tools: list[Any] | None = None

    @property
    def alive(self) -> bool:
        return (
            not self.broken
            and self.session is not None
            and self._task is not None
            and not self._task.done()
        )

    async def _run(self) -> None:
        try:
            async with self._opener() as session:
                await session.initialize()
                self.session = session
                self._ready.set()
                await self._stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - reported via self.error
            self.error = exc
        finally:
            self.session = None
            self.broken = True
            self._ready.set()

    async def start(self, timeout: float) -> None:
        self.loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except TimeoutError:
            await self.close()
            raise RuntimeError(f"MCP server did not initialize within {timeout:g} s") from None
        if self.session is None:
            await self.close()
            detail = _readable_error(self.error) if self.error else "connection closed during initialization"
            raise RuntimeError(f"could not connect to MCP server: {detail}")

    def request_stop_threadsafe(self) -> None:
        """Ask the owner task to exit; safe from finalizers and other threads."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(self._stop.set)

    async def close(self, timeout: float = CLOSE_TIMEOUT_SECONDS) -> None:
        self.broken = True
        self._stop.set()
        task = self._task
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            with contextlib.suppress(BaseException):
                await task

    async def list_tools(self) -> list[Any]:
        if self.tools is None:
            result = await self.session.list_tools()
            self.tools = list(result.tools)
        return self.tools


@dataclass
class _ActiveCall:
    task: asyncio.Task[str] | None = None
    connection: _MCPConnection | None = None
    request_id: int | None = None
    cancelled: bool = False
    progress: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_PENDING_PROGRESS_EVENTS)
    )


_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _retain(task: asyncio.Task[Any]) -> None:
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class MCPClientAdapter(RuntimeAdapter):
    """Agent-style MCP adapter.

    The adapter treats an MCP server as the downstream agent runtime: each
    finalized voice transcript becomes one call to a configured MCP chat tool.
    MCP remains control-plane only; audio stays in Qantara's WebSocket path.

    One MCP client session (one stdio process, or one streamable-HTTP
    session) is kept open per adapter and reused by every turn; it is
    reopened after a connection failure and released by ``aclose()``. The
    tool list is cached per connection. When the chat tool accepts a
    ``session_id``-style argument it receives a stable id per Qantara
    session (the browser's ``client_session_id`` when known). Cancelling a
    turn sends ``notifications/cancelled`` for the in-flight request.
    """

    def __init__(self, config: AdapterConfig | None = None) -> None:
        super().__init__(config or AdapterConfig(kind="mcp_client", name="mcp_client"))
        options = self.config.options
        self.transport = str(options.get("transport") or os.environ.get("QANTARA_MCP_TRANSPORT", "stdio")).strip().lower()
        self.command = str(options.get("command") or os.environ.get("QANTARA_MCP_COMMAND", "")).strip()
        self.url = str(options.get("url") or os.environ.get("QANTARA_MCP_URL", "")).strip().rstrip("/")
        self.outbound_host_header = str(options.get("outbound_host_header") or "")
        self.outbound_server_hostname = str(
            options.get("outbound_server_hostname") or ""
        )
        self.chat_tool = str(options.get("chat_tool") or os.environ.get("QANTARA_MCP_CHAT_TOOL", "chat")).strip()
        self.argument_key = str(options.get("argument_key") or os.environ.get("QANTARA_MCP_CHAT_ARG", "")).strip()
        self.timeout_seconds = float(options.get("timeout_seconds") or os.environ.get("QANTARA_MCP_TIMEOUT", "120"))
        self.max_sessions = int(options.get("max_sessions") or os.environ.get("QANTARA_MCP_MAX_SESSIONS", "64"))
        # Bounded: least-recently-used sessions are evicted beyond max_sessions;
        # turns within a session are capped at MAX_TURNS_PER_SESSION.
        self._sessions: dict[str, dict[str, Any]] = {}
        self._active_calls: dict[str, _ActiveCall] = {}
        self._connection: _MCPConnection | None = None
        self._connection_lock: asyncio.Lock | None = None
        self._connection_lock_loop: asyncio.AbstractEventLoop | None = None
        self._finalizer: weakref.finalize | None = None

    @property
    def available(self) -> bool:
        if self.transport == "stdio":
            return bool(self.command and self.chat_tool)
        if self.transport == "http":
            return bool(self.url and self.chat_tool)
        return False

    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        session_handle = str(uuid.uuid4())
        context = client_context or {}
        raw_key = context.get("client_session_id")
        session_key = raw_key.strip() if isinstance(raw_key, str) else ""
        self._sessions[session_handle] = {
            "client_context": context,
            "session_key": (session_key or session_handle)[:MAX_MCP_SESSION_ID_CHARS],
            "turns": {},
        }
        while len(self._sessions) > self.max_sessions:
            oldest_handle = next(iter(self._sessions))
            self._sessions.pop(oldest_handle, None)
        return session_handle

    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        if session_handle not in self._sessions:
            raise UnknownSessionError("unknown session handle")
        # Refresh recency so an actively used session is not the next evicted.
        self._sessions[session_handle] = self._sessions.pop(session_handle)
        turn_handle = str(uuid.uuid4())
        turns = self._sessions[session_handle]["turns"]
        turns[turn_handle] = {
            "transcript": transcript,
            "turn_context": turn_context or {},
        }
        while len(turns) > MAX_TURNS_PER_SESSION:
            oldest_turn = next(iter(turns))
            if oldest_turn == turn_handle:
                break
            turns.pop(oldest_turn, None)
        return turn_handle

    async def stream_assistant_output(
        self,
        session_handle: str,
        turn_handle: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if session_handle not in self._sessions:
            raise UnknownSessionError("unknown session handle")
        session_state = self._sessions[session_handle]
        turn = session_state["turns"].get(turn_handle)
        if turn is None:
            raise ValueError("unknown turn handle")

        active = _ActiveCall()

        async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
            # Runs on the shared MCP receive loop: never block it.
            with contextlib.suppress(asyncio.QueueFull):
                active.progress.put_nowait(self._activity_event(message, progress, total))

        call_task = active.task = asyncio.create_task(
            self._call_chat_tool(
                turn["transcript"],
                turn["turn_context"],
                progress_callback,
                session_state=session_state,
                active=active,
            )
        )
        self._active_calls[turn_handle] = active
        getter: asyncio.Task[dict[str, Any]] | None = None
        try:
            yield self._activity_event(f"Calling MCP tool `{self.chat_tool}`", None, None)
            while True:
                getter = asyncio.create_task(active.progress.get())
                await asyncio.wait({getter, call_task}, return_when=asyncio.FIRST_COMPLETED)
                if getter.done():
                    yield getter.result()
                    getter = None
                    continue
                getter.cancel()
                getter = None
                break
            while not active.progress.empty():
                yield active.progress.get_nowait()

            if active.cancelled or call_task.cancelled():
                yield {"type": "cancel_acknowledged"}
                return
            exc = call_task.exception()
            if exc is not None:
                yield {"type": "turn_failed", "message": _readable_error(exc) or "MCP tool call failed"}
                return
            text = call_task.result()
            if text:
                yield {"type": "assistant_text_delta", "text": text}
            yield {"type": "assistant_text_final", "text": text, "turn_handle": turn_handle}
        finally:
            if getter is not None:
                getter.cancel()
            self._active_calls.pop(turn_handle, None)
            if not call_task.done():
                # Consumer went away (gateway force-cancel): stop the call and
                # tell the server, without blocking the cancelling task.
                self._abort_call(active, "stream closed")

    def _abort_call(self, active: _ActiveCall, reason: str) -> None:
        active.cancelled = True
        _retain(asyncio.create_task(self._notify_cancelled(active, reason)))
        if active.task is not None:
            active.task.cancel()

    async def _notify_cancelled(self, active: _ActiveCall, reason: str) -> bool:
        connection = active.connection
        if connection is None or not connection.alive or active.request_id is None:
            return False
        try:
            from mcp import types
        except ModuleNotFoundError:
            return False
        notification = types.ClientNotification(
            types.CancelledNotification(
                params=types.CancelledNotificationParams(requestId=active.request_id, reason=reason),
            )
        )
        try:
            await asyncio.wait_for(
                connection.session.send_notification(notification),
                timeout=CANCEL_NOTIFY_TIMEOUT_SECONDS,
            )
        except Exception:
            return False
        return True

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, Any]:
        if session_handle not in self._sessions:
            raise UnknownSessionError("unknown session handle")
        active = self._active_calls.get(turn_handle)
        if active is None or active.task is None or active.task.done():
            return {
                "status": "acknowledged",
                "turn_handle": turn_handle,
                "detail": "no MCP tool call in flight for this turn",
            }
        active.cancelled = True
        reason = str((cancel_context or {}).get("reason") or "cancelled by Qantara")[:256]
        notified = await self._notify_cancelled(active, reason)
        active.task.cancel()
        return {
            "status": "acknowledged",
            "turn_handle": turn_handle,
            "mode": "notifications/cancelled" if notified else "local",
        }

    async def check_health(self) -> AdapterHealth:
        if not self.available:
            return AdapterHealth(status="degraded_but_usable", degraded=True, detail=self._missing_config_detail())
        try:
            tools = await self.list_tools()
        except Exception as exc:
            return AdapterHealth(status="degraded", degraded=True, detail=_readable_error(exc))
        tool_names = {tool["name"] for tool in tools}
        if self.chat_tool not in tool_names:
            return AdapterHealth(
                status="degraded",
                degraded=True,
                detail=f"MCP server does not expose chat tool {self.chat_tool!r}",
            )
        return AdapterHealth(status="ok", detail=f"{len(tools)} MCP tool(s) available")

    async def list_tools(self) -> list[dict[str, Any]]:
        """List the server's tools.

        Uses the long-lived connection when one is open (refreshing its
        cache); otherwise opens a short-lived session so one-off probes do
        not leave a server process running.
        """
        connection = self._connection
        if connection is not None and connection.alive and connection.loop is asyncio.get_running_loop():
            result = await connection.session.list_tools()
            connection.tools = list(result.tools)
            raw_tools = connection.tools
        else:
            async with self._open_session() as session:
                await session.initialize()
                raw_tools = list((await session.list_tools()).tools)
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in raw_tools
        ]

    def _lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._connection_lock is None or self._connection_lock_loop is not loop:
            self._connection_lock = asyncio.Lock()
            self._connection_lock_loop = loop
        return self._connection_lock

    async def _discard_connection(self, connection: _MCPConnection) -> None:
        if self._connection is connection:
            self._connection = None
            if self._finalizer is not None:
                self._finalizer.detach()
                self._finalizer = None
        if connection.loop is asyncio.get_running_loop():
            await connection.close()
        else:
            connection.request_stop_threadsafe()

    async def _get_connection(self) -> _MCPConnection:
        async with self._lock():
            connection = self._connection
            if connection is not None:
                if connection.alive and connection.loop is asyncio.get_running_loop():
                    if await self._ping(connection):
                        return connection
                await self._discard_connection(connection)
            connection = _MCPConnection(self._session_opener())
            await connection.start(timeout=self.timeout_seconds)
            self._connection = connection
            self._finalizer = weakref.finalize(self, connection.request_stop_threadsafe)
            return connection

    @staticmethod
    async def _ping(connection: _MCPConnection) -> bool:
        """Detect a server that died between turns before sending a real call."""
        try:
            await asyncio.wait_for(connection.session.send_ping(), timeout=PING_TIMEOUT_SECONDS)
        except Exception as exc:
            # A server that rejects ping but answers is still connected.
            code = _mcp_error_code(_leaf_exception(exc))
            if code is not None and code not in {_MCP_CONNECTION_CLOSED, _MCP_REQUEST_TIMEOUT}:
                return True
            connection.broken = True
            return False
        return True

    async def aclose(self) -> None:
        for active in list(self._active_calls.values()):
            if active.task is not None and not active.task.done():
                active.cancelled = True
                active.task.cancel()
        connection = self._connection
        if connection is not None:
            await self._discard_connection(connection)

    async def _call_chat_tool(
        self,
        transcript: str,
        turn_context: dict[str, Any],
        progress_callback: Callable[[float, float | None, str | None], Any],
        *,
        session_state: dict[str, Any] | None = None,
        active: _ActiveCall | None = None,
    ) -> str:
        connection = await self._get_connection()
        if active is not None:
            active.connection = connection
        try:
            tools = await connection.list_tools()
            selected_tool = next((tool for tool in tools if tool.name == self.chat_tool), None)
            if selected_tool is None:
                available = ", ".join(tool.name for tool in tools) or "none"
                raise RuntimeError(f"MCP chat tool {self.chat_tool!r} not found; available tools: {available}")
            arguments = self._build_tool_arguments(
                selected_tool.inputSchema,
                transcript,
                turn_context,
                session_state=session_state,
            )
            session = connection.session
            if session is None:
                raise RuntimeError("MCP connection closed")
            # The SDK assigns the next request id synchronously inside
            # call_tool (no await in between), so this is the id to cancel.
            request_id = getattr(session, "_request_id", None)
            if active is not None and isinstance(request_id, int):
                active.request_id = request_id
            result = await session.call_tool(
                self.chat_tool,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                progress_callback=progress_callback,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_connection_failure(exc):
                connection.broken = True
            raise RuntimeError(_readable_error(exc)) from exc
        text = self._extract_text(result)
        if getattr(result, "isError", False):
            raise RuntimeError(text or "MCP tool returned an error")
        if not text:
            raise RuntimeError("MCP tool returned no text content")
        if len(text) > MAX_MCP_TOOL_OUTPUT_CHARS:
            raise RuntimeError("MCP tool output exceeded the configured limit")
        return text

    def _session_opener(self) -> SessionOpener:
        return _make_session_opener(
            transport=self.transport,
            command=self.command,
            url=self.url,
            host_header=self.outbound_host_header,
            server_hostname=self.outbound_server_hostname,
            timeout_seconds=self.timeout_seconds,
            split_command=self._split_command,
        )

    def _open_session(self) -> AbstractAsyncContextManager[Any]:
        """Open a short-lived MCP client session (used for one-off probes)."""
        return self._session_opener()()

    def _build_tool_arguments(
        self,
        schema: dict[str, Any] | None,
        transcript: str,
        turn_context: dict[str, Any],
        *,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        properties = (schema or {}).get("properties") or {}
        text_key = self.argument_key or self._infer_text_argument(schema)
        arguments: dict[str, Any] = {text_key: transcript}
        if "turn_context" in properties:
            arguments["turn_context"] = turn_context
        elif "context" in properties:
            arguments["context"] = turn_context
        if session_state is not None:
            session_key = next((key for key in SESSION_ID_ARGUMENT_KEYS if key in properties), None)
            if session_key is not None and session_key != text_key:
                arguments[session_key] = session_state["session_key"]
            if "client_context" in properties:
                arguments["client_context"] = session_state["client_context"]
        return arguments

    @staticmethod
    def _infer_text_argument(schema: dict[str, Any] | None) -> str:
        properties = (schema or {}).get("properties") or {}
        required = (schema or {}).get("required") or []
        preferred = ["message", "prompt", "input", "query", "text", "transcript"]
        for key in preferred:
            if key in properties:
                return key
        required_string_keys = [
            key for key in required if (properties.get(key) or {}).get("type") == "string"
        ]
        if len(required_string_keys) == 1:
            return required_string_keys[0]
        return "message"

    @staticmethod
    def _extract_text(result: Any) -> str:
        chunks: list[str] = []
        total = 0
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text:
                total += len(text) + (1 if chunks else 0)
                if total > MAX_MCP_TOOL_OUTPUT_CHARS:
                    raise RuntimeError("MCP tool output exceeded the configured limit")
                chunks.append(text)
        if chunks:
            return "\n".join(chunks).strip()
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            for key in ("text", "message", "response", "result"):
                value = structured.get(key)
                if isinstance(value, str) and value.strip():
                    clean = value.strip()
                    if len(clean) > MAX_MCP_TOOL_OUTPUT_CHARS:
                        raise RuntimeError(
                            "MCP tool output exceeded the configured limit"
                        )
                    return clean
            encoded_chunks: list[str] = []
            total = 0
            for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(structured):
                total += len(chunk)
                if total > MAX_MCP_TOOL_OUTPUT_CHARS:
                    raise RuntimeError("MCP tool output exceeded the configured limit")
                encoded_chunks.append(chunk)
            return "".join(encoded_chunks)
        return ""

    def _activity_event(
        self,
        summary: str | None,
        progress: float | None,
        total: float | None,
    ) -> dict[str, Any]:
        ratio = None
        if progress is not None and total:
            ratio = max(0.0, min(1.0, progress / total))
        elif progress is not None and 0 <= progress <= 1:
            ratio = progress
        return make_activity_event(
            activity_type="tool_call",
            summary=(summary or "MCP tool activity")[:MAX_MCP_ACTIVITY_CHARS],
            progress=ratio,
            tool_name=self.chat_tool or None,
        )

    def _missing_config_detail(self) -> str:
        if self.transport == "stdio":
            return "QANTARA_MCP_COMMAND and QANTARA_MCP_CHAT_TOOL are required for stdio MCP"
        if self.transport == "http":
            return "QANTARA_MCP_URL and QANTARA_MCP_CHAT_TOOL are required for HTTP MCP"
        return f"unsupported MCP transport: {self.transport}"

    @staticmethod
    def _split_command(command: str, *, windows: bool | None = None) -> list[str]:
        is_windows = os.name == "nt" if windows is None else windows
        parts = shlex.split(command, posix=not is_windows)
        if not is_windows:
            return parts
        return [
            part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'} else part
            for part in parts
        ]
