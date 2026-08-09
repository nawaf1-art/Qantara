#!/usr/bin/env python3
"""Inspect built wheel/sdist members without extracting or executing them."""

from __future__ import annotations

import argparse
import stat
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_CONTENT_BYTES = 32 * 1024 * 1024
FORBIDDEN_PARTS = frozenset(
    {
        ".env",
        ".git",
        ".github",
        ".venv",
        "__pycache__",
        "certs",
        "models",
        "session_handoff.md",
        "venv",
    }
)
FORBIDDEN_PATHS = (
    ("docs", "audits"),
    ("docs", "internal"),
    ("ops", "certs"),
)
FORBIDDEN_SUFFIXES = (
    ".cer",
    ".ckpt",
    ".crt",
    ".der",
    ".egg-info",
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
    ".pyo",
    ".safetensors",
    ".wav",
)


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    size: int
    is_link: bool = False


def _members(path: Path) -> list[ArchiveMember]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return [
                ArchiveMember(
                    item.filename,
                    item.file_size,
                    stat.S_ISLNK(item.external_attr >> 16),
                )
                for item in archive.infolist()
            ]
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, mode="r:gz") as archive:
            return [
                ArchiveMember(item.name, item.size, item.issym() or item.islnk())
                for item in archive.getmembers()
                if item.isfile() or item.issym() or item.islnk()
            ]
    raise ValueError("artifact must be a .whl or .tar.gz file")


def _relative_parts(name: str) -> tuple[str, ...]:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if parts and parts[0].startswith("qantara-") and not parts[0].endswith(".dist-info"):
        parts = parts[1:]
    return tuple(part.lower() for part in parts)


def _has_forbidden_path(name: str) -> bool:
    parts = _relative_parts(name)
    if any(part.startswith(".env") for part in parts):
        return True
    if any(part in FORBIDDEN_PARTS for part in parts):
        return True
    for forbidden in FORBIDDEN_PATHS:
        width = len(forbidden)
        if any(parts[index : index + width] == forbidden for index in range(len(parts) - width + 1)):
            return True
    return any(part.endswith(FORBIDDEN_SUFFIXES) for part in parts)


def _has_unsafe_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return path.is_absolute() or ".." in path.parts


def _required_members(path: Path) -> tuple[str, ...]:
    common = (
        "qantara/__init__.py",
        "adapters/base.py",
        "gateway/transport_spike/server.py",
        "providers/stt/base.py",
        "discovery/scanner.py",
        "client/transport-spike/index.html",
        "identity/avatar-descriptor.schema.json",
        "protocols/agent.md",
    )
    if path.suffix == ".whl":
        return common
    return (*common, "pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md")


def check_artifact(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        members = _members(path)
    except (OSError, tarfile.TarError, ValueError, zipfile.BadZipFile) as exc:
        return [f"could not inspect {path.name}: {exc}"]

    normalized = {"/".join(_relative_parts(item.name)) for item in members}
    total_size = sum(item.size for item in members)
    if total_size > MAX_ARCHIVE_CONTENT_BYTES:
        errors.append(f"expanded content is too large: {total_size} bytes")
    for member in members:
        if _has_unsafe_path(member.name):
            errors.append(f"unsafe archive member path: {member.name}")
        if member.is_link:
            errors.append(f"archive link is not allowed: {member.name}")
        if member.size > MAX_MEMBER_BYTES:
            errors.append(f"archive member is too large: {member.name} ({member.size} bytes)")
        if _has_forbidden_path(member.name):
            errors.append(f"forbidden archive member: {member.name}")
    for required in _required_members(path):
        if required.lower() not in normalized:
            errors.append(f"required archive member missing: {required}")

    print(f"inspected {path.name}: {len(members)} files, {total_size} expanded bytes")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()

    errors: list[str] = []
    for artifact in args.artifacts:
        errors.extend(f"{artifact.name}: {error}" for error in check_artifact(artifact))
    if errors:
        print("package artifact check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print("package artifacts passed structural and exclusion checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
