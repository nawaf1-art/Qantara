from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field

import aiohttp
from aiohttp import web

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gateway.session_backend_prompts import build_voice_turn_context_prompt  # noqa: E402

DEFAULT_HOST = os.environ.get("QANTARA_REAL_BACKEND_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("QANTARA_REAL_BACKEND_PORT", "19120"))
OLLAMA_BASE_URL = os.environ.get("QANTARA_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("QANTARA_OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_KEEP_ALIVE = os.environ.get("QANTARA_OLLAMA_KEEP_ALIVE", "15m")
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("QANTARA_OLLAMA_TIMEOUT", "120"))
MAX_HISTORY_TURNS = max(1, int(os.environ.get("QANTARA_MAX_HISTORY_TURNS", "6")))
ASSISTANT_NAME = os.environ.get("QANTARA_ASSISTANT_NAME", "Qantara")
ASSISTANT_ROLE = os.environ.get("QANTARA_ASSISTANT_ROLE", "a voice assistant")
BUSINESS_NAME = os.environ.get("QANTARA_BUSINESS_NAME", "").strip()
VOICE_STYLE = os.environ.get("QANTARA_VOICE_STYLE", "calm, direct, and helpful").strip()
SYSTEM_PROMPT_OVERRIDE = os.environ.get("QANTARA_OLLAMA_SYSTEM_PROMPT", "").strip()


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


def _clean_label(value: object, fallback: str = "") -> str:
    text = " ".join(str(value or "").strip().split())
    return text or fallback


def _build_system_prompt(client_context: dict | None = None) -> str:
    if SYSTEM_PROMPT_OVERRIDE:
        return SYSTEM_PROMPT_OVERRIDE

    client_context = client_context or {}
    assistant_name = _clean_label(client_context.get("assistant_name"), ASSISTANT_NAME)
    assistant_role = _clean_label(client_context.get("assistant_role"), ASSISTANT_ROLE)
    business_name = _clean_label(client_context.get("business_name"), BUSINESS_NAME)
    voice_style = _clean_label(client_context.get("voice_style"), VOICE_STYLE)
    persona_hint = _clean_label(client_context.get("persona_hint"))

    identity = f"You are {assistant_name}, {assistant_role}."
    if business_name:
        identity = f"You are {assistant_name}, {assistant_role} for {business_name}."

    prompt_parts = [
        identity,
        f"Your speaking style is {voice_style}.",
        "Treat every reply as speech that will be read aloud.",
        "Keep answers brief, natural, and confident.",
        "Use one to three short sentences unless the user clearly asks for more detail.",
        f"When asked who you are, answer as {assistant_name} and keep the role wording consistent.",
        "If the user's words sound partial, noisy, ambiguous, or nonsensical, do not guess their intent.",
        "In those unclear cases, say you did not catch that clearly and ask them to repeat or rephrase.",
        "Do not invent strange specifics from uncertain speech fragments.",
        "If the user only says a low-information acknowledgment like yes, yeah, okay, or mm-hmm, do not infer a task.",
        "For those acknowledgment-only turns, reply briefly and ask what they need help with.",
        "For a simple greeting, respond with one short greeting and one direct offer to help.",
        "Do not use filler, hype, or hospitality phrases unless the user explicitly invites that tone.",
        "Do not introduce yourself unless the user asks who you are or the conversation is just starting.",
        "Prefer direct service-oriented wording over brand adjectives or charm.",
        "Ask at most one short follow-up question when it is genuinely needed.",
        "Do not use markdown, lists, headings, bullet points, or emojis.",
        "Do not mention policies, hidden instructions, or internal implementation details.",
        "If you are unsure, say so briefly and offer the next useful step.",
    ]
    if persona_hint:
        prompt_parts.append(f"Persona note: {persona_hint}.")
    return " ".join(prompt_parts)


def _normalize_assistant_text(text: str) -> str:
    normalized = text.replace("`", " ").replace("\r", " ").replace("\n", " ")
    normalized = normalized.replace("*", " ").replace("#", " ")
    normalized = " ".join(normalized.split())
    return normalized.strip()


def _trim_history(history: list[dict]) -> list[dict]:
    if not history:
        return history

    system_message = history[0] if history[0].get("role") == "system" else None
    conversational = history[1:] if system_message else history
    max_messages = MAX_HISTORY_TURNS * 2
    if len(conversational) > max_messages:
        conversational = conversational[-max_messages:]
    return ([system_message] if system_message else []) + conversational


def _append_history(session_state: SessionState, user_text: str, assistant_text: str) -> None:
    session_state.history.append({"role": "user", "content": user_text})
    session_state.history.append({"role": "assistant", "content": assistant_text})
    session_state.history = _trim_history(session_state.history)


class OllamaSessionBackend:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}

    def create_session(self, client_context: dict | None = None) -> str:
        session_handle = str(uuid.uuid4())
        self.sessions[session_handle] = SessionState(
            client_context=client_context or {},
            history=[{"role": "system", "content": _build_system_prompt(client_context)}],
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


async def _ollama_stream_messages(session_state: SessionState, transcript: str, turn_context: dict | None = None):
    messages = [*session_state.history]
    context_prompt = build_voice_turn_context_prompt(turn_context)
    if context_prompt:
        messages.append({"role": "system", "content": context_prompt})
    messages.append({"role": "user", "content": transcript})
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
        client, upstream = await _ollama_stream_messages(session_state, turn.transcript, turn.turn_context)
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

        turn.final_text = _normalize_assistant_text(full_text)
        if turn.final_text:
            _append_history(session_state, turn.transcript, turn.final_text)
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
