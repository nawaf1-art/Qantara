"""Audit 2026-09-24 Q-06b: pinned, hashed Piper voices incl. English."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "fetch_piper_voices.sh"
ENTRY_RE = re.compile(r'^\s*"(?P<path>[^" ]+) (?P<sha>[0-9a-f]{64})"\s*$', re.MULTILINE)


class FetchScriptStaticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.entries = {Path(m["path"]).name: m["sha"] for m in ENTRY_RE.finditer(self.text)}

    def test_revision_is_pinned_commit(self) -> None:
        match = re.search(r'^REVISION="([0-9a-f]{40})"$', self.text, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertNotIn("resolve/main", self.text)

    def test_english_voice_included(self) -> None:
        self.assertIn("en_US-lessac-medium.onnx", self.entries)
        self.assertIn("en_US-lessac-medium.onnx.json", self.entries)

    def test_every_registry_piper_voice_with_download_is_hashed(self) -> None:
        registry = json.loads((REPO_ROOT / "identity" / "voice-registry" / "voices.json").read_text(encoding="utf-8"))
        wanted = {"lessac", "ar_JO-kareem-medium", "es_ES-davefx-medium", "fr_FR-siwis-medium"}
        for voice in registry["voices"]:
            if voice["voice_id"] in wanted:
                self.assertIn(Path(voice["model_path"]).name, self.entries, voice["voice_id"])
                self.assertIn(Path(voice["config_path"]).name, self.entries, voice["voice_id"])
        self.assertEqual(len(self.entries), 8)


@unittest.skipIf(sys.platform == "win32" or shutil.which("bash") is None, "needs POSIX bash")
class FetchScriptChecksumTests(unittest.TestCase):
    def test_checksum_mismatch_fails_and_removes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_curl = bin_dir / "curl"
            # Fake curl: write placeholder bytes to the -o target, no network.
            fake_curl.write_text(
                "#!/usr/bin/env bash\n"
                "out=''\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = '-o' ]; then out=\"$2\"; shift; fi\n"
                "  shift\n"
                "done\n"
                "printf 'not a model' > \"$out\"\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
            result = subprocess.run(
                ["bash", str(SCRIPT)], cwd=root, env=env, capture_output=True, text=True, timeout=60
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum mismatch", result.stderr)
            leftovers = list((root / "models" / "piper").iterdir())
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
