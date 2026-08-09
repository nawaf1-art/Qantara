#!/usr/bin/env python3
"""Reject tracked local artifacts that must never enter a public release."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKED_FILE_BYTES = 20 * 1024 * 1024
FORBIDDEN_PARTS = frozenset(
    {
        ".env",
        ".venv",
        "__pycache__",
        "certs",
        "logs",
        "models",
        "recordings",
        "venv",
    }
)
FORBIDDEN_NAMES = frozenset(
    {
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "service-account.json",
    }
)
FORBIDDEN_SUFFIXES = (
    ".cer",
    ".ckpt",
    ".crt",
    ".der",
    ".flac",
    ".gguf",
    ".key",
    ".log",
    ".mp3",
    ".onnx",
    ".p12",
    ".pem",
    ".pfx",
    ".pt",
    ".pth",
    ".pyc",
    ".safetensors",
    ".wav",
)
ALLOWED_PATHS = frozenset({".env.example"})


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def check_path(relative: str) -> list[str]:
    normalized = relative.replace("\\", "/")
    if normalized in ALLOWED_PATHS:
        return []
    path = PurePosixPath(normalized)
    lowered_parts = tuple(part.lower() for part in path.parts)
    errors: list[str] = []
    if path.name.lower().startswith(".env"):
        errors.append("forbidden environment file")
    if any(part in FORBIDDEN_PARTS for part in lowered_parts):
        errors.append("forbidden local-artifact directory")
    if path.name.lower() in FORBIDDEN_NAMES:
        errors.append("forbidden credential filename")
    if path.name.lower().endswith(FORBIDDEN_SUFFIXES):
        errors.append("forbidden private/model/audio/log suffix")

    disk_path = ROOT / Path(*path.parts)
    try:
        size = disk_path.stat().st_size
    except OSError as exc:
        errors.append(f"could not inspect tracked path ({type(exc).__name__})")
    else:
        if size > MAX_TRACKED_FILE_BYTES:
            errors.append(f"tracked file exceeds {MAX_TRACKED_FILE_BYTES} bytes")
    return errors


def main() -> int:
    try:
        paths = tracked_paths()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"tracked-artifact check failed to enumerate files ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 1

    failures = [
        f"{path}: {error}"
        for path in paths
        for error in check_path(path)
    ]
    if failures:
        print("tracked-artifact check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(f"tracked-artifact paths are clean ({len(paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
