#!/usr/bin/env python3
"""Fail when public release metadata disagrees about Qantara's version.

``VERSION`` is the single source of truth. Every *current-release* literal —
package metadata, the runtime ``__version__``, the first CHANGELOG heading,
"current version" lines, and the install URLs/filenames in the primary
install documentation — must equal it. Workflows must not hard-code a
release version; they read ``VERSION`` (or the release input) instead.

Historical documents (release notes, benchmark snapshots, ADRs) are not
checked: they intentionally name the release they describe.
"""

from __future__ import annotations

import argparse
import re
import runpy
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"[0-9]+\.[0-9]+\.[0-9]+"

# (file, regex with one version group, label). Each must match exactly once;
# REPEATED_LITERALS are checked at every occurrence.
SINGLE_LITERALS: tuple[tuple[str, str, str], ...] = (
    ("CHANGELOG.md", rf"^## \[({VERSION_PATTERN})\](?:\s+-|$)", "first release heading"),
    ("README.md", rf"^Current source version:\s*`({VERSION_PATTERN})`\s*$", "current source version"),
    ("ROADMAP.md", rf"^Current release line:\s*`({VERSION_PATTERN})`\s*$", "current release line"),
    (
        "docs/README.md",
        rf"^Current source and published release line:\s*`({VERSION_PATTERN})`",
        "current release line",
    ),
    (
        "docs/DOCUMENTATION_GOVERNANCE.md",
        rf"^Current source and published release line:\s*`({VERSION_PATTERN})`",
        "current release line",
    ),
    (
        "docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md",
        rf"^Expected release version:\s*`({VERSION_PATTERN})`",
        "expected release version",
    ),
)
REPEATED_LITERALS: tuple[tuple[str, str, str], ...] = tuple(
    (relative, pattern, label)
    for relative in ("README.md", "docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md", "docs/QUICKSTART.md")
    for pattern, label in (
        (rf"qantara-({VERSION_PATTERN})-py3-none-any\.whl", "wheel filename"),
        (rf"qantara-({VERSION_PATTERN})\.tar\.gz", "sdist filename"),
        (rf"/releases/download/v({VERSION_PATTERN})/", "release download URL"),
        (rf"Qantara\.git@v({VERSION_PATTERN})", "tagged git install"),
    )
)
# Hard-coded release versions in CI would silently go stale on a bump.
WORKFLOW_FORBIDDEN = re.compile(rf"--expected\s+\"?({VERSION_PATTERN})")


def _match(path: Path, pattern: str, label: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise ValueError(f"could not find {label} in {path.relative_to(ROOT)}")
    return match.group(1)


def release_versions() -> dict[str, str]:
    """Return {label: version} for every checked current-release literal."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_version = runpy.run_path(str(ROOT / "qantara" / "version.py"))["__version__"]
    versions = {
        "VERSION": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "pyproject.toml": str(pyproject["project"]["version"]),
        "qantara.__version__": str(runtime_version),
    }
    for relative, pattern, label in SINGLE_LITERALS:
        versions[f"{relative} ({label})"] = _match(ROOT / relative, pattern, label)
    for relative, pattern, label in REPEATED_LITERALS:
        path = ROOT / relative
        if not path.is_file():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in re.finditer(pattern, line):
                versions[f"{relative}:{line_number} ({label})"] = match.group(1)
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            match = WORKFLOW_FORBIDDEN.search(line)
            if match:
                # Reported as a mismatch against any expected value.
                versions[f"{workflow.relative_to(ROOT)}:{line_number} (hard-coded; read VERSION)"] = (
                    f"hard-coded {match.group(1)}"
                )
    return versions


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
