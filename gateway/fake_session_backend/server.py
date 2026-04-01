from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from aiohttp import web


DEFAULT_HOST = os.environ.get("QANTARA_FAKE_BACKEND_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("QANTARA_FAKE_BACKEND_PORT", "19110"))


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class FakeBackend:
    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}

    def create_session(self, client_context: dict | None = None) -> str:
        session_handle = str(uuid.uuid4())
        self.sessions[session_handle] = {
            "client_context": client_context or {},
            "turns": {},
            "created_at": utc_now(),
        }
        return session_handle

    def create_turn(self, session_handle: str, transcript: str, turn_context: dict | None = None) -> str:
        if session_handle not in self.sessions:
            raise KeyError("unknown session handle")

        turn_handle = str(uuid.uuid4())
        self.sessions[session_handle]["turns"][turn_handle] = {
            "transcript": transcript,
            "turn_context": turn_context or {},
            "cancelled": False,
            "created_at": utc_now(),
        }
        return turn_handle


BACKEND = FakeBackend()


async def health_handler(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "detail": "fake session backend ready"})


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


async def stream_turn_events_handler(request: web.Request) -> web.StreamResponse:
    session_handle = request.match_info["session_handle"]
    turn_handle = request.match_info["turn_handle"]

    if session_handle not in BACKEND.sessions:
        return web.json_response({"error": "unknown session handle"}, status=404)
    if turn_handle not in BACKEND.sessions[session_handle]["turns"]:
        return web.json_response({"error": "unknown turn handle"}, status=404)

    turn = BACKEND.sessions[session_handle]["turns"][turn_handle]
    transcript = turn["transcript"]
    response_text = (
        f"I received your turn: {transcript}. "
        "This response is coming from the fake session backend. "
        "It exists to validate Qantara's real adapter path."
    )
    chunks = [
        f"I received your turn: {transcript}.",
        " This response is coming from the fake session backend.",
        " It exists to validate Qantara's real adapter path.",
    ]

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)

    for chunk in chunks:
        if turn["cancelled"]:
            payload = {"type": "cancel_acknowledged", "turn_handle": turn_handle}
            await response.write((json.dumps(payload) + "\n").encode("utf-8"))
            await response.write_eof()
            return response

        await asyncio.sleep(0.2)
        await response.write((json.dumps({"type": "assistant_text_delta", "text": chunk}) + "\n").encode("utf-8"))

    await asyncio.sleep(0.05)
    await response.write(
        (json.dumps({"type": "assistant_text_final", "text": response_text, "turn_handle": turn_handle}) + "\n").encode("utf-8")
    )
    await response.write((json.dumps({"type": "turn_completed", "turn_handle": turn_handle}) + "\n").encode("utf-8"))
    await response.write_eof()
    return response


async def cancel_turn_handler(request: web.Request) -> web.Response:
    session_handle = request.match_info["session_handle"]
    turn_handle = request.match_info["turn_handle"]

    if session_handle not in BACKEND.sessions:
        return web.json_response({"error": "unknown session handle"}, status=404)
    if turn_handle not in BACKEND.sessions[session_handle]["turns"]:
        return web.json_response({"error": "unknown turn handle"}, status=404)

    BACKEND.sessions[session_handle]["turns"][turn_handle]["cancelled"] = True
    return web.json_response({"status": "acknowledged"})


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
