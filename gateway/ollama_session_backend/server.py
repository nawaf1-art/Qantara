from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field

import aiohttp
from aiohttp import web


DEFAULT_HOST = os.environ.get("QANTARA_REAL_BACKEND_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("QANTARA_REAL_BACKEND_PORT", "19120"))
OLLAMA_BASE_URL = os.environ.get("QANTARA_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("QANTARA_OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_KEEP_ALIVE = os.environ.get("QANTARA_OLLAMA_KEEP_ALIVE", "15m")
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("QANTARA_OLLAMA_TIMEOUT", "120"))
SYSTEM_PROMPT = os.environ.get(
    "QANTARA_OLLAMA_SYSTEM_PROMPT",
    (
        "You are a concise conversational voice assistant. "
        "Respond naturally in short spoken-style sentences. "
        "Do not use markdown, lists, or formatting."
    ),
)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class TurnState:
    transcript: str
    turn_context: dict
    created_at: str = field(default_factory=utc_now)
    cancelled: bool = False
    final_text: str = ""


@dataclass
class SessionState:
    client_context: dict
    created_at: str = field(default_factory=utc_now)
    turns: dict[str, TurnState] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)


class OllamaSessionBackend:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}

    def create_session(self, client_context: dict | None = None) -> str:
        session_handle = str(uuid.uuid4())
        self.sessions[session_handle] = SessionState(
            client_context=client_context or {},
            history=[{"role": "system", "content": SYSTEM_PROMPT}],
        )
        return session_handle

    def create_turn(self, session_handle: str, transcript: str, turn_context: dict | None = None) -> str:
        if session_handle not in self.sessions:
            raise KeyError("unknown session handle")
        turn_handle = str(uuid.uuid4())
        self.sessions[session_handle].turns[turn_handle] = TurnState(
            transcript=transcript,
            turn_context=turn_context or {},
        )
        return turn_handle


BACKEND = OllamaSessionBackend()


async def health_handler(_: web.Request) -> web.Response:
    detail = f"ollama session backend ready ({OLLAMA_MODEL})"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{OLLAMA_BASE_URL}/api/tags") as response:
                if response.status >= 400:
                    return web.json_response({"status": "degraded", "detail": detail}, status=200)
    except Exception as exc:
        return web.json_response({"status": "degraded", "detail": f"{detail}; ollama unavailable: {exc}"}, status=200)
    return web.json_response({"status": "ok", "detail": detail})


async def create_session_handler(request: web.Request) -> web.Response:
    payload = await request.json()
    session_handle = BACKEND.create_session(payload.get("client_context"))
    return web.json_response({"session_handle": session_handle})


async def create_turn_handler(request: web.Request) -> web.Response:
    session_handle = request.match_info["session_handle"]
    if session_handle not in BACKEND.sessions:
        return web.json_response({"error": "unknown session handle"}, status=404)

    payload = await request.json()
    transcript = (payload.get("transcript") or "").strip()
    if not transcript:
        return web.json_response({"error": "empty transcript"}, status=400)

    turn_handle = BACKEND.create_turn(session_handle, transcript, payload.get("turn_context"))
    return web.json_response({"turn_handle": turn_handle})


async def _ollama_stream_messages(session_state: SessionState, transcript: str):
    messages = [*session_state.history, {"role": "user", "content": transcript}]
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }

    timeout = aiohttp.ClientTimeout(total=OLLAMA_TIMEOUT_SECONDS)
    client = aiohttp.ClientSession(timeout=timeout)
    response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
    return client, response


async def stream_turn_events_handler(request: web.Request) -> web.StreamResponse:
    session_handle = request.match_info["session_handle"]
    turn_handle = request.match_info["turn_handle"]

    if session_handle not in BACKEND.sessions:
        return web.json_response({"error": "unknown session handle"}, status=404)
    session_state = BACKEND.sessions[session_handle]
    if turn_handle not in session_state.turns:
        return web.json_response({"error": "unknown turn handle"}, status=404)
    turn = session_state.turns[turn_handle]

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)

    client: aiohttp.ClientSession | None = None
    upstream: aiohttp.ClientResponse | None = None
    full_text = ""
    try:
        client, upstream = await _ollama_stream_messages(session_state, turn.transcript)
        if upstream.status >= 400:
            body = await upstream.text()
            await response.write((json.dumps({"type": "turn_failed", "message": body or f"ollama error {upstream.status}"}) + "\n").encode("utf-8"))
            await response.write_eof()
            return response

        async for chunk in upstream.content:
            if turn.cancelled:
                await response.write((json.dumps({"type": "cancel_acknowledged", "turn_handle": turn_handle}) + "\n").encode("utf-8"))
                await response.write_eof()
                return response

            line = chunk.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            if payload.get("done"):
                break

            delta = ((payload.get("message") or {}).get("content")) or ""
            if not delta:
                continue

            full_text += delta
            await response.write((json.dumps({"type": "assistant_text_delta", "text": delta, "turn_handle": turn_handle}) + "\n").encode("utf-8"))

        if turn.cancelled:
            await response.write((json.dumps({"type": "cancel_acknowledged", "turn_handle": turn_handle}) + "\n").encode("utf-8"))
            await response.write_eof()
            return response

        turn.final_text = full_text.strip()
        if turn.final_text:
            session_state.history.append({"role": "user", "content": turn.transcript})
            session_state.history.append({"role": "assistant", "content": turn.final_text})
            await response.write(
                (json.dumps({"type": "assistant_text_final", "text": turn.final_text, "turn_handle": turn_handle}) + "\n").encode("utf-8")
            )
        await response.write((json.dumps({"type": "turn_completed", "turn_handle": turn_handle}) + "\n").encode("utf-8"))
        await response.write_eof()
        return response
    except Exception as exc:
        await response.write((json.dumps({"type": "turn_failed", "message": str(exc), "turn_handle": turn_handle}) + "\n").encode("utf-8"))
        await response.write_eof()
        return response
    finally:
        if upstream is not None:
            upstream.close()
        if client is not None:
            await client.close()


async def cancel_turn_handler(request: web.Request) -> web.Response:
    session_handle = request.match_info["session_handle"]
    turn_handle = request.match_info["turn_handle"]

    if session_handle not in BACKEND.sessions:
        return web.json_response({"error": "unknown session handle"}, status=404)
    if turn_handle not in BACKEND.sessions[session_handle].turns:
        return web.json_response({"error": "unknown turn handle"}, status=404)

    BACKEND.sessions[session_handle].turns[turn_handle].cancelled = True
    return web.json_response({"status": "acknowledged", "mode": "best_effort"})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_post("/sessions", create_session_handler)
    app.router.add_post("/sessions/{session_handle}/turns", create_turn_handler)
    app.router.add_get("/sessions/{session_handle}/turns/{turn_handle}/events", stream_turn_events_handler)
    app.router.add_post("/sessions/{session_handle}/turns/{turn_handle}/cancel", cancel_turn_handler)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=DEFAULT_HOST, port=DEFAULT_PORT)
