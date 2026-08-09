"""OpenAI-compatible adapter for Qantara.

Connects directly to any server exposing /v1/chat/completions.
Covers: Ollama (OpenAI mode), llama.cpp, vLLM, LiteLLM, LocalAI,
Jan.ai, LM Studio, and any other OpenAI-compatible server.

No bridge process needed — the adapter speaks the OpenAI chat
completions protocol directly.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter
from gateway.session_backend_prompts import build_voice_turn_context_prompt
from qantara.http_safety import (
    HTTPResponseLimitError,
    read_bounded_response_json,
    read_bounded_response_text,
)
from qantara.streaming import iter_sse_json_objects

# Voice-optimized system prompt: short responses, conversational, no markdown.
DEFAULT_SYSTEM_PROMPT = (
    "You are a voice assistant. Keep replies short and conversational. No markdown or formatting."
)

# Max conversation turns to keep (system prompt + last N exchanges).
MAX_HISTORY_TURNS = 20
MAX_ASSISTANT_TEXT_CHARS = 1024 * 1024


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
    err = data.get("error")
    if isinstance(err, str):
        return err  # Ollama: {"error": "string"}
    if isinstance(err, dict):
        return err.get("message", str(err))  # OpenAI: {"error": {"message": "..."}}
    return body.strip() or "unknown error"


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


class OpenAICompatibleAdapter(RuntimeAdapter):
    """Adapter that speaks the OpenAI chat completions protocol directly."""

    def __init__(self, config: AdapterConfig | None = None) -> None:
        super().__init__(
            config or AdapterConfig(kind="openai_compatible", name="openai-compatible")
        )
        raw_url = (
            self.config.options.get("base_url")
            or os.environ.get("QANTARA_OPENAI_BASE_URL", "")
        )
        self.base_url = _normalize_base_url(raw_url)
        self.outbound_host_header = str(
            self.config.options.get("outbound_host_header") or ""
        )
        self.outbound_server_hostname = str(
            self.config.options.get("outbound_server_hostname") or ""
        )
        self.api_key = (
            self.config.options.get("api_key")
            or os.environ.get("QANTARA_OPENAI_API_KEY", "not-needed")
        )
        self.model = (
            self.config.options.get("model")
            or os.environ.get("QANTARA_OPENAI_MODEL", "")
        )
        self.system_prompt = (
            self.config.options.get("system_prompt")
            or os.environ.get("QANTARA_OPENAI_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)
        )
        self.timeout_connect = float(
            self.config.options.get("timeout_connect")
            or os.environ.get("QANTARA_OPENAI_TIMEOUT_CONNECT", "5")
        )
        self.timeout_first_token = float(
            self.config.options.get("timeout_first_token")
            or os.environ.get("QANTARA_OPENAI_TIMEOUT_FIRST_TOKEN", "30")
        )
        self.reasoning_effort = (
            self.config.options.get("reasoning_effort")
            or os.environ.get("QANTARA_OPENAI_REASONING_EFFORT", "")
        ).strip()

        self.max_sessions = int(
            self.config.options.get("max_sessions")
            or os.environ.get("QANTARA_OPENAI_MAX_SESSIONS", "64")
        )
        # Per-session conversation history: session_handle -> messages list.
        # Bounded: least-recently-used sessions are evicted beyond max_sessions.
        self._sessions: dict[str, list[dict[str, str]]] = {}
        # Track active turns for cancellation
        self._active_turns: dict[str, bool] = {}
        # Track turn -> session mapping for rollback on failure
        self._turn_sessions: dict[str, str] = {}
        # Transient per-turn voice context (not persisted in history)
        self._turn_context_prompts: dict[str, str] = {}
        # Active response objects for aborting HTTP connections on cancel
        self._active_responses: dict[str, aiohttp.ClientResponse] = {}
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

    async def start_or_resume_session(
        self, client_context: dict | None = None
    ) -> str:
        session_handle = str(uuid.uuid4())
        # Initialize conversation with system prompt
        self._sessions[session_handle] = [
            {"role": "system", "content": self.system_prompt}
        ]
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
            self._sessions[session_handle] = [
                {"role": "system", "content": self.system_prompt}
            ]
            self._evict_stale_sessions()
        else:
            self._touch_session(session_handle)

        # Append user message
        self._sessions[session_handle].append(
            {"role": "user", "content": transcript}
        )

        # Truncate history if too long (keep system prompt + last N turns)
        messages = self._sessions[session_handle]
        if len(messages) > MAX_HISTORY_TURNS + 1:  # +1 for system prompt
            self._sessions[session_handle] = [messages[0]] + messages[-(MAX_HISTORY_TURNS):]

        turn_handle = str(uuid.uuid4())
        self._active_turns[turn_handle] = True
        self._turn_sessions[turn_handle] = session_handle
        # Store voice turn context if provided — used transiently at request
        # time and NOT persisted into the session history so subsequent turns
        # don't compound directives.
        context_prompt = build_voice_turn_context_prompt(turn_context)
        if context_prompt:
            self._turn_context_prompts[turn_handle] = context_prompt
        return turn_handle

    async def stream_assistant_output(
        self,
        session_handle: str,
        turn_handle: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self.available:
            self._cleanup_turn(turn_handle)
            raise RuntimeError("OpenAI-compatible backend URL is not configured")

        messages = self._sessions.get(session_handle, [])
        if not messages:
            self._rollback_user_message(session_handle)
            self._cleanup_turn(turn_handle)
            yield {"type": "turn_failed", "message": "no session found"}
            return

        # Apply transient voice turn context: insert as a system message
        # just before the latest user turn, but only for this request — not
        # persisted in the session history.
        context_prompt = self._turn_context_prompts.pop(turn_handle, None)
        if context_prompt:
            # messages is a reference; don't mutate. Rebuild with context inserted.
            messages_for_request = list(messages)
            # Insert context right before the last user turn.
            if messages_for_request and messages_for_request[-1].get("role") == "user":
                messages_for_request.insert(-1, {"role": "system", "content": context_prompt})
            else:
                messages_for_request.append({"role": "system", "content": context_prompt})
            messages = messages_for_request

        # Resolve model and API prefix
        model = self.model or await self._auto_detect_model()
        if not model:
            self._rollback_user_message(session_handle)
            self._cleanup_turn(turn_handle)
            yield {"type": "turn_failed", "message": "no model configured or detected"}
            return

        prefix = await self._resolve_api_prefix()
        url = f"{self.base_url}{prefix}/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        timeout = aiohttp.ClientTimeout(
            sock_connect=self.timeout_connect,
            sock_read=self.timeout_first_token,
        )

        full_response = ""
        saw_reasoning = False
        stream_error = ""

        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    allow_redirects=False,
                    **self._request_kwargs(),
                ) as resp:
                    # Store response for cancellation
                    self._active_responses[turn_handle] = resp

                    if resp.status >= 400:
                        body = await read_bounded_response_text(resp)
                        error_msg = _normalize_error(body)
                        self._rollback_user_message(session_handle)
                        self._cleanup_turn(turn_handle)
                        yield {"type": "turn_failed", "message": error_msg}
                        return

                    async for event in iter_sse_json_objects(resp.content):
                        if not self._active_turns.get(turn_handle, False):
                            break  # Cancelled

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

                        content, event_has_reasoning = _extract_answer_delta(
                            choices[0].get("delta", {})
                        )
                        saw_reasoning = saw_reasoning or event_has_reasoning
                        if content:
                            if len(full_response) + len(content) > MAX_ASSISTANT_TEXT_CHARS:
                                stream_error = "assistant output exceeded the configured limit"
                                break
                            full_response += content
                            yield {
                                "type": "assistant_text_delta",
                                "text": content,
                            }

        except aiohttp.ClientConnectorError:
            yield self._finish_failed_or_cancelled(
                session_handle,
                turn_handle,
                f"Cannot reach server at {self.base_url}. Is it running?",
            )
            return
        except aiohttp.ServerTimeoutError:
            yield self._finish_failed_or_cancelled(
                session_handle,
                turn_handle,
                "Server not responding. The model may be loading — try again.",
            )
            return
        except Exception as exc:
            yield self._finish_failed_or_cancelled(
                session_handle,
                turn_handle,
                str(exc),
            )
            return

        if stream_error:
            self._rollback_user_message(session_handle)
            self._cleanup_turn(turn_handle)
            yield {"type": "turn_failed", "message": stream_error}
            return

        # Clean up turn tracking
        was_cancelled = not self._active_turns.get(turn_handle, False)
        self._cleanup_turn(turn_handle)

        if was_cancelled:
            # Cancelled turn: emit cancel_acknowledged, do NOT save partial response
            self._rollback_user_message(session_handle)
            yield {"type": "cancel_acknowledged"}
            return

        if not full_response:
            self._rollback_user_message(session_handle)
            message = "model returned no assistant content"
            if saw_reasoning:
                message += "; reasoning was withheld from voice output"
            yield {"type": "turn_failed", "message": message}
            return

        # Emit final text for completed turns only
        yield {"type": "assistant_text_final", "text": full_response}
        # Save assistant response to conversation history
        if session_handle in self._sessions:
            self._sessions[session_handle].append(
                {"role": "assistant", "content": full_response}
            )

        yield {"type": "turn_completed"}

    def _rollback_user_message(self, session_handle: str) -> None:
        """Remove the last user message from history on turn failure."""
        messages = self._sessions.get(session_handle, [])
        if messages and messages[-1].get("role") == "user":
            messages.pop()

    def _finish_failed_or_cancelled(
        self,
        session_handle: str,
        turn_handle: str,
        message: str,
    ) -> dict[str, str]:
        """Clean up a failed stream while preserving cancellation semantics."""
        was_cancelled = not self._active_turns.get(turn_handle, False)
        self._rollback_user_message(session_handle)
        self._cleanup_turn(turn_handle)
        if was_cancelled:
            return {"type": "cancel_acknowledged"}
        return {"type": "turn_failed", "message": message}

    def _cleanup_turn(self, turn_handle: str) -> None:
        """Drop per-turn state after completion, cancellation, or failure."""
        self._active_responses.pop(turn_handle, None)
        self._active_turns.pop(turn_handle, None)
        self._turn_sessions.pop(turn_handle, None)
        self._turn_context_prompts.pop(turn_handle, None)

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, Any]:
        # Signal the streaming loop to stop
        self._active_turns[turn_handle] = False
        # Close the HTTP response to abort the in-flight stream immediately
        resp = self._active_responses.pop(turn_handle, None)
        if resp is not None:
            resp.close()
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
                    model_names = [
                        m.get("id", "?")
                        for m in models[:5]
                        if isinstance(m, dict)
                    ]
                    detail = f"connected; {len(models)} model(s)"
                    if self.model:
                        detail += f"; using {self.model}"
                    elif model_names:
                        detail += f"; available: {', '.join(model_names)}"
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
