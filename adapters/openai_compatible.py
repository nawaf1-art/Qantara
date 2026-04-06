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
from typing import Any, AsyncIterator

import aiohttp

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter

# Voice-optimized system prompt: short responses, conversational, no markdown.
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful voice assistant having a real-time spoken conversation. "
    "Keep every response to 1-2 sentences. Use natural, conversational language "
    "with contractions. Never use markdown, bullet points, lists, or formatting. "
    "Never use emojis. If unclear, ask a brief clarifying question. "
    "Start with natural acknowledgments when appropriate."
)

# Max conversation turns to keep (system prompt + last N exchanges).
MAX_HISTORY_TURNS = 20


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

        # Per-session conversation history: session_handle -> messages list
        self._sessions: dict[str, list[dict[str, str]]] = {}
        # Track active turns for cancellation
        self._active_turns: dict[str, bool] = {}
        # Detected /v1 prefix (auto-probed on first use)
        self._api_prefix: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _resolve_api_prefix(self) -> str:
        """Auto-detect whether the server needs /v1 prefix."""
        if self._api_prefix is not None:
            return self._api_prefix

        timeout = aiohttp.ClientTimeout(total=self.timeout_connect)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Try /v1/models first (most common)
            for prefix in ("/v1", ""):
                try:
                    async with session.get(
                        f"{self.base_url}{prefix}/models",
                        headers=self._headers(),
                    ) as resp:
                        if resp.status < 400:
                            self._api_prefix = prefix
                            return prefix
                except Exception:
                    continue

        # Default to /v1 if we can't detect
        self._api_prefix = "/v1"
        return "/v1"

    async def _auto_detect_model(self) -> str:
        """Pick the first available model if none is configured."""
        prefix = await self._resolve_api_prefix()
        timeout = aiohttp.ClientTimeout(total=self.timeout_connect)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{self.base_url}{prefix}/models",
                    headers=self._headers(),
                ) as resp:
                    if resp.status >= 400:
                        return ""
                    data = await resp.json()
                    models = data.get("data", [])
                    if models:
                        return models[0].get("id", "")
        except Exception:
            pass
        return ""

    async def start_or_resume_session(
        self, client_context: dict | None = None
    ) -> str:
        session_handle = str(uuid.uuid4())
        # Initialize conversation with system prompt
        self._sessions[session_handle] = [
            {"role": "system", "content": self.system_prompt}
        ]
        return session_handle

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
        return turn_handle

    async def stream_assistant_output(
        self,
        session_handle: str,
        turn_handle: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self.available:
            raise RuntimeError("OpenAI-compatible backend URL is not configured")

        messages = self._sessions.get(session_handle, [])
        if not messages:
            yield {"type": "turn_failed", "message": "no session found"}
            return

        # Resolve model and API prefix
        model = self.model or await self._auto_detect_model()
        if not model:
            yield {"type": "turn_failed", "message": "no model configured or detected"}
            return

        prefix = await self._resolve_api_prefix()
        url = f"{self.base_url}{prefix}/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        timeout = aiohttp.ClientTimeout(
            sock_connect=self.timeout_connect,
            sock_read=self.timeout_first_token,
        )

        full_response = ""

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        error_msg = _normalize_error(body)
                        yield {"type": "turn_failed", "message": error_msg}
                        return

                    # Parse SSE stream
                    buffer = ""
                    async for chunk in resp.content:
                        if not self._active_turns.get(turn_handle, False):
                            break  # Cancelled

                        buffer += chunk.decode("utf-8", errors="replace")

                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()

                            if not line:
                                continue

                            # Strip "data: " or "data:" prefix
                            if line.startswith("data: "):
                                data_str = line[6:]
                            elif line.startswith("data:"):
                                data_str = line[5:]
                            else:
                                continue

                            data_str = data_str.strip()

                            # Stream end signal
                            if data_str == "[DONE]":
                                break

                            if not data_str:
                                continue

                            try:
                                event = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            # Extract content from delta
                            choices = event.get("choices", [])
                            if not choices:
                                continue

                            delta = choices[0].get("delta", {})
                            # Handle both content and reasoning_content (vLLM)
                            content = (
                                delta.get("content")
                                or delta.get("reasoning_content")
                                or ""
                            )

                            if content:
                                full_response += content
                                yield {
                                    "type": "assistant_text_delta",
                                    "text": content,
                                }

        except aiohttp.ClientConnectorError:
            yield {
                "type": "turn_failed",
                "message": f"Cannot reach server at {self.base_url}. Is it running?",
            }
            return
        except aiohttp.ServerTimeoutError:
            yield {
                "type": "turn_failed",
                "message": "Server not responding. The model may be loading — try again.",
            }
            return
        except Exception as exc:
            yield {
                "type": "turn_failed",
                "message": str(exc),
            }
            return

        # Emit final text
        if full_response:
            yield {"type": "assistant_text_final", "text": full_response}
            # Save assistant response to conversation history
            if session_handle in self._sessions:
                self._sessions[session_handle].append(
                    {"role": "assistant", "content": full_response}
                )

        # Clean up turn
        self._active_turns.pop(turn_handle, None)
        yield {"type": "turn_completed"}

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, Any]:
        # Signal the streaming loop to stop
        self._active_turns[turn_handle] = False
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
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{self.base_url}{prefix}/models",
                    headers=self._headers(),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        return AdapterHealth(
                            status="degraded",
                            degraded=True,
                            detail=_normalize_error(body),
                        )
                    data = await resp.json()
                    models = data.get("data", [])
                    model_names = [m.get("id", "?") for m in models[:5]]
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
