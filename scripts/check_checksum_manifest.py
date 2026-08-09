#!/usr/bin/env python3
"""Validate a release checksum manifest against downloaded-style basenames."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([^/\\]+)$")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_manifest(manifest: Path, artifacts: list[Path]) -> list[str]:
    errors: list[str] = []
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return [f"could not read {manifest}: {exc}"]

    entries: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None:
            errors.append(f"line {line_number} must contain a SHA-256 and a basename")
            continue
        digest, name = match.groups()
        if name in entries:
            errors.append(f"duplicate checksum entry: {name}")
            continue
        entries[name] = digest

    expected = {artifact.name: artifact for artifact in artifacts}
    if len(expected) != len(artifacts):
        errors.append("artifact basenames must be unique")
    for name in sorted(expected.keys() - entries.keys()):
        errors.append(f"missing checksum entry: {name}")
    for name in sorted(entries.keys() - expected.keys()):
        errors.append(f"unexpected checksum entry: {name}")
    for name in sorted(expected.keys() & entries.keys()):
        try:
            actual = _digest(expected[name])
        except OSError as exc:
            errors.append(f"could not hash {name}: {exc}")
            continue
        if actual != entries[name]:
            errors.append(f"checksum mismatch: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()

    errors = check_manifest(args.manifest, args.artifacts)
    if errors:
        print("checksum manifest check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print(f"checksum manifest matches {len(args.artifacts)} release assets by basename")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
