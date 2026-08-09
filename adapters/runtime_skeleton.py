from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter

MAX_TURNS_PER_SESSION = 24


class RuntimeSkeletonAdapter(RuntimeAdapter):
    """
    Placeholder adapter for the first real backend path.

    This adapter intentionally does not bind to a concrete runtime yet.
    It exists so the gateway can exercise a real adapter selection path
    without coupling Qantara to the user's current local agents.
    """

    def __init__(self, config: AdapterConfig | None = None) -> None:
        super().__init__(config or AdapterConfig(kind="runtime_skeleton", name="runtime-skeleton"))
        self._sessions: dict[str, dict[str, Any]] = {}
        self.max_sessions = max(
            1,
            int(
                self.config.options.get("max_sessions")
                or os.environ.get("QANTARA_RUNTIME_SKELETON_MAX_SESSIONS", "64")
            ),
        )

    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        session_handle = str(uuid.uuid4())
        self._sessions[session_handle] = {
            "client_context": client_context or {},
            "turns": [],
        }
        while len(self._sessions) > self.max_sessions:
            self._sessions.pop(next(iter(self._sessions)), None)
        return session_handle

    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        if session_handle not in self._sessions:
            raise ValueError("unknown session handle")

        self._sessions[session_handle] = self._sessions.pop(session_handle)

        turn_handle = str(uuid.uuid4())
        self._sessions[session_handle]["turns"].append(
            {
                "turn_handle": turn_handle,
                "transcript": transcript,
                "turn_context": turn_context or {},
            }
        )
        turns = self._sessions[session_handle]["turns"]
        if len(turns) > MAX_TURNS_PER_SESSION:
            del turns[: len(turns) - MAX_TURNS_PER_SESSION]
        return turn_handle

    async def stream_assistant_output(
        self,
        session_handle: str,
        turn_handle: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if session_handle not in self._sessions:
            raise ValueError("unknown session handle")

        message = (
            "Runtime adapter skeleton is wired. "
            "A concrete downstream runtime is still intentionally deferred."
        )
        yield {"type": "assistant_text_final", "text": message, "turn_handle": turn_handle}

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict[str, Any]:
        if session_handle not in self._sessions:
            raise ValueError("unknown session handle")
        return {
            "status": "unsupported",
            "turn_handle": turn_handle,
            "reason": "runtime adapter skeleton does not implement cancellation yet",
            "cancel_context": cancel_context or {},
        }

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(
            status="degraded_but_usable",
            degraded=True,
            detail="adapter framework is wired but no concrete runtime backend is bound yet",
        )
