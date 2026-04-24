import asyncio
import uuid

from adapters.base import AdapterConfig, AdapterHealth, RuntimeAdapter


class MockAdapter(RuntimeAdapter):
    def __init__(self, config: AdapterConfig | None = None) -> None:
        super().__init__(config or AdapterConfig(kind="mock", name="mock"))
        self._sessions = {}

    async def start_or_resume_session(self, client_context: dict | None = None) -> str:
        session_handle = str(uuid.uuid4())
        self._sessions[session_handle] = {
            "client_context": client_context or {},
            "turns": [],
        }
        return session_handle

    async def submit_user_turn(
        self,
        session_handle: str,
        transcript: str,
        turn_context: dict | None = None,
    ) -> str:
        if session_handle not in self._sessions:
            raise ValueError("unknown session handle")

        turn_handle = str(uuid.uuid4())
        self._sessions[session_handle]["turns"].append(
            {
                "turn_handle": turn_handle,
                "transcript": transcript,
                "turn_context": turn_context or {},
            }
        )
        return turn_handle

    async def stream_assistant_output(self, session_handle: str, turn_handle: str):
        if session_handle not in self._sessions:
            raise ValueError("unknown session handle")

        messages = [
            "This is a mock assistant response.",
            " It exists to exercise the gateway session flow.",
            " Runtime binding stays deferred for now.",
        ]

        for delta in messages:
            await asyncio.sleep(0.2)
            yield {"type": "assistant_text_delta", "text": delta}

        await asyncio.sleep(0.05)
        yield {"type": "assistant_text_final", "text": "".join(messages), "turn_handle": turn_handle}

    async def cancel_turn(
        self,
        session_handle: str,
        turn_handle: str,
        cancel_context: dict | None = None,
    ) -> dict:
        if session_handle not in self._sessions:
            raise ValueError("unknown session handle")
        return {
            "status": "acknowledged",
            "turn_handle": turn_handle,
            "cancel_context": cancel_context or {},
        }

    async def check_health(self) -> AdapterHealth:
        return AdapterHealth(status="ok")
