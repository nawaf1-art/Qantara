#!/usr/bin/env python3
"""Require immutable full-SHA references for external GitHub Actions."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USES_PATTERN = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def main() -> int:
    errors: list[str] = []
    checked = 0
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = USES_PATTERN.match(line)
            if match is None:
                continue
            target = match.group(1)
            if target.startswith("./") or target.startswith("docker://"):
                continue
            checked += 1
            if "@" not in target:
                errors.append(f"{workflow.name}:{line_number}: action has no ref")
                continue
            action, ref = target.rsplit("@", 1)
            if not action or SHA_PATTERN.fullmatch(ref) is None:
                errors.append(
                    f"{workflow.name}:{line_number}: external action ref is not a full commit SHA"
                )
    if errors:
        print("workflow pin check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print(f"workflow action pins are immutable ({checked} references)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
