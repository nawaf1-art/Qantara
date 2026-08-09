from __future__ import annotations

import asyncio
import json
import os
import shlex
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter, make_activity_event

MAX_TURNS_PER_SESSION = 24
MAX_MCP_TOOL_OUTPUT_CHARS = 1024 * 1024
MAX_MCP_ACTIVITY_CHARS = 4096


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


class MCPClientAdapter(RuntimeAdapter):
    """Agent-style MCP adapter.

    The adapter treats an MCP server as the downstream agent runtime: each
    finalized voice transcript becomes one call to a configured MCP chat tool.
    MCP remains control-plane only; audio stays in Qantara's WebSocket path.
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

    @property
    def available(self) -> bool:
        if self.transport == "stdio":
            return bool(self.command and self.chat_tool)
        if self.transport == "http":
            return bool(self.url and self.chat_tool)
        return False

    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        session_handle = str(uuid.uuid4())
        self._sessions[session_handle] = {
            "client_context": client_context or {},
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
            raise ValueError("unknown session handle")
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
            raise ValueError("unknown session handle")
        turn = self._sessions[session_handle]["turns"].get(turn_handle)
        if turn is None:
            raise ValueError("unknown turn handle")

        # Backpressure prevents a noisy MCP server from accumulating an
        # unbounded number of progress notifications in gateway memory.
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)

        async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
            await queue.put(self._activity_event(message, progress, total))

        async def run_call() -> None:
            try:
                await queue.put(self._activity_event(f"Calling MCP tool `{self.chat_tool}`", None, None))
                text = await self._call_chat_tool(
                    turn["transcript"],
                    turn["turn_context"],
                    progress_callback,
                )
                if len(text) > MAX_MCP_TOOL_OUTPUT_CHARS:
                    raise RuntimeError("MCP tool output exceeded the configured limit")
                await queue.put({"type": "_result", "text": text})
            except Exception as exc:
                await queue.put({"type": "_error", "message": str(exc)})

        task = asyncio.create_task(run_call())
        try:
            while True:
                item = await queue.get()
                if item["type"] == "_result":
                    text = item.get("text", "")
                    if text:
                        yield {"type": "assistant_text_delta", "text": text}
                    yield {"type": "assistant_text_final", "text": text, "turn_handle": turn_handle}
                    return
                if item["type"] == "_error":
                    yield {"type": "turn_failed", "message": item.get("message", "MCP tool call failed")}
                    return
                yield item
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, Any]:
        if session_handle not in self._sessions:
            raise ValueError("unknown session handle")
        return {
            "status": "acknowledged",
            "turn_handle": turn_handle,
            "cancel_context": cancel_context or {},
            "detail": "MCP tool calls are per-turn; cancellation is local to Qantara playback for now",
        }

    async def check_health(self) -> AdapterHealth:
        if not self.available:
            return AdapterHealth(status="degraded_but_usable", degraded=True, detail=self._missing_config_detail())
        try:
            tools = await self.list_tools()
        except Exception as exc:
            return AdapterHealth(status="degraded", degraded=True, detail=str(exc))
        tool_names = {tool["name"] for tool in tools}
        if self.chat_tool not in tool_names:
            return AdapterHealth(
                status="degraded",
                degraded=True,
                detail=f"MCP server does not expose chat tool {self.chat_tool!r}",
            )
        return AdapterHealth(status="ok", detail=f"{len(tools)} MCP tool(s) available")

    async def list_tools(self) -> list[dict[str, Any]]:
        async with self._open_session() as session:
            await session.initialize()
            result = await session.list_tools()
            tools = []
            for tool in result.tools:
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema,
                    }
                )
            return tools

    async def _call_chat_tool(
        self,
        transcript: str,
        turn_context: dict[str, Any],
        progress_callback: Callable[[float, float | None, str | None], Any],
    ) -> str:
        async with self._open_session() as session:
            await session.initialize()
            tools_result = await session.list_tools()
            selected_tool = next((tool for tool in tools_result.tools if tool.name == self.chat_tool), None)
            if selected_tool is None:
                available = ", ".join(tool.name for tool in tools_result.tools) or "none"
                raise RuntimeError(f"MCP chat tool {self.chat_tool!r} not found; available tools: {available}")
            arguments = self._build_tool_arguments(selected_tool.inputSchema, transcript, turn_context)
            result = await session.call_tool(
                self.chat_tool,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                progress_callback=progress_callback,
            )
            text = self._extract_text(result)
            if getattr(result, "isError", False):
                raise RuntimeError(text or "MCP tool returned an error")
            if not text:
                raise RuntimeError("MCP tool returned no text content")
            return text

    @asynccontextmanager
    async def _open_session(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamablehttp_client
        except ModuleNotFoundError as exc:
            raise RuntimeError("mcp package is not installed; install mcp==1.28.*") from exc

        read_timeout = timedelta(seconds=self.timeout_seconds)
        if self.transport == "stdio":
            parts = self._split_command(self.command)
            if not parts:
                raise RuntimeError("QANTARA_MCP_COMMAND is required for stdio MCP transport")
            params = StdioServerParameters(command=parts[0], args=parts[1:])
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=read_timeout) as session:
                    yield session
            return

        if self.transport == "http":
            if not self.url:
                raise RuntimeError("QANTARA_MCP_URL is required for HTTP MCP transport")
            http_client_factory = _make_mcp_http_client_factory(
                self.outbound_host_header,
                self.outbound_server_hostname,
            )

            async with streamablehttp_client(
                self.url,
                timeout=read_timeout,
                headers={"Host": self.outbound_host_header}
                if self.outbound_host_header
                else None,
                httpx_client_factory=http_client_factory,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=read_timeout) as session:
                    yield session
            return

        raise RuntimeError(f"unsupported MCP transport: {self.transport}")

    def _build_tool_arguments(
        self,
        schema: dict[str, Any] | None,
        transcript: str,
        turn_context: dict[str, Any],
    ) -> dict[str, Any]:
        properties = (schema or {}).get("properties") or {}
        text_key = self.argument_key or self._infer_text_argument(schema)
        arguments: dict[str, Any] = {text_key: transcript}
        if "turn_context" in properties:
            arguments["turn_context"] = turn_context
        elif "context" in properties:
            arguments["context"] = turn_context
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
