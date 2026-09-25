from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import web

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from adapters.base import make_activity_event  # noqa: E402
from gateway.session_backend_prompts import build_voice_turn_context_prompt  # noqa: E402
from qantara.http_safety import (  # noqa: E402
    read_bounded_response_json,
    read_bounded_response_text,
)
from qantara.streaming import (  # noqa: E402
    NDJSONEventWriter,
    ReasoningTagFilter,
    iter_ndjson_objects,
)

DEFAULT_HOST = os.environ.get("QANTARA_REAL_BACKEND_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("QANTARA_REAL_BACKEND_PORT", "19120"))
OLLAMA_BASE_URL = os.environ.get("QANTARA_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("QANTARA_OLLAMA_MODEL", "qwen3.5:2b")
OLLAMA_KEEP_ALIVE = os.environ.get("QANTARA_OLLAMA_KEEP_ALIVE", "15m")
# Idle bound on the upstream Ollama stream (no bytes for this long fails the
# turn). Not a total bound: long generations are fine while tokens flow.
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("QANTARA_OLLAMA_TIMEOUT", "120"))
OLLAMA_CONNECT_TIMEOUT_SECONDS = 10.0
# While a turn is silent (model load, long prefill) the bridge sends an
# assistant_activity keep-alive at least this often, so the gateway's idle
# timeout (QANTARA_BACKEND_IDLE_TIMEOUT) does not fire.
KEEPALIVE_SECONDS = float(os.environ.get("QANTARA_BACKEND_KEEPALIVE_SECONDS", "10"))
OLLAMA_THINK = os.environ.get("QANTARA_OLLAMA_THINK", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MAX_HISTORY_TURNS = max(1, int(os.environ.get("QANTARA_MAX_HISTORY_TURNS", "6")))
MAX_SESSIONS = max(1, int(os.environ.get("QANTARA_BACKEND_MAX_SESSIONS", "64")))
MAX_TURNS_PER_SESSION = 24
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
    # In-flight upstream work, so cancel can abort it promptly.
    request_task: asyncio.Task | None = field(default=None, repr=False)
    upstream: aiohttp.ClientResponse | None = field(default=None, repr=False)


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
        while len(self.sessions) > MAX_SESSIONS:
            oldest_handle = next(iter(self.sessions))
            self.sessions.pop(oldest_handle, None)
        return session_handle

    def create_turn(self, session_handle: str, transcript: str, turn_context: dict | None = None) -> str:
        if session_handle not in self.sessions:
            raise KeyError("unknown session handle")
        # Refresh recency so an actively used session is not the next evicted.
        session_state = self.sessions.pop(session_handle)
        self.sessions[session_handle] = session_state
        turn_handle = str(uuid.uuid4())
        session_state.turns[turn_handle] = TurnState(
            transcript=transcript,
            turn_context=turn_context or {},
        )
        while len(session_state.turns) > MAX_TURNS_PER_SESSION:
            oldest_turn_handle = next(iter(session_state.turns))
            if oldest_turn_handle == turn_handle:
                break
            session_state.turns.pop(oldest_turn_handle, None)
        return turn_handle


BACKEND = OllamaSessionBackend()
MAX_TURN_TEXT_CHARS = 16 * 1024
MAX_ASSISTANT_TEXT_CHARS = 1024 * 1024


def _model_is_pulled(model: str, tags: Any) -> bool:
    """Return True when /api/tags lists the model (tolerating Ollama's :latest)."""
    models = tags.get("models") if isinstance(tags, dict) else None
    if not isinstance(models, list):
        return False
    candidates = {model}
    if model.endswith(":latest"):
        candidates.add(model[: -len(":latest")])
    elif ":" not in model:
        candidates.add(f"{model}:latest")
    for entry in models:
        if not isinstance(entry, dict):
            continue
        if entry.get("name") in candidates or entry.get("model") in candidates:
            return True
    return False


async def health_handler(_: web.Request) -> web.Response:
    detail = f"ollama session backend ready ({OLLAMA_MODEL})"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(
                f"{OLLAMA_BASE_URL}/api/tags", allow_redirects=False
            ) as response:
                if response.status >= 400:
                    return web.json_response({"status": "degraded", "detail": detail}, status=200)
                tags = await read_bounded_response_json(response)
    except Exception:
        return web.json_response(
            {"status": "degraded", "detail": f"{detail}; ollama unavailable"},
            status=200,
        )
    if not _model_is_pulled(OLLAMA_MODEL, tags):
        return web.json_response(
            {
                "status": "degraded",
                "detail": f"{detail}; model {OLLAMA_MODEL!r} is not pulled (run: ollama pull {OLLAMA_MODEL})",
            },
            status=200,
        )
    return web.json_response({"status": "ok", "detail": detail})


async def create_session_handler(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, web.HTTPBadRequest):
        return web.json_response({"error": "invalid JSON object"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "invalid JSON object"}, status=400)
    client_context = payload.get("client_context")
    if client_context is not None and not isinstance(client_context, dict):
        return web.json_response({"error": "client_context must be an object"}, status=400)
    session_handle = BACKEND.create_session(client_context)
    return web.json_response({"session_handle": session_handle})


async def create_turn_handler(request: web.Request) -> web.Response:
    session_handle = request.match_info["session_handle"]
    if session_handle not in BACKEND.sessions:
        return web.json_response({"error": "unknown session handle"}, status=404)

    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, web.HTTPBadRequest):
        return web.json_response({"error": "invalid JSON object"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "invalid JSON object"}, status=400)
    raw_transcript = payload.get("transcript")
    transcript = raw_transcript.strip() if isinstance(raw_transcript, str) else ""
    if not transcript:
        return web.json_response({"error": "empty transcript"}, status=400)
    if len(transcript) > MAX_TURN_TEXT_CHARS:
        return web.json_response({"error": "transcript is too long"}, status=413)

    turn_context = payload.get("turn_context")
    if turn_context is not None and not isinstance(turn_context, dict):
        return web.json_response({"error": "turn_context must be an object"}, status=400)
    turn_handle = BACKEND.create_turn(session_handle, transcript, turn_context)
    return web.json_response({"turn_handle": turn_handle})


def _request_messages(session_state: SessionState, transcript: str, turn_context: dict | None) -> list[dict]:
    """Build [system, (user, assistant)*, user]; voice context joins the system message."""
    history = session_state.history
    context_prompt = build_voice_turn_context_prompt(turn_context, omit_defaults=True)
    if history and history[0].get("role") == "system":
        system = dict(history[0])
        exchanges = history[1:]
    else:
        system = {"role": "system", "content": ""}
        exchanges = list(history)
    if context_prompt:
        system["content"] = f"{system['content']}\n\n{context_prompt}".strip()
    messages = [system] if system["content"] else []
    messages.extend(exchanges)
    messages.append({"role": "user", "content": transcript})
    return messages


async def _ollama_stream_messages(session_state: SessionState, transcript: str, turn_context: dict | None = None):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": _request_messages(session_state, transcript, turn_context),
        "stream": True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "think": OLLAMA_THINK,
    }

    timeout = aiohttp.ClientTimeout(
        total=None,
        sock_connect=OLLAMA_CONNECT_TIMEOUT_SECONDS,
        sock_read=OLLAMA_TIMEOUT_SECONDS,
    )
    client = aiohttp.ClientSession(timeout=timeout, trust_env=False)
    try:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            allow_redirects=False,
        )
    except BaseException:
        # Includes cancellation by cancel_turn_handler before headers arrive.
        await client.close()
        raise
    return client, response


