#!/usr/bin/env python3
"""Check that local Markdown link targets exist in the source tree."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _markdown_files() -> list[Path]:
    roots = [
        ROOT / "README.md",
        ROOT / "ARCHITECTURE.md",
        ROOT / "CHANGELOG.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "GOVERNANCE.md",
        ROOT / "ROADMAP.md",
        ROOT / "SECURITY.md",
        ROOT / "SUPPORT.md",
    ]
    return [path for path in roots if path.is_file()] + sorted((ROOT / "docs").rglob("*.md"))


def main() -> int:
    errors: list[str] = []
    checked = 0
    for document in _markdown_files():
        text = document.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in LINK_PATTERN.finditer(line):
                raw_target = match.group(1).strip().strip("<>")
                if not raw_target or raw_target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                target_text = unquote(raw_target.split("#", 1)[0])
                if not target_text:
                    continue
                checked += 1
                target = (document.parent / target_text).resolve()
                try:
                    target.relative_to(ROOT)
                except ValueError:
                    errors.append(
                        f"{document.relative_to(ROOT)}:{line_number}: link leaves repository: {raw_target}"
                    )
                    continue
                if not target.exists():
                    errors.append(
                        f"{document.relative_to(ROOT)}:{line_number}: missing target: {raw_target}"
                    )
    if errors:
        print("documentation link check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print(f"documentation links resolve ({checked} local targets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
