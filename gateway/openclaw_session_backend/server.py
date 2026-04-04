from __future__ import annotations

import asyncio
import json
import os
import signal
import time
import uuid
from dataclasses import dataclass, field

from aiohttp import web


DEFAULT_HOST = os.environ.get("QANTARA_REAL_BACKEND_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("QANTARA_REAL_BACKEND_PORT", "19120"))
OPENCLAW_BIN = os.environ.get("QANTARA_OPENCLAW_BIN", "openclaw")
OPENCLAW_AGENT_ID = os.environ.get("QANTARA_OPENCLAW_AGENT_ID", "spectra").strip() or "spectra"
OPENCLAW_TIMEOUT_SECONDS = float(os.environ.get("QANTARA_OPENCLAW_TIMEOUT", "120"))
OPENCLAW_THINKING = os.environ.get("QANTARA_OPENCLAW_THINKING", "").strip()
OPENCLAW_CANCEL_GRACE_SECONDS = float(os.environ.get("QANTARA_OPENCLAW_CANCEL_GRACE", "2"))


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
    last_active_at: str = field(default_factory=utc_now)


class OpenClawSessionBackend:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}
        self.client_session_map: dict[str, str] = {}
        self.active_processes: dict[str, asyncio.subprocess.Process] = {}
        self.turn_lock = asyncio.Lock()

    def create_session(self, client_context: dict | None = None) -> str:
        client_context = client_context or {}
        client_session_id = (client_context.get("client_session_id") or "").strip()
        if client_session_id:
            existing_session_handle = self.client_session_map.get(client_session_id)
            if existing_session_handle and existing_session_handle in self.sessions:
                existing = self.sessions[existing_session_handle]
                existing.client_context = client_context
                existing.last_active_at = utc_now()
                return existing_session_handle

        session_handle = str(uuid.uuid4())
        self.sessions[session_handle] = SessionState(client_context=client_context)
        if client_session_id:
            self.client_session_map[client_session_id] = session_handle
        return session_handle

    def create_turn(self, session_handle: str, transcript: str, turn_context: dict | None = None) -> str:
        if session_handle not in self.sessions:
            raise KeyError("unknown session handle")
        session_state = self.sessions[session_handle]
        turn_handle = str(uuid.uuid4())
        session_state.turns[turn_handle] = TurnState(
            transcript=transcript,
            turn_context=turn_context or {},
        )
        session_state.last_active_at = utc_now()
        if len(session_state.turns) > 24:
            oldest_turn_handle = next(iter(session_state.turns))
            if oldest_turn_handle != turn_handle:
                session_state.turns.pop(oldest_turn_handle, None)
        return turn_handle


BACKEND = OpenClawSessionBackend()


class TurnCancelledError(RuntimeError):
    pass


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\r", " ").replace("\n", " ").split()).strip()


def _build_openclaw_command(session_handle: str, transcript: str) -> list[str]:
    command = [
        OPENCLAW_BIN,
        "agent",
        "--agent",
        OPENCLAW_AGENT_ID,
        "--session-id",
        session_handle,
        "--message",
        transcript,
        "--json",
    ]
    if OPENCLAW_THINKING:
        command.extend(["--thinking", OPENCLAW_THINKING])
    if OPENCLAW_TIMEOUT_SECONDS > 0:
        command.extend(["--timeout", str(int(OPENCLAW_TIMEOUT_SECONDS))])
    return command


async def _terminate_process_group(process: asyncio.subprocess.Process, hard: bool = False) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL if hard else signal.SIGTERM)
    except ProcessLookupError:
        return


async def _escalate_cancel(turn_handle: str, process: asyncio.subprocess.Process) -> None:
    await asyncio.sleep(max(0.0, OPENCLAW_CANCEL_GRACE_SECONDS))
    if process.returncode is None and turn_handle in BACKEND.active_processes:
        await _terminate_process_group(process, hard=True)


