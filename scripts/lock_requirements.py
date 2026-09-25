#!/usr/bin/env python3
"""Regenerate Qantara's hash-locked speech/runtime requirement files.

Run from the repository root with uv installed:

    python scripts/lock_requirements.py            # keep existing pins
    python scripts/lock_requirements.py --upgrade  # re-resolve to latest allowed

Only the PyTorch ecosystem (torch and its CPU build) is resolved from the
PyTorch CPU index, via ``uv pip compile --torch-backend cpu``. Every other
package is resolved from PyPI, so uv records the hash of every published file
(cp311/cp312 x Linux x86_64/aarch64, Windows, macOS) instead of only the files
it happened to download from a mirror.

pip still needs to locate the ``+cpu`` torch build when it installs the lock,
so the generated file gains an ``--extra-index-url`` line for the PyTorch CPU
index. That is safe because every requirement carries ``--hash`` pins:
``pip install --require-hashes`` rejects any file whose digest is not locked,
whichever index serves it.

After regenerating, verify platform coverage with:

    python scripts/check_lock_hashes.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
PYPI_INDEX = "https://pypi.org/simple"
LOCKS = (
    (ROOT / "ops" / "docker" / "requirements.in", ROOT / "ops" / "docker" / "requirements.txt"),
    (
        ROOT / "gateway" / "transport_spike" / "requirements.in",
        ROOT / "gateway" / "transport_spike" / "requirements.txt",
    ),
)
PIN_LINE = re.compile(r"^([A-Za-z0-9_.\-]+==[^\s;\\]+)")
COMPILE_COMMAND = "python scripts/lock_requirements.py"


def _seed_preferences(lock: Path, seed: Path) -> None:
    """Write version-only pins so uv keeps current versions but refetches hashes."""
    pins: list[str] = []
    if lock.is_file():
        for line in lock.read_text(encoding="utf-8").splitlines():
            match = PIN_LINE.match(line)
            if match:
                pins.append(match.group(1))
    seed.write_text("\n".join(pins) + ("\n" if pins else ""), encoding="utf-8")


def _add_pytorch_index(lock: Path) -> None:
    lines = lock.read_text(encoding="utf-8").splitlines()
    if any(line.startswith("--extra-index-url") for line in lines):
        return
    for index, line in enumerate(lines):
        if line.startswith("--index-url"):
            lines.insert(index + 1, f"--extra-index-url {PYTORCH_CPU_INDEX}")
            break
    else:
        raise RuntimeError(f"{lock}: uv did not emit an --index-url line")
    lock.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compile_lock(source: Path, lock: Path, *, upgrade: bool) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required: https://docs.astral.sh/uv/")
    with tempfile.TemporaryDirectory(prefix="qantara-lock-") as temp_dir:
        output = Path(temp_dir) / "requirements.txt"
        if not upgrade:
            # uv treats an existing output file as version preferences. A
            # hash-free copy keeps the pins without reusing partial hash sets.
            _seed_preferences(lock, output)
        command = [
            uv,
            "pip",
            "compile",
            "--quiet",
            "--universal",
            "--generate-hashes",
            "--python-version",
            "3.11",
            "--torch-backend",
            "cpu",
            "--index-url",
            PYPI_INDEX,
            "--emit-index-url",
            "--no-cache",
            "--custom-compile-command",
            COMPILE_COMMAND,
            "--output-file",
            str(output),
            str(source.relative_to(ROOT)),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        _add_pytorch_index(output)
        text = output.read_text(encoding="utf-8").replace("\r\n", "\n")
        lock.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--upgrade", action="store_true", help="ignore existing pins and re-resolve")
    args = parser.parse_args()
    try:
        for source, lock in LOCKS:
            compile_lock(source, lock, upgrade=args.upgrade)
            print(f"locked {lock.relative_to(ROOT)}")
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"lock generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
