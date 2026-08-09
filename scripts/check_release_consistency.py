#!/usr/bin/env python3
"""Fail when public release metadata disagrees about Qantara's version."""

from __future__ import annotations

import argparse
import re
import runpy
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"[0-9]+\.[0-9]+\.[0-9]+"


def _match(path: Path, pattern: str, label: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise ValueError(f"could not find {label} in {path.relative_to(ROOT)}")
    return match.group(1)


def release_versions() -> dict[str, str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_version = runpy.run_path(str(ROOT / "qantara" / "version.py"))[
        "__version__"
    ]
    return {
        "VERSION": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "pyproject.toml": str(pyproject["project"]["version"]),
        "qantara.__version__": str(runtime_version),
        "CHANGELOG.md": _match(
            ROOT / "CHANGELOG.md",
            rf"^## \[({VERSION_PATTERN})\](?:\s+-|$)",
            "first release heading",
        ),
        "README.md": _match(
            ROOT / "README.md",
            rf"^Current source version:\s*`({VERSION_PATTERN})`\s*$",
            "current source version",
        ),
        "ROADMAP.md": _match(
            ROOT / "ROADMAP.md",
            rf"^Current release line:\s*`({VERSION_PATTERN})`\s*$",
            "current release line",
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", help="Require this exact semantic version")
    args = parser.parse_args()

    try:
        versions = release_versions()
    except (KeyError, OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"release consistency check failed: {exc}", file=sys.stderr)
        return 1

    expected = args.expected or versions["VERSION"]
    mismatches = {name: value for name, value in versions.items() if value != expected}
    if mismatches:
        print(f"release consistency check failed; expected {expected}", file=sys.stderr)
        for name, value in sorted(mismatches.items()):
            print(f"  {name}: {value}", file=sys.stderr)
        return 1

    print(f"release metadata is consistent at {expected} ({len(versions)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
