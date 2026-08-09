from __future__ import annotations

import argparse
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cli import _apply_env, _classify_backend


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


if __name__ == "__main__":
    unittest.main()
