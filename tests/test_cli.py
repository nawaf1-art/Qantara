from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from qantara.cli import _apply_config_defaults, _apply_env, _classify_backend, build_parser, main
from qantara.config import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve(argv: list[str], env: dict[str, str], config_text: str | None = None) -> argparse.Namespace:
    """Parse argv and resolve startup values in an isolated environment."""
    with tempfile.TemporaryDirectory(prefix="qantara-cli-test-") as temp_dir:
        if config_text is not None:
            config = Path(temp_dir) / "qantara.yml"
            config.write_text(config_text, encoding="utf-8")
            argv = [*argv, "--config", str(config)]
        with patch.dict(os.environ, env, clear=True), patch("os.getcwd", return_value=temp_dir):
            args = build_parser().parse_args(argv)
            with patch("qantara.config._source_checkout_root", return_value=None):
                _apply_config_defaults(args)
            backend_type, url = _classify_backend(args.backend or "mock")
            _apply_env(backend_type, url, args)
            args.resolved_env = dict(os.environ)
    return args


class CliConfigurationTests(unittest.TestCase):
    def test_http_url_selects_and_configures_openai_adapter(self) -> None:
        backend_type, url = _classify_backend("http://127.0.0.1:11434/v1")
        args = argparse.Namespace(
            host="127.0.0.1",
            port=8765,
            model="qwen3.5:2b",
            agent=None,
            _config_backend_url="",
        )
        with patch.dict(os.environ, {}, clear=True):
            _apply_env(backend_type, url, args)
            self.assertEqual(os.environ["QANTARA_ADAPTER"], "openai_compatible")
            self.assertEqual(os.environ["QANTARA_OPENAI_BASE_URL"], url)
            self.assertEqual(os.environ["QANTARA_OPENAI_MODEL"], "qwen3.5:2b")

    def test_unknown_backend_warning_does_not_echo_credentials(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            backend_type, url = _classify_backend(
                "user:private-password@127.0.0.1:19120"
            )
        self.assertEqual(backend_type, "custom")
        self.assertIn("private-password", url)
        self.assertNotIn("private-password", output.getvalue())


class CliPrecedenceTests(unittest.TestCase):
    """Precedence: explicit CLI flags > environment > YAML file > defaults."""

    def test_flags_beat_environment_variables(self) -> None:
        env = {
            "QANTARA_OPENAI_MODEL": "env-openai-model",
            "QANTARA_OLLAMA_MODEL": "env-ollama-model",
            "QANTARA_SPIKE_PORT": "7000",
            "QANTARA_SPIKE_HOST": "127.0.0.2",
            "QANTARA_OPENAI_BASE_URL": "http://127.0.0.1:1/env",
        }
        args = _resolve(
            ["--backend", "http://127.0.0.1:11434", "--model", "flag-model", "--port", "9000", "--host", "127.0.0.1"],
            env,
        )
        self.assertEqual(args.port, 9000)
        self.assertEqual(args.resolved_env["QANTARA_SPIKE_PORT"], "9000")
        self.assertEqual(args.resolved_env["QANTARA_SPIKE_HOST"], "127.0.0.1")
        self.assertEqual(args.resolved_env["QANTARA_OPENAI_MODEL"], "flag-model")
        self.assertEqual(args.resolved_env["QANTARA_OPENAI_BASE_URL"], "http://127.0.0.1:11434")

    def test_environment_beats_config_file(self) -> None:
        config = "backend:\n  type: ollama\n  model: yaml-model\nserver:\n  port: 8100\n  host: 127.0.0.3\n"
        args = _resolve([], {"QANTARA_OLLAMA_MODEL": "env-model", "QANTARA_SPIKE_PORT": "8200"}, config)
        self.assertEqual(args.backend, "ollama")
        self.assertEqual(args.model, "env-model")
        self.assertEqual(args.port, 8200)
        self.assertEqual(args.host, "127.0.0.3")
        self.assertEqual(args.resolved_env["QANTARA_OLLAMA_MODEL"], "env-model")

    def test_config_file_beats_defaults(self) -> None:
        config = "backend:\n  type: ollama\n  model: yaml-model\nserver:\n  port: 8100\n"
        args = _resolve([], {}, config)
        self.assertEqual(args.backend, "ollama")
        self.assertEqual(args.port, 8100)
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.resolved_env["QANTARA_OLLAMA_MODEL"], "yaml-model")

    def test_defaults_apply_without_flags_env_or_file(self) -> None:
        args = _resolve([], {})
        self.assertEqual(args.backend, "")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        self.assertEqual(args.resolved_env["QANTARA_ADAPTER"], "mock")

    def test_env_model_does_not_clobber_adapter_specific_env(self) -> None:
        args = _resolve(
            ["--backend", "http://127.0.0.1:11434"],
            {"QANTARA_OLLAMA_MODEL": "ollama-name", "QANTARA_OPENAI_MODEL": "openai-name"},
        )
        self.assertEqual(args.resolved_env["QANTARA_OPENAI_MODEL"], "openai-name")

    def test_missing_config_file_is_an_error(self) -> None:
        args = build_parser().parse_args(["--config", "/nonexistent/qantara.yml"])
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ConfigError, "--config file not found"):
                _apply_config_defaults(args)

    def test_missing_qantara_config_env_file_is_an_error(self) -> None:
        args = build_parser().parse_args([])
        with patch.dict(os.environ, {"QANTARA_CONFIG": "/nonexistent/qantara.yml"}, clear=True):
            with self.assertRaisesRegex(ConfigError, "QANTARA_CONFIG file not found"):
                _apply_config_defaults(args)

    def test_bad_port_env_names_the_variable(self) -> None:
        args = build_parser().parse_args([])
        with patch.dict(os.environ, {"QANTARA_SPIKE_PORT": "eighty"}, clear=True):
            with patch("qantara.config._source_checkout_root", return_value=None), patch(
                "os.getcwd", return_value=tempfile.gettempdir()
            ):
                with self.assertRaisesRegex(ConfigError, "QANTARA_SPIKE_PORT must be an integer"):
                    _apply_config_defaults(args)

    def test_main_reports_config_errors_without_traceback(self) -> None:
        stderr = io.StringIO()
        with patch.dict(os.environ, {"QANTARA_SPIKE_PORT": "abc"}, clear=True), redirect_stderr(stderr):
            with patch("qantara.config._source_checkout_root", return_value=None), patch(
                "os.getcwd", return_value=tempfile.gettempdir()
            ):
                self.assertEqual(main([]), 2)
        self.assertIn("QANTARA_SPIKE_PORT must be an integer", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_main_dispatches_doctor_subcommand(self) -> None:
        with patch("qantara.doctor.main", return_value=0) as doctor_main:
            self.assertEqual(main(["doctor", "--mesh"]), 0)
        doctor_main.assert_called_once_with(["--mesh"])


class CliShimTests(unittest.TestCase):
    def test_root_cli_shim_prints_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "cli.py"), "--help"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("explicit CLI flags > environment variables", result.stdout)

    def test_root_config_shim_reexports_loader(self) -> None:
        import config as root_config
        import qantara.config

        self.assertIs(root_config.load_config, qantara.config.load_config)


if __name__ == "__main__":
    unittest.main()
