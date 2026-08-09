from __future__ import annotations

import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = Path(__file__).resolve().parent.parent


class SDKImportTests(unittest.TestCase):
    def test_voice_gateway_importable_from_qantara(self) -> None:
        from qantara import VoiceGateway  # noqa: F401

    def test_version_matches_version_file(self) -> None:
        import qantara

        version_file = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(qantara.__version__, version_file)


class VoiceGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_app_serves_gateway_routes(self) -> None:
        from qantara import VoiceGateway

        gateway = VoiceGateway(host="127.0.0.1", port=0)
        app = gateway.create_app()
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            status_resp = await client.get("/api/status")
            self.assertEqual(status_resp.status, 200)
            body = await status_resp.json()
            self.assertIn("adapter_kind", body)
            self.assertIn("health", body)
            setup_resp = await client.get("/setup/index.html")
            self.assertEqual(setup_resp.status, 200)
        finally:
            await client.close()

    async def test_constructor_arguments_are_stored(self) -> None:
        from qantara import VoiceGateway

        gateway = VoiceGateway(host="0.0.0.0", port=9001)
        self.assertEqual(gateway.host, "0.0.0.0")
        self.assertEqual(gateway.port, 9001)


class MinimalInstallTests(unittest.TestCase):
    def test_provider_packages_do_not_eagerly_import_heavy_deps(self) -> None:
        """A base `pip install qantara` ships no numpy/torch/faster-whisper.
        Importing the gateway must not pull concrete providers at package
        import time — provider selection is lazy in the factory."""
        import subprocess
        import sys

        code = (
            "import sys\n"
            "import providers.tts, providers.stt\n"
            "import gateway.transport_spike.common\n"
            "heavy = [m for m in ('numpy', 'faster_whisper', 'kokoro', 'torch') if m in sys.modules]\n"
            "assert not heavy, f'eagerly imported: {heavy}'\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class SDKDocumentationTests(unittest.TestCase):
    def test_readme_has_tagged_source_and_sdk_examples(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            'pip install "qantara @ git+https://github.com/nawaf1-art/Qantara.git@v0.3.1"',
            readme,
        )
        self.assertIn(
            'pip install "qantara[speech] @ git+https://github.com/nawaf1-art/Qantara.git@v0.3.1"',
            readme,
        )
        self.assertIn("not published to PyPI", readme)
        self.assertIn("from qantara import VoiceGateway", readme)


if __name__ == "__main__":
    unittest.main()
