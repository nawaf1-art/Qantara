"""OpenAI-compatible adapter for Qantara.

Connects directly to any server exposing /v1/chat/completions.
Covers: Ollama (OpenAI mode), llama.cpp, vLLM, LiteLLM, LocalAI,
Jan.ai, LM Studio, and any other OpenAI-compatible server.

No bridge process needed — the adapter speaks the OpenAI chat
completions protocol directly.

History discipline:

- The request is always ``[system, (user, assistant)*, user]``: the per-turn
  voice context is merged into the single system message, never inserted as
  a second one, so strict-alternation chat templates (Gemma, Mistral) accept
  it.
- A user message stays pending until its turn succeeds; then the user and
  assistant messages are stored together. Failed or interrupted turns leave
  no trace in history.
- History is trimmed in whole exchanges, by count and by a character budget.
  A context-length rejection drops the oldest exchange and retries once.
- Inline ``<think>`` reasoning is filtered from spoken text and history.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter, make_activity_event
from gateway.session_backend_prompts import build_voice_turn_context_prompt
from qantara.http_safety import (
    HTTPResponseLimitError,
    read_bounded_response_json,
    read_bounded_response_text,
)
from qantara.streaming import ReasoningTagFilter, iter_sse_json_objects

# Voice-optimized system prompt: short responses, conversational, no markdown.
DEFAULT_SYSTEM_PROMPT = (
    "You are a voice assistant. Keep replies short and conversational. No markdown or formatting."
)

# Max stored conversation messages after the system prompt (10 exchanges).
MAX_HISTORY_TURNS = 20
DEFAULT_HISTORY_CHAR_BUDGET = 8000
DEFAULT_MAX_TOKENS = 512
MAX_ASSISTANT_TEXT_CHARS = 1024 * 1024
# Turns submitted but never streamed (or never cleaned up) are bounded.
MAX_PENDING_TURNS = 256
REASONING_START_MODES = ("auto", "inside", "outside")

_CONTEXT_OVERFLOW_STATUSES = frozenset({400, 413, 422})
_CONTEXT_OVERFLOW_RE = re.compile(r"context|tokens?\b|prompt is too long", re.IGNORECASE)


def _normalize_base_url(raw: str) -> str:
    """Normalize a user-provided URL to a clean base."""
    url = raw.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url
    # Strip common suffixes users might paste
    for suffix in ("/v1/chat/completions", "/v1/models", "/v1", "/api"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def _normalize_error(body: str) -> str:
    """Handle both Ollama and OpenAI error formats."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body.strip() or "unknown error"
    if not isinstance(data, dict):
        return body.strip() or "unknown error"
    err = data.get("error")
    if isinstance(err, str):
        return err  # Ollama: {"error": "string"}
    if isinstance(err, dict):
        return str(err.get("message", err))  # OpenAI: {"error": {"message": "..."}}
    return body.strip() or "unknown error"


def _is_context_overflow(status: int, message: str) -> bool:
    return status in _CONTEXT_OVERFLOW_STATUSES and bool(_CONTEXT_OVERFLOW_RE.search(message))


def _extract_answer_delta(delta: object) -> tuple[str, bool]:
    """Return only user-facing content and flag hidden reasoning separately."""
    if not isinstance(delta, dict):
        return "", False
    content = delta.get("content")
    answer = content if isinstance(content, str) else ""
    has_reasoning = any(
        isinstance(delta.get(key), str) and bool(delta[key])
        for key in ("reasoning", "reasoning_content", "thinking")
    )
    return answer, has_reasoning


def _model_is_listed(model: str, model_ids: list[str]) -> bool:
    """Match a configured model against a server list, tolerating Ollama's :latest."""
    candidates = {model}
    if model.endswith(":latest"):
        candidates.add(model[: -len(":latest")])
    elif ":" not in model:
        candidates.add(f"{model}:latest")
    return any(model_id in candidates for model_id in model_ids)


