from __future__ import annotations


def assert_session_ready_payload(testcase, payload: dict) -> None:
    testcase.assertEqual(payload["type"], "session_ready")
    testcase.assertIn("session_id", payload)
    testcase.assertIn("client_session_id", payload)
    testcase.assertIn("voice_defaults", payload)
    testcase.assertIn("allowed_transforms", payload)
    testcase.assertIn("active_transforms", payload)


def assert_tts_status_payload(testcase, payload: dict) -> None:
    testcase.assertEqual(payload["type"], "tts_status")
    testcase.assertIn("engine", payload)
    testcase.assertIn("voice_id", payload)
    testcase.assertIn("allowed_transforms", payload)
    testcase.assertIn("active_transforms", payload)


def assert_playback_cleared_payload(testcase, payload: dict) -> None:
    testcase.assertEqual(payload["type"], "playback_cleared")
    testcase.assertIn("generation", payload)


def assert_transcript_result_payload(testcase, payload: dict) -> None:
    testcase.assertEqual(payload["type"], "transcript_result")
    testcase.assertIn("engine", payload)
    testcase.assertIn("text", payload)
