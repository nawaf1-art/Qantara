#!/usr/bin/env python3
"""Install one artifact into a clean venv and exercise its public surface."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path

SMOKE_CODE = r"""
import os
from pathlib import Path

os.environ.update({
    "QANTARA_ADAPTER": "mock",
    "QANTARA_STT_PROVIDER": "faster_whisper",
    "QANTARA_TTS_PROVIDER": "piper",
})

import qantara
from qantara import VoiceGateway, __version__

assert __version__ == os.environ["QANTARA_EXPECTED_VERSION"]
root = Path(qantara.__file__).resolve().parent.parent
for resource in (
    root / "client" / "transport-spike" / "index.html",
    root / "identity" / "avatar-descriptor.schema.json",
    root / "protocols" / "agent.md",
):
    assert resource.is_file(), resource
app = VoiceGateway().create_app()
routes = {route.resource.canonical for route in app.router.routes()}
assert "/ws" in routes
assert "/api/status" in routes
assert "/api/v1/speak" in routes
print(f"qantara {__version__} artifact smoke passed with {len(routes)} routes")
"""


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expected", required=True)
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    if not artifact.is_file():
        parser.error(f"artifact not found: {artifact}")

    with tempfile.TemporaryDirectory(prefix="qantara-smoke-") as temp_dir:
        environment = Path(temp_dir) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = _venv_python(environment)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--quiet",
                str(artifact),
            ],
            check=True,
        )
        env = os.environ.copy()
        env["QANTARA_EXPECTED_VERSION"] = args.expected
        subprocess.run([str(python), "-I", "-c", SMOKE_CODE], check=True, env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