def _int_option(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


class OpenAICompatibleAdapter(RuntimeAdapter):
    """Adapter that speaks the OpenAI chat completions protocol directly."""

    def __init__(self, config: AdapterConfig | None = None) -> None:
        super().__init__(
            config or AdapterConfig(kind="openai_compatible", name="openai-compatible")
        )
        options = self.config.options
        raw_url = options.get("base_url") or os.environ.get("QANTARA_OPENAI_BASE_URL", "")
        self.base_url = _normalize_base_url(raw_url)
        self.outbound_host_header = str(options.get("outbound_host_header") or "")
        self.outbound_server_hostname = str(options.get("outbound_server_hostname") or "")
        self.api_key = options.get("api_key") or os.environ.get("QANTARA_OPENAI_API_KEY", "not-needed")
        self.model = options.get("model") or os.environ.get("QANTARA_OPENAI_MODEL", "")
        self.system_prompt = options.get("system_prompt") or os.environ.get(
            "QANTARA_OPENAI_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT
        )
        self.timeout_connect = float(
            options.get("timeout_connect") or os.environ.get("QANTARA_OPENAI_TIMEOUT_CONNECT", "5")
        )
        self.timeout_first_token = float(
            options.get("timeout_first_token") or os.environ.get("QANTARA_OPENAI_TIMEOUT_FIRST_TOKEN", "30")
        )
        self.reasoning_effort = (
            options.get("reasoning_effort") or os.environ.get("QANTARA_OPENAI_REASONING_EFFORT", "")
        ).strip()
        # 0 disables sending max_tokens.
        self.max_tokens = max(
            0,
            _int_option(
                options.get("max_tokens", os.environ.get("QANTARA_OPENAI_MAX_TOKENS")),
                DEFAULT_MAX_TOKENS,
            ),
        )
        self.history_char_budget = max(
            0,
            _int_option(
                options.get("history_char_budget", os.environ.get("QANTARA_OPENAI_HISTORY_CHAR_BUDGET")),
                DEFAULT_HISTORY_CHAR_BUDGET,
            ),
        )
        reasoning_start = str(
            options.get("reasoning_start") or os.environ.get("QANTARA_OPENAI_REASONING_START", "auto")
        ).strip().lower()
        self.reasoning_start = reasoning_start if reasoning_start in REASONING_START_MODES else "auto"

        self.max_sessions = int(
            options.get("max_sessions") or os.environ.get("QANTARA_OPENAI_MAX_SESSIONS", "64")
        )
        # Per-session committed history: session_handle -> [system, (user, assistant)*].
        # Bounded: least-recently-used sessions are evicted beyond max_sessions.
        self._sessions: dict[str, list[dict[str, str]]] = {}
        # Per-turn state, all keyed by turn handle and removed together.
        self._active_turns: dict[str, bool] = {}  # False once cancelled
        self._turn_sessions: dict[str, str] = {}
        self._turn_transcripts: dict[str, str] = {}  # pending user message
        self._turn_context_prompts: dict[str, str] = {}  # transient, never persisted
        self._active_responses: dict[str, aiohttp.ClientResponse] = {}
        self._active_clients: dict[str, aiohttp.ClientSession] = {}
        # Models observed to start their output inside reasoning (only a
        # closing </think> tag appears), learned when reasoning_start=auto.
        self._reasoning_prefix_models: set[str] = set()
        # Detected /v1 prefix (auto-probed on first use)
        self._api_prefix: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.outbound_host_header:
            headers["Host"] = self.outbound_host_header
        return headers

    def _request_kwargs(self) -> dict[str, str]:
        if self.outbound_server_hostname:
            return {"server_hostname": self.outbound_server_hostname}
        return {}

    async def _resolve_api_prefix(self) -> str:
        """Auto-detect whether the server needs /v1 prefix."""
        if self._api_prefix is not None:
            return self._api_prefix

        timeout = aiohttp.ClientTimeout(total=self.timeout_connect)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            # Try /v1/models first (most common)
            for prefix in ("/v1", ""):
                try:
                    async with session.get(
                        f"{self.base_url}{prefix}/models",
                        headers=self._headers(),
                        allow_redirects=False,
                        **self._request_kwargs(),
                    ) as resp:
                        if resp.status < 400:
                            self._api_prefix = prefix
                            return prefix
                except (aiohttp.ClientError, TimeoutError):
                    continue

        # Default to /v1 if we can't detect
        self._api_prefix = "/v1"
        return "/v1"

    async def _auto_detect_model(self) -> str:
        """Pick the first available model if none is configured."""
        prefix = await self._resolve_api_prefix()
        timeout = aiohttp.ClientTimeout(total=self.timeout_connect)
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.get(
                    f"{self.base_url}{prefix}/models",
                    headers=self._headers(),
                    allow_redirects=False,
                    **self._request_kwargs(),
                ) as resp:
                    if resp.status >= 400:
                        return ""
                    data = await read_bounded_response_json(resp)
                    if not isinstance(data, dict):
                        return ""
                    models = data.get("data", [])
                    if not isinstance(models, list) or not models:
                        return ""
                    first = models[0]
                    if isinstance(first, dict):
                        model_id = first.get("id")
                        return model_id if isinstance(model_id, str) else ""
        except (
            aiohttp.ClientError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            HTTPResponseLimitError,
        ):
            return ""
        return ""

    def _new_history(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system_prompt}]

    async def start_or_resume_session(
        self, client_context: dict | None = None
    ) -> str:
        session_handle = str(uuid.uuid4())
        self._sessions[session_handle] = self._new_history()
        self._evict_stale_sessions()
        return session_handle

    def _evict_stale_sessions(self) -> None:
        while len(self._sessions) > self.max_sessions:
            oldest_handle = next(iter(self._sessions))
            self._sessions.pop(oldest_handle, None)

    def _touch_session(self, session_handle: str) -> None:
        # Move to the tail of the insertion-ordered dict so eviction is LRU.
        messages = self._sessions.pop(session_handle, None)
        if messages is not None:
            self._sessions[session_handle] = messages

    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        if session_handle not in self._sessions:
            # Auto-create session if missing
            self._sessions[session_handle] = self._new_history()
            self._evict_stale_sessions()
        else:
            self._touch_session(session_handle)

        turn_handle = str(uuid.uuid4())
        self._active_turns[turn_handle] = True
        self._turn_sessions[turn_handle] = session_handle
        # The user message stays pending here until the turn succeeds.
        self._turn_transcripts[turn_handle] = transcript
        # Transient voice context, merged into the system message at request
        # time only. Default-only context is skipped entirely.
        context_prompt = build_voice_turn_context_prompt(turn_context, omit_defaults=True)
        if context_prompt:
            self._turn_context_prompts[turn_handle] = context_prompt
        while len(self._turn_sessions) > MAX_PENDING_TURNS:
            self._cleanup_turn(next(iter(self._turn_sessions)))
        return turn_handle

    def _request_messages(
        self,
        session_handle: str,
        transcript: str,
        context_prompt: str,
    ) -> list[dict[str, str]]:
        history = self._sessions.get(session_handle) or self._new_history()
        system_content = history[0]["content"] if history[0].get("role") == "system" else self.system_prompt
        exchanges = history[1:] if history[0].get("role") == "system" else history
        if context_prompt:
            system_content = f"{system_content}\n\n{context_prompt}"
        return [
            {"role": "system", "content": system_content},
            *exchanges,
            {"role": "user", "content": transcript},
        ]

    def _trim_history(self, history: list[dict[str, str]]) -> None:
        """Drop whole (user, assistant) exchanges until count and size fit."""
        while len(history) > 1:
            exchanges = history[1:]
            chars = sum(len(message.get("content", "")) for message in exchanges)
            if len(exchanges) <= MAX_HISTORY_TURNS and chars <= self.history_char_budget:
                return
            del history[1:3]

    def _commit_exchange(self, session_handle: str, transcript: str, reply: str) -> None:
        history = self._sessions.get(session_handle)
        if history is None or not reply:
            return
        history.append({"role": "user", "content": transcript})
        history.append({"role": "assistant", "content": reply})
        self._trim_history(history)

    def _drop_oldest_exchange(self, session_handle: str) -> bool:
        history = self._sessions.get(session_handle)
        if history is None or len(history) < 3:
            return False
        del history[1:3]
        return True

    def _is_cancelled(self, turn_handle: str) -> bool:
        return not self._active_turns.get(turn_handle, False)

    async def stream_assistant_output(
        self,
        session_handle: str,
        turn_handle: str,
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            if not self.available:
                raise RuntimeError("OpenAI-compatible backend URL is not configured")
            transcript = self._turn_transcripts.get(turn_handle)
            if transcript is None:
                yield {"type": "turn_failed", "message": "unknown or finished turn handle"}
                return
            if self._is_cancelled(turn_handle):
                yield {"type": "cancel_acknowledged"}
                return
            if session_handle not in self._sessions:
                yield {"type": "turn_failed", "message": "no session found"}
                return

            model = self.model or await self._auto_detect_model()
            if not model:
                yield {"type": "turn_failed", "message": "no model configured or detected"}
                return
            prefix = await self._resolve_api_prefix()
            url = f"{self.base_url}{prefix}/chat/completions"
            context_prompt = self._turn_context_prompts.get(turn_handle, "")

            start_inside = self.reasoning_start == "inside" or (
                self.reasoning_start == "auto" and model in self._reasoning_prefix_models
            )
            tag_filter = ReasoningTagFilter(start_inside=start_inside)
            timeout = aiohttp.ClientTimeout(
                sock_connect=self.timeout_connect,
                sock_read=self.timeout_first_token,
            )

            full_response = ""  # exactly the concatenated deltas yielded
            clean_response = ""  # what is stored in history (no reasoning)
            reasoning_announced = False
            stray_close_seen = False
            stream_error = ""
            finish_reason = ""
            failure = ""

            try:
                for attempt in range(2):
                    payload: dict[str, Any] = {
                        "model": model,
                        "messages": self._request_messages(session_handle, transcript, context_prompt),
                        "stream": True,
                    }
                    if self.max_tokens:
                        payload["max_tokens"] = self.max_tokens
                    if self.reasoning_effort:
                        payload["reasoning_effort"] = self.reasoning_effort

                    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as http:
                        self._active_clients[turn_handle] = http
                        async with http.post(
                            url,
                            json=payload,
                            headers=self._headers(),
                            allow_redirects=False,
                            **self._request_kwargs(),
                        ) as resp:
                            self._active_responses[turn_handle] = resp
                            if self._is_cancelled(turn_handle):
                                break
                            if resp.status >= 400:
                                message = _normalize_error(await read_bounded_response_text(resp))
                                if (
                                    attempt == 0
                                    and _is_context_overflow(resp.status, message)
                                    and self._drop_oldest_exchange(session_handle)
                                ):
                                    continue
                                failure = message
                                break

                            async for event in iter_sse_json_objects(resp.content):
                                if self._is_cancelled(turn_handle):
                                    break
                                if event.get("error"):
                                    stream_error = _normalize_error(json.dumps(event))
                                    break
                                choices = event.get("choices", [])
                                if (
                                    not isinstance(choices, list)
                                    or not choices
                                    or not isinstance(choices[0], dict)
                                ):
                                    continue
                                choice = choices[0]
                                if isinstance(choice.get("finish_reason"), str):
                                    finish_reason = choice["finish_reason"]
                                content, field_reasoning = _extract_answer_delta(choice.get("delta", {}))
                                visible = tag_filter.feed(content) if content else ""
                                if tag_filter.saw_stray_close and not stray_close_seen:
                                    # Everything before the stray tag was reasoning.
                                    stray_close_seen = True
                                    clean_response = ""
                                    if self.reasoning_start == "auto":
                                        self._reasoning_prefix_models.add(model)
                                if (field_reasoning or tag_filter.saw_reasoning) and not reasoning_announced:
                                    reasoning_announced = True
                                    yield make_activity_event("thinking", "Thinking")
                                if visible:
                                    if len(full_response) + len(visible) > MAX_ASSISTANT_TEXT_CHARS:
                                        stream_error = "assistant output exceeded the configured limit"
                                        break
                                    full_response += visible
                                    clean_response += visible
                                    yield {"type": "assistant_text_delta", "text": visible}
                    break
            except aiohttp.ClientConnectorError:
                failure = f"Cannot reach server at {self.base_url}. Is it running?"
            except aiohttp.ServerTimeoutError:
                failure = "Server not responding. The model may be loading — try again."
            except Exception as exc:
                failure = str(exc) or type(exc).__name__

            if self._is_cancelled(turn_handle):
                # Cancelled turn: nothing is stored, the partial reply is dropped.
                yield {"type": "cancel_acknowledged"}
                return
            if failure or stream_error:
                yield {"type": "turn_failed", "message": failure or stream_error}
                return

            tail = tag_filter.flush()
            if tail:
                full_response += tail
                clean_response += tail
                yield {"type": "assistant_text_delta", "text": tail}

            if not full_response:
                message = "model returned no assistant content"
                if reasoning_announced or tag_filter.saw_reasoning:
                    message += "; reasoning was withheld from voice output"
                if finish_reason == "length":
                    message += "; the token limit was reached (raise QANTARA_OPENAI_MAX_TOKENS)"
                yield {"type": "turn_failed", "message": message}
                return

            # Commit user + assistant together only once the turn succeeded.
            self._commit_exchange(session_handle, transcript, clean_response.strip())
            yield {"type": "assistant_text_final", "text": full_response}
            yield {"type": "turn_completed"}
        finally:
            self._cleanup_turn(turn_handle)

    def _cleanup_turn(self, turn_handle: str) -> None:
        """Drop per-turn state after completion, cancellation, or failure."""
        self._active_responses.pop(turn_handle, None)
        self._active_clients.pop(turn_handle, None)
        self._active_turns.pop(turn_handle, None)
        self._turn_sessions.pop(turn_handle, None)
        self._turn_transcripts.pop(turn_handle, None)
        self._turn_context_prompts.pop(turn_handle, None)

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, Any]:
        if turn_handle not in self._turn_sessions:
            # Unknown or already finished: nothing to cancel, nothing to track.
            return {"status": "acknowledged", "detail": "turn is not active"}
        # Signal the streaming loop to stop
        self._active_turns[turn_handle] = False
        # Abort the in-flight HTTP exchange, including one still waiting for
        # response headers (cold model load, long prefill).
        resp = self._active_responses.pop(turn_handle, None)
        if resp is not None:
            resp.close()
        client = self._active_clients.pop(turn_handle, None)
        if client is not None and not client.closed:
            await client.close()
        return {"status": "acknowledged"}

    async def check_health(self) -> AdapterHealth:
        if not self.available:
            return AdapterHealth(
                status="degraded",
                degraded=True,
                detail="QANTARA_OPENAI_BASE_URL is not configured",
            )

        try:
            prefix = await self._resolve_api_prefix()
            timeout = aiohttp.ClientTimeout(total=self.timeout_connect)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.get(
                    f"{self.base_url}{prefix}/models",
                    headers=self._headers(),
                    allow_redirects=False,
                    **self._request_kwargs(),
                ) as resp:
                    if resp.status >= 400:
                        body = await read_bounded_response_text(resp)
                        return AdapterHealth(
                            status="degraded",
                            degraded=True,
                            detail=_normalize_error(body),
                        )
                    data = await read_bounded_response_json(resp)
                    if not isinstance(data, dict):
                        raise RuntimeError("model endpoint returned a non-object JSON response")
                    models = data.get("data", [])
                    if not isinstance(models, list):
                        raise RuntimeError("model endpoint returned an invalid model list")
                    model_ids = [
                        m["id"] for m in models if isinstance(m, dict) and isinstance(m.get("id"), str)
                    ]
                    preview = ", ".join(model_ids[:5]) or "none"
                    if self.model and not _model_is_listed(self.model, model_ids):
                        return AdapterHealth(
                            status="degraded",
                            degraded=True,
                            detail=f"configured model {self.model!r} is not served; available: {preview}",
                        )
                    detail = f"connected; {len(models)} model(s)"
                    if self.model:
                        detail += f"; using {self.model}"
                    elif model_ids:
                        detail += f"; available: {preview}"
                    return AdapterHealth(status="ok", detail=detail)
        except aiohttp.ClientConnectorError:
            return AdapterHealth(
                status="degraded",
                degraded=True,
                detail=f"cannot reach {self.base_url}",
            )
        except Exception as exc:
            return AdapterHealth(
                status="degraded",
                degraded=True,
                detail=str(exc),
            )
