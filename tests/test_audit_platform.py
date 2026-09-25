"""Regression tests for the 2026-09-24 platform audit fixes (config, doctor,
voice control client, packaging and lock tooling)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

from qantara.config import (
    ConfigError,
    env_float,
    env_int,
    load_config,
    parse_simple_yaml,
)

try:
    from packaging.requirements import Requirement
except ImportError:  # the test extra does not install packaging; pip vendors it
    from pip._vendor.packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def _repo_text(relative: str) -> str:
    """Read a repository-only file; skip when running from the sdist."""
    path = ROOT / relative
    if not path.is_file():
        raise unittest.SkipTest(f"{relative} is not part of the source distribution")
    return path.read_text(encoding="utf-8")


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"audit_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class YamlLiteParserTests(unittest.TestCase):
    def test_quoted_values_keep_hash_and_drop_trailing_comment(self) -> None:
        parsed = parse_simple_yaml(
            'backend:\n'
            '  model: "qwen#3"   # trailing comment\n'
            "  agent: 'it''s'\n"
            '  url: "http://h:1/\\"x\\""\n'
        )
        self.assertEqual(parsed["backend"]["model"], "qwen#3")
        self.assertEqual(parsed["backend"]["agent"], "it's")
        self.assertEqual(parsed["backend"]["url"], 'http://h:1/"x"')

    def test_unquoted_hash_is_comment_only_after_whitespace(self) -> None:
        parsed = parse_simple_yaml(
            "backend:   # section comment\n"
            "  url: http://127.0.0.1:11434/#frag\n"
            "  model: qwen3.5:2b # comment\n"
            "  # full-line comment\n"
            "  type:\n"
        )
        self.assertEqual(parsed["backend"]["url"], "http://127.0.0.1:11434/#frag")
        self.assertEqual(parsed["backend"]["model"], "qwen3.5:2b")
        self.assertEqual(parsed["backend"]["type"], "")

    def test_malformed_input_raises_with_location(self) -> None:
        for text, message in (
            ('backend:\n  model: "unterminated\n', "unterminated"),
            ('backend:\n  model: "x" trailing\n', "unexpected text"),
            ("  model: x\n", "no section"),
            ("backend: ollama\n", "must be a section"),
            ("backend:\n\tmodel: x\n", "tabs"),
            ("backend:\n  just-a-word\n", "key: value"),
        ):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ConfigError, message):
                    parse_simple_yaml(text, source="qantara.yml")

    def test_unknown_keys_warn_and_are_ignored(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "qantara.yml"
            path.write_text("backend:\n  typo: x\n  model: m\nextra:\n  a: b\n", encoding="utf-8")
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                cfg = load_config(str(path))
        self.assertEqual(cfg["backend"]["model"], "m")
        self.assertNotIn("typo", cfg["backend"])
        self.assertIn("unknown config key backend.typo", stderr.getvalue())
        self.assertIn("unknown config section 'extra'", stderr.getvalue())

    def test_invalid_port_in_file_is_reported(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "qantara.yml"
            path.write_text("server:\n  port: 80a\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "server.port must be an integer"):
                load_config(str(path))


class EnvHelperTests(unittest.TestCase):
    def test_env_int_parses_defaults_and_names_variable(self) -> None:
        self.assertEqual(env_int("QANTARA_X", 5, environ={}), 5)
        self.assertEqual(env_int("QANTARA_X", 5, environ={"QANTARA_X": " 42 "}), 42)
        with self.assertRaisesRegex(ConfigError, "QANTARA_X must be an integer, got '4.2'"):
            env_int("QANTARA_X", 5, environ={"QANTARA_X": "4.2"})
        with self.assertRaisesRegex(ConfigError, "QANTARA_X must be <= 10"):
            env_int("QANTARA_X", 5, maximum=10, environ={"QANTARA_X": "11"})

    def test_env_float_rejects_non_finite(self) -> None:
        self.assertEqual(env_float("QANTARA_Y", 1.5, environ={"QANTARA_Y": "2.25"}), 2.25)
        for raw in ("nan", "inf", "abc"):
            with self.subTest(raw=raw), self.assertRaisesRegex(ConfigError, "QANTARA_Y"):
                env_float("QANTARA_Y", 1.0, environ={"QANTARA_Y": raw})


class DoctorTests(unittest.TestCase):
    def test_non_loopback_bind_without_token_fails(self) -> None:
        from qantara import doctor

        output = io.StringIO()
        with patch.dict(os.environ, {"QANTARA_SPIKE_HOST": "0.0.0.0"}, clear=True), redirect_stdout(output):
            self.assertFalse(doctor.check_exposure())
        self.assertIn("QANTARA_AUTH_TOKEN", output.getvalue())

    def test_non_loopback_bind_with_token_warns_about_tls(self) -> None:
        from qantara import doctor

        output = io.StringIO()
        env = {"QANTARA_SPIKE_HOST": "192.168.1.5", "QANTARA_AUTH_TOKEN": "x" * 32}
        with patch.dict(os.environ, env, clear=True), redirect_stdout(output):
            self.assertTrue(doctor.check_exposure())
        self.assertIn("TLS", output.getvalue())

    def test_loopback_names_are_recognised(self) -> None:
        from qantara.doctor import _is_loopback

        for host in ("127.0.0.1", "localhost", "::1", "[::1]", "127.1.2.3"):
            self.assertTrue(_is_loopback(host), host)
        for host in ("0.0.0.0", "192.168.1.2", "qantara.local", "::"):
            self.assertFalse(_is_loopback(host), host)

    def test_python_version_warning_for_kokoro(self) -> None:
        from qantara import doctor

        output = io.StringIO()
        with patch.object(doctor.sys, "version_info", (3, 13, 0, "final", 0)), redirect_stdout(output):
            self.assertTrue(doctor.check_python())
        self.assertIn("Kokoro", output.getvalue())

    def test_old_aiohttp_fails(self) -> None:
        from qantara import doctor

        output = io.StringIO()
        with patch.object(doctor, "_dist_version", return_value="3.13.5"), redirect_stdout(output):
            self.assertFalse(doctor.check_aiohttp())
        self.assertIn("aiohttp>=3.14", output.getvalue())

    def test_selected_missing_tts_fails_and_unsupported_is_reported(self) -> None:
        from qantara import doctor

        with patch.object(doctor, "_has_module", return_value=False), redirect_stdout(io.StringIO()):
            with patch.dict(os.environ, {"QANTARA_TTS_PROVIDER": "piper"}, clear=True):
                self.assertFalse(doctor.check_tts())
            with patch.dict(os.environ, {"QANTARA_TTS_PROVIDER": "nope"}, clear=True):
                self.assertFalse(doctor.check_tts())
            with patch.dict(os.environ, {}, clear=True):
                self.assertTrue(doctor.check_tts())

    def test_cuda_torch_is_flagged(self) -> None:
        from qantara import doctor

        output = io.StringIO()
        with patch.object(doctor, "_dist_version", return_value="2.13.0"), patch.object(
            doctor.sys, "platform", "linux"
        ), patch.object(doctor.importlib.metadata, "distributions", return_value=[]), redirect_stdout(output):
            doctor.check_torch()
        self.assertNotIn("CUDA", output.getvalue())
        output = io.StringIO()
        with patch.object(doctor, "_dist_version", return_value="2.13.0+cu130"), patch.object(
            doctor.sys, "platform", "linux"
        ), patch.object(doctor.importlib.metadata, "distributions", return_value=[]), redirect_stdout(output):
            doctor.check_torch()
        self.assertIn("CUDA build", output.getvalue())

    def test_bad_port_env_is_a_failure_not_a_traceback(self) -> None:
        from qantara import doctor

        output = io.StringIO()
        with patch.dict(os.environ, {"QANTARA_SPIKE_PORT": "abc"}, clear=True), redirect_stdout(output):
            self.assertFalse(doctor.check_port())
        self.assertIn("QANTARA_SPIKE_PORT must be an integer", output.getvalue())


class _FakeGateway:
    """In-process stand-in for /api/control/voice/* with bearer auth."""

    def __init__(self, token: str | None) -> None:
        self.token = token
        self.requests: list[tuple[str, str, dict]] = []

    def _authorized(self, request: web.Request) -> bool:
        return self.token is None or request.headers.get("Authorization") == f"Bearer {self.token}"

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        self.requests.append((request.method, request.path, body))
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        if request.path.endswith("/status"):
            return web.json_response({"ok": True, "active_session_count": 1, "sessions": [{"session_id": "s1"}]})
        if request.path.endswith("/speak"):
            if not body.get("text"):
                return web.json_response({"ok": False, "error": "missing text"}, status=400)
            return web.json_response({"ok": True, "status": "queued", "generation": 3})
        if request.path.endswith("/interrupt"):
            if body.get("session_id") == "missing":
                return web.json_response({"ok": False, "error": "no active browser voice session"}, status=404)
            return web.json_response({"ok": True, "status": "interrupted"})
        return web.json_response({"error": "not found"}, status=404)

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/api/control/voice/status", self.handle)
        app.router.add_post("/api/control/voice/speak", self.handle)
        app.router.add_post("/api/control/voice/interrupt", self.handle)
        return app


class VoiceControlClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fake = _FakeGateway(token="t" * 32)
        self.server = TestServer(self.fake.app())
        await self.server.start_server()
        self.base_url = str(self.server.make_url("")).rstrip("/")

    async def asyncTearDown(self) -> None:
        await self.server.close()

    async def test_status_speak_interrupt_round_trip(self) -> None:
        from qantara.control import VoiceControl

        async with VoiceControl(self.base_url, token="t" * 32) as voice:
            status = await voice.status()
            self.assertEqual(status["active_session_count"], 1)
            queued = await voice.speak("hello", voice_id="af_heart", interrupt=True, session_id="s1")
            self.assertEqual(queued["status"], "queued")
            stopped = await voice.interrupt(client_session_id="tab-1")
            self.assertEqual(stopped["status"], "interrupted")

        speak = self.fake.requests[1]
        self.assertEqual(speak[:2], ("POST", "/api/control/voice/speak"))
        self.assertEqual(
            speak[2], {"text": "hello", "interrupt": True, "voice_id": "af_heart", "session_id": "s1"}
        )
        self.assertEqual(self.fake.requests[2][2], {"client_session_id": "tab-1"})

    async def test_errors_raise_with_status_and_message(self) -> None:
        from qantara.control import VoiceControl, VoiceControlError

        async with VoiceControl(self.base_url, token="wrong-token-value-xxxxxxxxx") as voice:
            with self.assertRaises(VoiceControlError) as caught:
                await voice.status()
        self.assertEqual(caught.exception.status, 401)

        async with VoiceControl(self.base_url, token="t" * 32) as voice:
            with self.assertRaisesRegex(VoiceControlError, "no active browser voice session") as caught:
                await voice.interrupt(session_id="missing")
            self.assertEqual(caught.exception.status, 404)
            with self.assertRaises(ValueError):
                await voice.speak("   ")

    def test_rejects_credentials_and_non_http_urls(self) -> None:
        from qantara.control import VoiceControl

        for url in ("ftp://127.0.0.1", "127.0.0.1:8765", "http://user:pw@127.0.0.1:8765"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                VoiceControl(url)

    async def test_matches_real_gateway_routes(self) -> None:
        routes = (ROOT / "gateway" / "transport_spike" / "http_api.py").read_text(encoding="utf-8")
        for route in ('add_get("/api/control/voice/status"', 'add_post("/api/control/voice/speak"',
                      'add_post("/api/control/voice/interrupt"'):
            self.assertIn(route, routes)


class PackagingConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_console_scripts(self) -> None:
        scripts = self.pyproject["project"]["scripts"]
        self.assertEqual(scripts["qantara"], "qantara.cli:main")
        self.assertEqual(scripts["qantara-doctor"], "qantara.doctor:main")

    def test_kokoro_is_limited_to_supported_pythons(self) -> None:
        speech = [Requirement(item) for item in self.pyproject["project"]["optional-dependencies"]["speech"]]
        kokoro = next(req for req in speech if req.name == "kokoro")
        self.assertIsNotNone(kokoro.marker)
        self.assertTrue(kokoro.marker.evaluate({"python_version": "3.12"}))
        self.assertFalse(kokoro.marker.evaluate({"python_version": "3.13"}))

    def test_extras_use_ranges_with_upper_caps_and_no_wyoming(self) -> None:
        extras = self.pyproject["project"]["optional-dependencies"]
        for name in ("speech", "mesh", "mcp", "chatterbox", "test"):
            for item in extras[name]:
                req = Requirement(item)
                with self.subTest(extra=name, requirement=item):
                    self.assertNotEqual(req.name, "wyoming")
                    operators = {spec.operator for spec in req.specifier}
                    self.assertNotIn("==", operators)
                    self.assertIn("<", operators)
        self.assertIn("httpx", {Requirement(item).name for item in extras["mcp"]})

    def test_wheel_excludes_lock_files(self) -> None:
        excludes = self.pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["exclude"]
        self.assertIn("**/requirements*.txt", excludes)

    def test_notice_is_shipped_in_sdist(self) -> None:
        self.assertTrue((ROOT / "NOTICE").is_file())
        self.assertIn("NOTICE", self.pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"])

    def test_tool_pins_are_synchronised(self) -> None:
        dev = {item.split("==")[0]: item.split("==")[1] for item in self.pyproject["project"]["optional-dependencies"]["dev"]}
        test_yml = _repo_text(".github/workflows/test.yml")
        release_yml = _repo_text(".github/workflows/release.yml")
        precommit = _repo_text(".pre-commit-config.yaml")
        for tool in ("build", "ruff", "twine"):
            self.assertIn(f'"{tool}=={dev[tool]}"', test_yml, tool)
        for tool in ("build", "ruff", "twine", "pip-audit"):
            self.assertIn(f'"{tool}=={dev[tool]}"', release_yml, tool)
        self.assertIn(f"rev: v{dev['ruff']}", precommit)
        self.assertNotIn("id: ruff-format", precommit)


class LockHashCheckerTests(unittest.TestCase):
    def test_parser_and_platform_selection(self) -> None:
        module = _load_script("check_lock_hashes.py")
        entries = module.parse_lock(
            "--index-url https://pypi.org/simple\n"
            "markupsafe==3.0.3 \\\n"
            "    --hash=sha256:" + "a" * 64 + " \\\n"
            "    --hash=sha256:" + "b" * 64 + "\n"
            "    # via jinja2\n"
            "colorama==0.4.6 ; sys_platform == 'win32' \\\n"
            "    --hash=sha256:" + "c" * 64 + "\n"
        )
        self.assertEqual([(e.name, e.version, len(e.hashes)) for e in entries], [("markupsafe", "3.0.3", 2), ("colorama", "0.4.6", 1)])
        self.assertEqual(entries[1].marker, "sys_platform == 'win32'")

        files = [
            module.IndexFile("markupsafe-3.0.3-cp312-cp312-manylinux_2_17_x86_64.whl", "a" * 64),
            module.IndexFile("markupsafe-3.0.3-cp312-cp312-macosx_11_0_arm64.whl", "b" * 64),
            module.IndexFile("markupsafe-3.0.3-cp312-cp312-manylinux_2_17_aarch64.whl", "d" * 64),
        ]
        tags_x86 = module.supported_tags((3, 12), "linux_x86_64")
        tags_arm = module.supported_tags((3, 12), "linux_aarch64")
        self.assertIsNone(module.check_entry(entries[0], files, (3, 12), "linux_x86_64", tags_x86))
        self.assertIn("no locked wheel", module.check_entry(entries[0], files, (3, 12), "linux_aarch64", tags_arm))

    def test_repository_locks_route_only_torch_to_pytorch_index(self) -> None:
        for lock in ("ops/docker/requirements.txt", "gateway/transport_spike/requirements.txt"):
            text = _repo_text(lock)
            with self.subTest(lock=lock):
                self.assertNotIn("unsafe-best-match", text)
                self.assertIn("--extra-index-url https://download.pytorch.org/whl/cpu", text)
                self.assertNotIn("\nwyoming==", text)
                local_versions = [line.split(" ")[0] for line in text.splitlines() if "+cpu" in line and "==" in line]
                self.assertTrue(all(item.startswith("torch==") for item in local_versions), local_versions)
                markupsafe = text.split("\nmarkupsafe==", 1)[1].split("# via", 1)[0]
                self.assertGreater(markupsafe.count("--hash="), 20)


class DocsExampleTests(unittest.TestCase):
    def test_converse_example_buffers_partial_sse_lines(self) -> None:
        text = (ROOT / "docs" / "examples" / "clients" / "converse.mjs").read_text(encoding="utf-8")
        self.assertIn("buffer = lines.pop()", text)

    def test_speak_example_builds_json_safely(self) -> None:
        text = (ROOT / "docs" / "examples" / "clients" / "speak.sh").read_text(encoding="utf-8")
        self.assertIn("json.dumps", text)
        self.assertNotIn('\\"${1', text)

    def test_compose_has_model_cache_and_no_wyoming(self) -> None:
        text = _repo_text("docker-compose.yml")
        self.assertIn("qantara-model-cache:/home/qantara/.cache", text)
        self.assertNotIn("WYOMING", text)
        self.assertNotIn("QANTARA_MCP_SERVER_", text)

    def test_dockerignore_excludes_private_files(self) -> None:
        entries = set(_repo_text(".dockerignore").split())
        self.assertTrue({"CLAUDE.md", "AGENTS.md", "docs/audits", "tests", ".claude"} <= entries)

    def test_sbom_checker_rejects_lock_only_packages(self) -> None:
        module = _load_script("check_spdx_sbom.py")
        document = json.loads(json.dumps({
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "packages": [
                {"name": "qantara", "SPDXID": "q", "versionInfo": "1.0.0", "licenseDeclared": "Apache-2.0",
                 "filesAnalyzed": True,
                 "externalRefs": [{"referenceType": "purl", "referenceLocator": "pkg:pypi/qantara@1.0.0"}]},
                {"name": "aiohttp", "externalRefs": [{"referenceType": "purl", "referenceLocator": "pkg:pypi/aiohttp@3.14.3"}]},
                {"name": "torch"},
            ],
            "relationships": [{"relatedSpdxElement": "q", "relationshipType": "DESCRIBES"}],
        }))
        errors = module.validate_spdx_document(document, expected_name="qantara", expected_version="1.0.0")
        self.assertTrue(any("does not install" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