def _keepalive_event(turn_handle: str) -> dict[str, Any]:
    return {**make_activity_event("thinking", "Still working"), "turn_handle": turn_handle}


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

    writer = NDJSONEventWriter(
        response.write,
        keepalive_seconds=KEEPALIVE_SECONDS,
        keepalive_event=lambda: _keepalive_event(turn_handle),
    )

    async def send(event: dict[str, Any]) -> None:
        await writer.send({**event, "turn_handle": turn_handle})

    try:
        async with writer:
            terminal = await _stream_turn(session_state, turn, send)
            await send(terminal)
        await response.write_eof()
    except ConnectionResetError:
        pass  # the gateway went away; upstream work was already released
    return response


async def _stream_turn(
    session_state: SessionState,
    turn: TurnState,
    send: Any,
) -> dict[str, Any]:
    """Stream one turn's deltas via ``send`` and return its terminal event.

    The final text is exactly the concatenation of the deltas sent (after
    inline reasoning is filtered), so the gateway can speak the unsent tail
    by offset.
    """
    if turn.cancelled:
        return {"type": "cancel_acknowledged"}

    client: aiohttp.ClientSession | None = None
    upstream: aiohttp.ClientResponse | None = None
    tag_filter = ReasoningTagFilter()
    full_text = ""
    announced_reasoning = False

    async def announce_reasoning() -> None:
        nonlocal announced_reasoning
        if not announced_reasoning:
            announced_reasoning = True
            await send(make_activity_event("thinking", "Thinking"))

    async def send_delta(delta: str) -> None:
        nonlocal full_text
        if len(full_text) + len(delta) > MAX_ASSISTANT_TEXT_CHARS:
            raise RuntimeError("assistant output exceeded the configured limit")
        full_text += delta
        await send({"type": "assistant_text_delta", "text": delta})

    try:
        turn.request_task = asyncio.create_task(
            _ollama_stream_messages(session_state, turn.transcript, turn.turn_context)
        )
        try:
            client, upstream = await turn.request_task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if turn.cancelled and (current is None or not current.cancelling()):
                return {"type": "cancel_acknowledged"}
            raise
        finally:
            turn.request_task = None
        turn.upstream = upstream
        if turn.cancelled:
            return {"type": "cancel_acknowledged"}
        if upstream.status >= 400:
            body = await read_bounded_response_text(upstream)
            return {"type": "turn_failed", "message": body or f"ollama error {upstream.status}"}

        async for payload in iter_ndjson_objects(upstream.content):
            if turn.cancelled:
                return {"type": "cancel_acknowledged"}

            upstream_error = payload.get("error")
            if upstream_error:
                message = upstream_error if isinstance(upstream_error, str) else json.dumps(upstream_error, ensure_ascii=False)
                return {"type": "turn_failed", "message": message}

            if payload.get("done"):
                break

            message = payload.get("message")
            if not isinstance(message, dict):
                continue
            thinking = message.get("thinking")
            if isinstance(thinking, str) and thinking:
                await announce_reasoning()
            content = message.get("content")
            visible = tag_filter.feed(content) if isinstance(content, str) and content else ""
            if tag_filter.saw_reasoning:
                await announce_reasoning()
            if visible:
                await send_delta(visible)

        if turn.cancelled:
            return {"type": "cancel_acknowledged"}
        tail = tag_filter.flush()
        if tail:
            await send_delta(tail)

        if not full_text:
            message = "model returned no assistant content"
            if announced_reasoning:
                message += "; reasoning was withheld from voice output"
            return {"type": "turn_failed", "message": message}

        turn.final_text = full_text
        history_text = full_text.strip()
        if history_text:
            _append_history(session_state, turn.transcript, history_text)
        await send({"type": "assistant_text_final", "text": full_text})
        return {"type": "turn_completed"}
    except Exception as exc:
        if turn.cancelled:
            # Closing the upstream on cancel surfaces here as a read error.
            return {"type": "cancel_acknowledged"}
        return {"type": "turn_failed", "message": str(exc) or type(exc).__name__}
    finally:
        turn.upstream = None
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

    turn = BACKEND.sessions[session_handle].turns[turn_handle]
    turn.cancelled = True
    # Abort upstream work now instead of at the next token: a request still
    # waiting for headers is cancelled, an open stream is closed.
    if turn.request_task is not None and not turn.request_task.done():
        turn.request_task.cancel()
    if turn.upstream is not None:
        turn.upstream.close()
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
