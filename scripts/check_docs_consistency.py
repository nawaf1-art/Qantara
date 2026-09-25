#!/usr/bin/env python3
"""Check semantic invariants that keep Qantara documentation authoritative."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HISTORICAL_SNAPSHOTS = (
    "FIRST_PUBLIC_RELEASE_NOTES_DRAFT.md",
    "PUBLISHING_READINESS_AUDIT.md",
    "REPOSITORY_CLEANUP_REPORT.md",
    "SECURITY_PUBLICATION_AUDIT.md",
    "SESSION_HANDOFF.md",
)
HISTORICAL_MARKER = "**Historical snapshot — not current product guidance.**"
PRECEDENCE = (
    "environment variables > explicit CLI flags > selected YAML file > "
    "built-in defaults"
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _index_targets(index_text: str) -> set[Path]:
    targets: set[Path] = set()
    for match in LINK_PATTERN.finditer(index_text):
        raw = match.group(1).strip().strip("<>")
        if not raw or raw.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target_text = unquote(raw.split("#", 1)[0])
        if target_text:
            targets.add((DOCS / target_text).resolve())
    return targets


def main() -> int:
    errors: list[str] = []
    checks = 0

    version = _read("VERSION").strip()
    index_text = _read("docs/README.md")
    index_targets = _index_targets(index_text)

    for document in sorted(DOCS.glob("*.md")):
        if document.name == "README.md":
            continue
        checks += 1
        if document.resolve() not in index_targets:
            errors.append(f"docs/README.md does not classify/link {document.name}")

    for name in HISTORICAL_SNAPSHOTS:
        checks += 1
        text = _read(f"docs/{name}")
        if HISTORICAL_MARKER not in "\n".join(text.splitlines()[:8]):
            errors.append(f"docs/{name} lacks the historical snapshot marker")

    for relative in ("docs/CONFIGURATION.md", "docs/CLI.md"):
        checks += 1
        if PRECEDENCE not in _read(relative):
            errors.append(f"{relative} does not state the implemented startup precedence")

    pyproject = tomllib.loads(_read("pyproject.toml"))
    sdist_include = set(pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"])
    checks += 2
    if "FEATURES.md" in sdist_include:
        errors.append("pyproject.toml still references nonexistent root FEATURES.md")
    if not ({"docs", "docs/FEATURES.md"} & sdist_include):
        errors.append("source distribution does not include docs/FEATURES.md")

    release_notes = DOCS / f"RELEASE_NOTES_{version}.md"
    checks += 1
    if not release_notes.is_file():
        errors.append(f"missing release notes for current version: {release_notes.name}")

    required_fragments = {
        "README.md": (
            "docs/DOCUMENTATION_GOVERNANCE.md",
            "docs/CLI.md",
            "docs/PYTHON_SDK.md",
            f"qantara-{version}-py3-none-any.whl",
        ),
        "docs/README.md": (
            f"Current source and published release line: `{version}`",
            "DOCUMENTATION_GOVERNANCE.md",
            "CLI.md",
            "PYTHON_SDK.md",
        ),
        "adapters/README.md": ("mcp_client.py", "QANTARA_ADAPTER=mcp"),
        "adapters/CONTRACT.md": ("adapters/base.py", "protocols/agent.md"),
        "gateway/SESSION_MODEL.md": (
            "idle",
            "listening",
            "thinking",
            "speaking",
            "interrupted",
        ),
        "providers/README.md": (
            "Default STT: `faster_whisper`",
            "Default TTS: `piper`",
        ),
    }
    for relative, fragments in required_fragments.items():
        text = _read(relative)
        for fragment in fragments:
            checks += 1
            if fragment not in text:
                errors.append(f"{relative} is missing required current guidance: {fragment}")

    forbidden_fragments = {
        "README.md": ("after the release is published",),
        "gateway/README.md": ("Initial responsibilities", "at this stage"),
        "gateway/transport_spike/README.md": (
            "fallback placeholder transcript",
            "synthetic tone path",
        ),
        "ops/README.md": ("current M0 spike", "runtime path still remains mock-based"),
    }
    for relative, fragments in forbidden_fragments.items():
        text = _read(relative)
        for fragment in fragments:
            checks += 1
            if fragment in text:
                errors.append(f"{relative} contains stale guidance: {fragment}")

    if errors:
        print("documentation consistency check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"documentation semantics are consistent ({checks} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
