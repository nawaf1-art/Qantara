"""Regression tests for the 2026-09-24 audit: OpenAI-compatible adapter.

Q-07a/AD-3 (inline reasoning), Q-07b/AD-2 (role order with the gateway's
real turn_context), B-2/AD-5 (context overflow, max_tokens), B-3/AD-6
(pending user message, per-turn cleanup), AD-12 (health model check),
AD-13 (SSE error frames).
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

from adapters.base import AdapterConfig
from adapters.openai_compatible import OpenAICompatibleAdapter

# The always-present keys speech.py puts in turn_context for a plain English
# voice turn (no detected language, no translation mode).
GATEWAY_DEFAULT_TURN_CONTEXT = {
    "source": "transport_spike",
    "modality": "voice",
    "primary_language": "en",
    "output_language": "en",
    "speech_rate": 1.0,
    "voice_id": "af_heart",
}


def _sse(content: str) -> bytes:
    return ("data: " + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n\n").encode()


def _assert_strict_alternation(test: unittest.TestCase, messages: list[dict]) -> None:
    """Mirror the Gemma/Mistral HF chat-template guard."""
    roles = [message["role"] for message in messages]
    test.assertEqual(roles.count("system"), 1 if roles and roles[0] == "system" else 0, roles)
    body = roles[1:] if roles and roles[0] == "system" else roles
    for index, role in enumerate(body):
        test.assertEqual(role, "user" if index % 2 == 0 else "assistant", roles)
    test.assertEqual(body[-1], "user", roles)


class _FakeOpenAIServer:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.models = [{"id": "test-model"}]
        self.reply_chunks: list[bytes] = [_sse("Sure."), b"data: [DONE]\n\n"]
        self.context_chars: int | None = None
        self.header_delay = 0.0
        self.server: TestServer | None = None

    async def models_handler(self, _: web.Request) -> web.Response:
        return web.json_response({"data": self.models})

    async def chat_handler(self, request: web.Request) -> web.StreamResponse:
        payload = await request.json()
        self.payloads.append(payload)
        if self.context_chars is not None:
            size = sum(len(message["content"]) for message in payload["messages"])
            if size > self.context_chars:
                return web.json_response(
                    {
                        "error": {
                            "code": 400,
                            "type": "exceed_context_size_error",
                            "message": "the request exceeds the available context size, try increasing it",
                        }
                    },
                    status=400,
                )
        if self.header_delay:
            await asyncio.sleep(self.header_delay)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for chunk in self.reply_chunks:
            await response.write(chunk)
        await response.write_eof()
        return response

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/v1/models", self.models_handler)
        app.router.add_post("/v1/chat/completions", self.chat_handler)
        self.server = TestServer(app)
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")

    async def close(self) -> None:
        if self.server is not None:
            await self.server.close()


class OpenAIAuditTestBase(unittest.IsolatedAsyncioTestCase):
    extra_options: dict = {}

    async def asyncSetUp(self) -> None:
        self.fake = _FakeOpenAIServer()
        base_url = await self.fake.start()
        options = {"base_url": base_url, "model": "test-model", **self.extra_options}
        self.adapter = OpenAICompatibleAdapter(
            AdapterConfig(kind="openai_compatible", name="audit", options=options)
        )

    async def asyncTearDown(self) -> None:
        await self.fake.close()

    async def _turn(self, session: str, text: str, turn_context: dict | None = None) -> list[dict]:
        turn = await self.adapter.submit_user_turn(session, text, turn_context)
        return [event async for event in self.adapter.stream_assistant_output(session, turn)]

    def _assert_no_turn_state(self) -> None:
        self.assertEqual(self.adapter._active_turns, {})
        self.assertEqual(self.adapter._turn_sessions, {})
        self.assertEqual(self.adapter._turn_context_prompts, {})
        self.assertEqual(self.adapter._active_responses, {})
        self.assertEqual(self.adapter._turn_transcripts, {})


class RoleOrderTests(OpenAIAuditTestBase):
    async def test_real_gateway_turn_context_keeps_strict_alternation(self) -> None:
        session = await self.adapter.start_or_resume_session()
        for index in range(1, 13):
            events = await self._turn(session, f"question {index}", GATEWAY_DEFAULT_TURN_CONTEXT)
            self.assertEqual(events[-1]["type"], "turn_completed")
            _assert_strict_alternation(self, self.fake.payloads[-1]["messages"])

    async def test_default_only_context_is_not_sent(self) -> None:
        session = await self.adapter.start_or_resume_session()
        await self._turn(session, "hello", GATEWAY_DEFAULT_TURN_CONTEXT)
        system = self.fake.payloads[-1]["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertNotIn("Qantara voice turn context", system["content"])

    async def test_directive_context_is_merged_into_the_first_system_message(self) -> None:
        session = await self.adapter.start_or_resume_session()
        context = {
            **GATEWAY_DEFAULT_TURN_CONTEXT,
            "input_language": "ar",
            "translation_mode": "assistant",
            "translation_directive": "Respond only in Arabic.",
        }
        await self._turn(session, "مرحبا", context)
        messages = self.fake.payloads[-1]["messages"]
        _assert_strict_alternation(self, messages)
        self.assertIn(self.adapter.system_prompt, messages[0]["content"])
        self.assertIn("Respond only in Arabic.", messages[0]["content"])
        # The directive is transient: it is not persisted in history.
        stored_system = self.adapter._sessions[session][0]["content"]
        self.assertNotIn("Respond only in Arabic.", stored_system)

    async def test_count_trim_removes_whole_pairs(self) -> None:
        session = await self.adapter.start_or_resume_session()
        for index in range(15):
            await self._turn(session, f"q{index}")
        history = self.adapter._sessions[session]
        self.assertEqual(history[0]["role"], "system")
        self.assertEqual(history[1]["role"], "user")
        self.assertEqual(len(history) % 2, 1)


class ReasoningFilterTests(OpenAIAuditTestBase):
    async def test_inline_think_block_is_not_spoken_or_stored(self) -> None:
        tokens = ["<think>", "\nOkay", ", the user asks", " about France.", "</thi", "nk>", "\n\n",
                  "Paris", " is the capital", " of France."]
        self.fake.reply_chunks = [_sse(token) for token in tokens] + [b"data: [DONE]\n\n"]
        session = await self.adapter.start_or_resume_session()
        events = await self._turn(session, "What is the capital of France?")

        deltas = "".join(event["text"] for event in events if event["type"] == "assistant_text_delta")
        self.assertEqual(deltas, "Paris is the capital of France.")
        final = [event for event in events if event["type"] == "assistant_text_final"][0]
        self.assertEqual(final["text"], deltas)
        activities = [event for event in events if event["type"] == "assistant_activity"]
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0]["activity_type"], "thinking")
        stored = self.adapter._sessions[session][-1]["content"]
        self.assertEqual(stored, "Paris is the capital of France.")
        self.assertNotIn("Okay", json.dumps(self.adapter._sessions[session]))

    async def test_separate_reasoning_field_surfaces_one_activity(self) -> None:
        reasoning = [
            ("data: " + json.dumps({"choices": [{"delta": {"reasoning_content": f"step {i}"}}]}) + "\n\n").encode()
            for i in range(5)
        ]
        self.fake.reply_chunks = reasoning + [_sse("Answer."), b"data: [DONE]\n\n"]
        session = await self.adapter.start_or_resume_session()
        events = await self._turn(session, "hi")
        activities = [event for event in events if event["type"] == "assistant_activity"]
        self.assertEqual(len(activities), 1)
        self.assertEqual(events[-1]["type"], "turn_completed")

    async def test_stream_starting_inside_reasoning_is_learned_for_later_turns(self) -> None:
        session = await self.adapter.start_or_resume_session()
        # First turn reveals the template style via a stray closing tag.
        self.fake.reply_chunks = [_sse("plan it"), _sse("</think>"), _sse("First answer."), b"data: [DONE]\n\n"]
        first = await self._turn(session, "one")
        self.assertEqual(first[-1]["type"], "turn_completed")
        self.assertEqual(self.adapter._sessions[session][-1]["content"], "First answer.")

        # Later turns withhold everything before the closing tag.
        self.fake.reply_chunks = [
            _sse("Okay, the user"), _sse(" wants a second answer."), _sse("</think>\n\n"),
            _sse("Second answer."), b"data: [DONE]\n\n",
        ]
        second = await self._turn(session, "two")
        deltas = "".join(event["text"] for event in second if event["type"] == "assistant_text_delta")
        self.assertEqual(deltas, "Second answer.")

    async def test_reasoning_start_can_be_forced(self) -> None:
        self.adapter.reasoning_start = "inside"
        self.fake.reply_chunks = [_sse("hidden plan"), _sse("</think>"), _sse("Answer."), b"data: [DONE]\n\n"]
        session = await self.adapter.start_or_resume_session()
        events = await self._turn(session, "hi")
        deltas = "".join(event["text"] for event in events if event["type"] == "assistant_text_delta")
        self.assertEqual(deltas, "Answer.")


class PendingUserMessageTests(OpenAIAuditTestBase):
    async def test_force_cancelled_turn_before_headers_leaves_no_history_or_state(self) -> None:
        # The gateway force-cancels the consumer task (CancelledError) when
        # the adapter does not finish within the cancel grace period.
        self.fake.header_delay = 5.0
        session = await self.adapter.start_or_resume_session()
        turn = await self.adapter.submit_user_turn(session, "question A")

        async def consume() -> list[dict]:
            return [event async for event in self.adapter.stream_assistant_output(session, turn)]

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual([m["role"] for m in self.adapter._sessions[session]], ["system"])
        self._assert_no_turn_state()

        self.fake.header_delay = 0.0
        await self._turn(session, "question B")
        sent = self.fake.payloads[-1]["messages"]
        self.assertEqual([(m["role"], m["content"]) for m in sent[1:]], [("user", "question B")])

    async def test_cancel_before_headers_aborts_the_request_promptly(self) -> None:
        self.fake.header_delay = 5.0
        session = await self.adapter.start_or_resume_session()
        turn = await self.adapter.submit_user_turn(session, "question A")

        async def consume() -> list[dict]:
            return [event async for event in self.adapter.stream_assistant_output(session, turn)]

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)
        await self.adapter.cancel_turn(session, turn)
        events = await asyncio.wait_for(task, timeout=2.0)

        self.assertEqual(events, [{"type": "cancel_acknowledged"}])
        self.assertEqual([m["role"] for m in self.adapter._sessions[session]], ["system"])
        self._assert_no_turn_state()

        self.fake.header_delay = 0.0
        await self._turn(session, "question B")
        sent = self.fake.payloads[-1]["messages"]
        self.assertEqual([(m["role"], m["content"]) for m in sent[1:]], [("user", "question B")])

    async def test_failed_turn_does_not_leave_user_message(self) -> None:
        self.fake.reply_chunks = [b'error: {"code":500,"message":"slot crashed"}\n\n']
        session = await self.adapter.start_or_resume_session()
        events = await self._turn(session, "hello")
        self.assertEqual(events[-1]["type"], "turn_failed")
        self.assertIn("slot crashed", events[-1]["message"])
        self.assertEqual([m["role"] for m in self.adapter._sessions[session]], ["system"])
        self._assert_no_turn_state()

    async def test_successful_turn_appends_user_and_assistant_together(self) -> None:
        session = await self.adapter.start_or_resume_session()
        turn = await self.adapter.submit_user_turn(session, "hello")
        # Nothing is stored until the turn succeeds.
        self.assertEqual([m["role"] for m in self.adapter._sessions[session]], ["system"])
        _ = [event async for event in self.adapter.stream_assistant_output(session, turn)]
        self.assertEqual(
            [m["role"] for m in self.adapter._sessions[session]], ["system", "user", "assistant"]
        )
        self._assert_no_turn_state()

    async def test_cancel_for_unknown_or_finished_turn_is_a_noop(self) -> None:
        session = await self.adapter.start_or_resume_session()
        await self._turn(session, "hello")
        for index in range(200):
            result = await self.adapter.cancel_turn(session, f"finished-{index}")
            self.assertEqual(result["status"], "acknowledged")
        self._assert_no_turn_state()

    async def test_never_started_turns_are_bounded(self) -> None:
        session = await self.adapter.start_or_resume_session()
        for index in range(600):
            await self.adapter.submit_user_turn(session, f"q{index}")
        self.assertLessEqual(len(self.adapter._turn_sessions), 256)
        self.assertLessEqual(len(self.adapter._turn_transcripts), 256)
        self.assertLessEqual(len(self.adapter._active_turns), 256)

    async def test_cancel_before_stream_start_yields_cancel_ack_without_request(self) -> None:
        session = await self.adapter.start_or_resume_session()
        turn = await self.adapter.submit_user_turn(session, "hello")
        await self.adapter.cancel_turn(session, turn)
        events = [event async for event in self.adapter.stream_assistant_output(session, turn)]
        self.assertEqual(events, [{"type": "cancel_acknowledged"}])
        self.assertEqual(self.fake.payloads, [])
        self._assert_no_turn_state()


class ContextBudgetTests(OpenAIAuditTestBase):
    async def test_context_overflow_drops_oldest_exchange_and_retries_once(self) -> None:
        reply = "This is a fairly detailed spoken answer. " * 30
        self.fake.reply_chunks = [_sse(reply), b"data: [DONE]\n\n"]
        self.fake.context_chars = 6000
        self.adapter.history_char_budget = 1_000_000
        session = await self.adapter.start_or_resume_session()
        outcomes = []
        for index in range(1, 11):
            events = await self._turn(session, f"question {index}")
            outcomes.append(events[-1]["type"])
        self.assertEqual(outcomes, ["turn_completed"] * 10)
        history = self.adapter._sessions[session]
        self.assertEqual(history[0]["role"], "system")
        self.assertEqual(history[1]["role"], "user")

    async def test_context_overflow_without_history_fails_once(self) -> None:
        self.fake.context_chars = 5
        session = await self.adapter.start_or_resume_session()
        events = await self._turn(session, "a question that is too long")
        self.assertEqual(events[-1]["type"], "turn_failed")
        self.assertEqual(len(self.fake.payloads), 1)
        self._assert_no_turn_state()

    async def test_history_is_trimmed_to_char_budget_in_pairs(self) -> None:
        self.adapter.history_char_budget = 100
        self.fake.reply_chunks = [_sse("x" * 30), b"data: [DONE]\n\n"]
        session = await self.adapter.start_or_resume_session()
        for index in range(6):
            await self._turn(session, f"question {index:02d} " + "y" * 10)
        history = self.adapter._sessions[session][1:]
        self.assertLessEqual(sum(len(m["content"]) for m in history), 100)
        self.assertEqual(history[0]["role"], "user")
        self.assertGreater(len(history), 0)

    async def test_max_tokens_is_sent_by_default(self) -> None:
        session = await self.adapter.start_or_resume_session()
        await self._turn(session, "hello")
        self.assertEqual(self.fake.payloads[-1]["max_tokens"], 512)

    async def test_max_tokens_env_override_and_disable(self) -> None:
        with patch.dict(os.environ, {"QANTARA_OPENAI_MAX_TOKENS": "0"}):
            adapter = OpenAICompatibleAdapter(
                AdapterConfig(kind="openai_compatible", name="x", options={"base_url": self.adapter.base_url, "model": "test-model"})
            )
        session = await adapter.start_or_resume_session()
        turn = await adapter.submit_user_turn(session, "hello")
        _ = [event async for event in adapter.stream_assistant_output(session, turn)]
        self.assertNotIn("max_tokens", self.fake.payloads[-1])
        with patch.dict(os.environ, {"QANTARA_OPENAI_MAX_TOKENS": "128", "QANTARA_OPENAI_HISTORY_CHAR_BUDGET": "321"}):
            adapter = OpenAICompatibleAdapter(
                AdapterConfig(kind="openai_compatible", name="x", options={"base_url": self.adapter.base_url})
            )
        self.assertEqual(adapter.max_tokens, 128)
        self.assertEqual(adapter.history_char_budget, 321)


class StreamErrorTests(OpenAIAuditTestBase):
    async def test_mid_stream_error_object_is_a_failure(self) -> None:
        self.fake.reply_chunks = [
            _sse("partial "),
            b'data: {"error": {"message": "backend overloaded"}}\n\n',
        ]
        session = await self.adapter.start_or_resume_session()
        events = await self._turn(session, "hello")
        self.assertEqual(events[-1]["type"], "turn_failed")
        self.assertIn("backend overloaded", events[-1]["message"])
        self.assertNotIn("assistant_text_final", [event["type"] for event in events])


class HealthModelTests(OpenAIAuditTestBase):
    async def test_health_is_degraded_when_configured_model_missing(self) -> None:
        self.fake.models = [{"id": "llama3.2:3b"}]
        self.adapter.model = "gemma3:4b"
        health = await self.adapter.check_health()
        self.assertTrue(health.degraded)
        self.assertIn("gemma3:4b", health.detail)

    async def test_health_is_ok_when_configured_model_present(self) -> None:
        health = await self.adapter.check_health()
        self.assertFalse(health.degraded)


if __name__ == "__main__":
    unittest.main()
