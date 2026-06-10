from __future__ import annotations

import unittest
from unittest.mock import patch

from adapters.base import AdapterConfig
from adapters.mcp_client import MCPClientAdapter
from adapters.openai_compatible import OpenAICompatibleAdapter


class OpenAIAdapterEvictionTests(unittest.IsolatedAsyncioTestCase):
    def _make_adapter(self, max_sessions: int) -> OpenAICompatibleAdapter:
        return OpenAICompatibleAdapter(
            AdapterConfig(
                kind="openai_compatible",
                name="test",
                options={"base_url": "http://127.0.0.1:9", "max_sessions": max_sessions},
            )
        )

    async def test_session_store_is_bounded(self) -> None:
        adapter = self._make_adapter(max_sessions=3)
        handles = [await adapter.start_or_resume_session() for _ in range(5)]
        self.assertEqual(len(adapter._sessions), 3)
        self.assertNotIn(handles[0], adapter._sessions)
        self.assertNotIn(handles[1], adapter._sessions)
        self.assertIn(handles[4], adapter._sessions)

    async def test_recently_used_session_survives_eviction(self) -> None:
        adapter = self._make_adapter(max_sessions=3)
        first = await adapter.start_or_resume_session()
        await adapter.start_or_resume_session()
        await adapter.start_or_resume_session()
        # Use the oldest session — it must be refreshed, not evicted next.
        await adapter.submit_user_turn(first, "hello")
        await adapter.start_or_resume_session()
        self.assertIn(first, adapter._sessions)


class MCPAdapterEvictionTests(unittest.IsolatedAsyncioTestCase):
    def _make_adapter(self, max_sessions: int) -> MCPClientAdapter:
        return MCPClientAdapter(
            AdapterConfig(
                kind="mcp_client",
                name="test",
                options={"command": "true", "max_sessions": max_sessions},
            )
        )

    async def test_session_store_is_bounded(self) -> None:
        adapter = self._make_adapter(max_sessions=3)
        handles = [await adapter.start_or_resume_session() for _ in range(5)]
        self.assertEqual(len(adapter._sessions), 3)
        self.assertNotIn(handles[0], adapter._sessions)
        self.assertIn(handles[4], adapter._sessions)

    async def test_turns_per_session_are_bounded(self) -> None:
        adapter = self._make_adapter(max_sessions=3)
        handle = await adapter.start_or_resume_session()
        for i in range(40):
            await adapter.submit_user_turn(handle, f"turn {i}")
        self.assertLessEqual(len(adapter._sessions[handle]["turns"]), 24)


class OllamaBackendEvictionTests(unittest.TestCase):
    def test_session_store_is_bounded(self) -> None:
        from gateway.ollama_session_backend.server import OllamaSessionBackend

        with patch("gateway.ollama_session_backend.server.MAX_SESSIONS", 3):
            backend = OllamaSessionBackend()
            handles = [backend.create_session() for _ in range(5)]
            self.assertEqual(len(backend.sessions), 3)
            self.assertNotIn(handles[0], backend.sessions)
            self.assertIn(handles[4], backend.sessions)

    def test_active_session_survives_eviction(self) -> None:
        from gateway.ollama_session_backend.server import OllamaSessionBackend

        with patch("gateway.ollama_session_backend.server.MAX_SESSIONS", 3):
            backend = OllamaSessionBackend()
            first = backend.create_session()
            backend.create_session()
            backend.create_session()
            backend.create_turn(first, "hello")
            backend.create_session()
            self.assertIn(first, backend.sessions)

    def test_turns_per_session_are_bounded(self) -> None:
        from gateway.ollama_session_backend.server import OllamaSessionBackend

        backend = OllamaSessionBackend()
        handle = backend.create_session()
        for i in range(40):
            backend.create_turn(handle, f"turn {i}")
        self.assertLessEqual(len(backend.sessions[handle].turns), 24)


class OpenClawBackendEvictionTests(unittest.TestCase):
    def test_session_store_and_side_maps_are_bounded(self) -> None:
        from gateway.openclaw_session_backend.server import OpenClawSessionBackend

        with patch("gateway.openclaw_session_backend.server.MAX_SESSIONS", 3):
            backend = OpenClawSessionBackend()
            handles = []
            for i in range(5):
                handle = backend.create_session({"client_session_id": f"client-{i}"})
                backend.get_session_lock(handle)
                handles.append(handle)
            self.assertEqual(len(backend.sessions), 3)
            self.assertNotIn(handles[0], backend.sessions)
            self.assertIn(handles[4], backend.sessions)
            # Side maps must not retain entries for evicted sessions.
            self.assertNotIn(handles[0], backend.session_locks)
            self.assertNotIn("client-0", backend.client_session_map)
            self.assertIn("client-4", backend.client_session_map)

    def test_active_session_survives_eviction(self) -> None:
        from gateway.openclaw_session_backend.server import OpenClawSessionBackend

        with patch("gateway.openclaw_session_backend.server.MAX_SESSIONS", 3):
            backend = OpenClawSessionBackend()
            first = backend.create_session({"client_session_id": "sticky"})
            backend.create_session()
            backend.create_session()
            backend.create_turn(first, "hello")
            backend.create_session()
            self.assertIn(first, backend.sessions)
            self.assertEqual(backend.client_session_map.get("sticky"), first)


if __name__ == "__main__":
    unittest.main()
