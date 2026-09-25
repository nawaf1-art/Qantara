"""Browser-client regression tests for the 2026-09-24 audit fixes.

The client pages are vanilla JS inline in HTML (no build step), so these
tests run the real inline scripts under node:vm with DOM / WebAudio /
WebSocket stubs (tests/fixtures/client/harness.js). Each check is a small
node program that exits non-zero on failure. Skipped when node is absent.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "client"
NODE = shutil.which("node")


def _run_check(script: str, check: str) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, str(FIXTURES / script), check],
        cwd=str(FIXTURES),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


class _NodeChecks(unittest.TestCase):
    script = ""

    def setUp(self) -> None:
        if NODE is None:
            self.skipTest("node is not installed")

    def check(self, name: str) -> None:
        result = _run_check(self.script, name)
        self.assertEqual(
            result.returncode,
            0,
            f"{self.script} {name} failed:\n{result.stdout}\n{result.stderr}",
        )


def _add_checks(cls: type[_NodeChecks], names: list[str]) -> None:
    for name in names:
        def test(self: _NodeChecks, _name: str = name) -> None:
            self.check(_name)

        test.__name__ = f"test_{name}"
        test.__doc__ = f"{cls.script}: {name}"
        setattr(cls, test.__name__, test)


class VoicePageChecks(_NodeChecks):
    script = "voice_checks.js"


class SetupPageChecks(_NodeChecks):
    script = "setup_checks.js"


class TranslatePageChecks(_NodeChecks):
    script = "translate_checks.js"


_add_checks(
    VoicePageChecks,
    [
        "ws_url_uses_location_host",
        "double_connect_and_stale_socket",
        "double_start_mic_is_guarded",
        "reconnect_restores_mic",
        "device_loss_and_recovery",
        "audio_context_suspend_is_handled",
        "bargein_rearms_on_playback_cleared",
        "late_frames_after_clear_are_dropped",
        "clear_ack_timeout_rearms",
        "weak_speech_filter_rejects_short_bursts",
        "default_audio_mode_is_headset",
        "speakers_bargein_utterance_is_submitted",
        "deferred_submit_expires",
        "speakers_threshold_tracks_echo",
        "playout_scheduler_cushion_and_detune",
        "jitter_produces_no_gaps",
        "sample_rate_changes_only_between_utterances",
        "mic_errors_are_explained",
        "echo_cancellation_all_with_fallback",
        "capture_uses_worklet_with_fallback",
        "resampler_frequency_response",
        "conversation_panel_is_event_driven",
        "barge_in_keeps_old_turn_text_separate",
        "state_caption_and_start_gesture",
        "debug_log_is_bounded",
        "speech_rate_sent_only_when_user_set",
        "avatar_returns_to_rest",
        "voice_page_has_no_innerhtml_or_inline_handlers",
    ],
)
_add_checks(
    SetupPageChecks,
    [
        "mesh_peers_rendered_as_text",
        "no_markup_injection_or_inline_handlers",
        "copy_button_falls_back",
        "restore_saved_settings_once",
        "restore_waits_for_backend_then_stops",
        "cards_are_keyboard_operable",
        "status_messages_are_live_regions",
    ],
)
_add_checks(
    TranslatePageChecks,
    [
        "quick_tap_during_permission_prompt",
        "held_press_through_prompt_records",
        "keyboard_and_touchcancel",
        "translating_status_clears",
        "insecure_context_is_explained",
    ],
)


class ClientScriptSyntaxTests(unittest.TestCase):
    """Every inline script and the worklet module must parse (node --check)."""

    def setUp(self) -> None:
        if NODE is None:
            self.skipTest("node is not installed")

    def test_inline_scripts_parse(self) -> None:
        pattern = re.compile(r"<script(\s[^>]*)?>([\s\S]*?)</script>")
        for page in ("transport-spike", "setup", "translate"):
            html = (REPO_ROOT / "client" / page / "index.html").read_text(encoding="utf-8")
            for index, match in enumerate(pattern.finditer(html)):
                if match.group(1) and "src=" in match.group(1):
                    continue
                with self.subTest(page=page, script=index):
                    result = subprocess.run(
                        [NODE, "--check", "-"],
                        input=match.group(2),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_worklet_module_parses(self) -> None:
        worklet = REPO_ROOT / "client" / "transport-spike" / "mic-capture-worklet.js"
        result = subprocess.run([NODE, "--check", str(worklet)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_lists_match(self) -> None:
        """Every node check is wired into this unittest module."""
        for cls in (VoicePageChecks, SetupPageChecks, TranslatePageChecks):
            result = subprocess.run(
                [NODE, str(FIXTURES / cls.script), "--list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            listed = set(result.stdout.split())
            wired = {name[len("test_"):] for name in dir(cls) if name.startswith("test_")}
            self.assertEqual(listed, wired, cls.script)


class WorkletIsServedTests(unittest.TestCase):
    def test_worklet_lives_in_the_statically_served_spike_dir(self) -> None:
        from gateway.transport_spike.common import CLIENT_SPIKE_DIR

        self.assertTrue((Path(CLIENT_SPIKE_DIR) / "mic-capture-worklet.js").is_file())
        page = (Path(CLIENT_SPIKE_DIR) / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="mic-capture-worklet.js"></script>', page)
        self.assertIn('const WORKLET_MODULE_URL = "mic-capture-worklet.js";', page)


if __name__ == "__main__":
    unittest.main()