async def _run_openclaw_turn(session_handle: str, turn_handle: str, transcript: str) -> tuple[str, dict]:
    command = _build_openclaw_command(session_handle, transcript)
    async with BACKEND.turn_lock:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        BACKEND.active_processes[turn_handle] = process
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=OPENCLAW_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await _terminate_process_group(process, hard=True)
            await process.communicate()
            raise RuntimeError(f"openclaw agent timed out after {int(OPENCLAW_TIMEOUT_SECONDS)} seconds")
        finally:
            BACKEND.active_processes.pop(turn_handle, None)

    turn = BACKEND.sessions[session_handle].turns[turn_handle]
    if turn.cancelled:
        raise TurnCancelledError("turn cancelled")

    if process.returncode != 0:
        message = (stderr or stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"openclaw agent failed with exit code {process.returncode}")

    payload = json.loads(stdout.decode("utf-8", errors="replace"))
    result = payload.get("result") or {}
    payloads = result.get("payloads") or []
    texts = [_normalize_text(item.get("text", "")) for item in payloads if isinstance(item, dict)]
    final_text = " ".join(text for text in texts if text).strip()
    if not final_text:
        raise RuntimeError("openclaw agent returned no text payload")
    return final_text, payload


async def health_handler(_: web.Request) -> web.Response:
    detail = f"openclaw session backend ready ({OPENCLAW_AGENT_ID})"
    try:
        process = await asyncio.create_subprocess_exec(
            OPENCLAW_BIN,
            "agent",
            "--agent",
            OPENCLAW_AGENT_ID,
            "--session-id",
            f"qantara-health-{OPENCLAW_AGENT_ID}",
            "--message",
            "Identify yourself in one short sentence.",
            "--json",
            "--timeout",
            "20",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = (stderr or stdout).decode("utf-8", errors="replace").strip()
            return web.json_response({"status": "degraded", "detail": f"{detail}; {message}"}, status=200)
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
        result = payload.get("result") or {}
        meta = result.get("meta") or {}
        agent_name = (
            ((meta.get("agentMeta") or {}).get("name"))
            or payload.get("name")
            or OPENCLAW_AGENT_ID
        )
        return web.json_response({"status": "ok", "detail": f"{detail}; agent={agent_name}"})
    except Exception as exc:
        return web.json_response({"status": "degraded", "detail": f"{detail}; {exc}"}, status=200)


async def create_session_handler(request: web.Request) -> web.Response:
    payload = await request.json()
    client_context = payload.get("client_context")
    existing_session_handle = None
    client_session_id = ((client_context or {}).get("client_session_id") or "").strip()
    if client_session_id:
        existing_session_handle = BACKEND.client_session_map.get(client_session_id)
    session_handle = BACKEND.create_session(client_context)
    return web.json_response(
        {
            "session_handle": session_handle,
            "resumed": bool(existing_session_handle and existing_session_handle == session_handle),
        }
    )


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

    try:
        final_text, meta = await _run_openclaw_turn(session_handle, turn_handle, turn.transcript)
        if turn.cancelled:
            await response.write((json.dumps({"type": "cancel_acknowledged", "turn_handle": turn_handle}) + "\n").encode("utf-8"))
            await response.write_eof()
            return response

        turn.final_text = final_text
        await response.write((json.dumps({"type": "assistant_text_delta", "text": final_text, "turn_handle": turn_handle}) + "\n").encode("utf-8"))
        await response.write((json.dumps({"type": "assistant_text_final", "text": final_text, "turn_handle": turn_handle}) + "\n").encode("utf-8"))
        await response.write(
            (
                json.dumps(
                    {
                        "type": "turn_completed",
                        "turn_handle": turn_handle,
                        "agent_id": OPENCLAW_AGENT_ID,
                        "agent_meta": ((meta.get("result") or {}).get("meta") or {}).get("agentMeta") or {},
                    }
                )
                + "\n"
            ).encode("utf-8")
        )
        await response.write_eof()
        return response
    except TurnCancelledError:
        await response.write((json.dumps({"type": "cancel_acknowledged", "turn_handle": turn_handle}) + "\n").encode("utf-8"))
        await response.write_eof()
        return response
    except Exception as exc:
        await response.write((json.dumps({"type": "turn_failed", "message": str(exc), "turn_handle": turn_handle}) + "\n").encode("utf-8"))
        await response.write_eof()
        return response


async def cancel_turn_handler(request: web.Request) -> web.Response:
    session_handle = request.match_info["session_handle"]
    turn_handle = request.match_info["turn_handle"]

    if session_handle not in BACKEND.sessions:
        return web.json_response({"error": "unknown session handle"}, status=404)
    if turn_handle not in BACKEND.sessions[session_handle].turns:
        return web.json_response({"error": "unknown turn handle"}, status=404)

    BACKEND.sessions[session_handle].turns[turn_handle].cancelled = True
    process = BACKEND.active_processes.get(turn_handle)
    if process and process.returncode is None:
        await _terminate_process_group(process, hard=False)
        asyncio.create_task(_escalate_cancel(turn_handle, process))
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
