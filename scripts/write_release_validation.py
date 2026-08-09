#!/usr/bin/env python3
"""Write machine-readable evidence after release workflow checks pass."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()

    evidence = {
        "schema_version": 1,
        "project": "Qantara",
        "version": args.version,
        "tag": f"v{args.version}",
        "commit": args.commit,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "status": "passed",
        "validations": [
            "release_metadata_consistency",
            "workflow_pin_check",
            "documentation_link_check",
            "tracked_artifact_check",
            "unit_tests",
            "ruff",
            "compileall",
            "twine_check",
            "artifact_content_check",
            "clean_wheel_install",
            "clean_sdist_install",
            "dependency_audit",
            "sbom_generated",
        ],
        "artifacts": [
            {
                "name": artifact.name,
                "sha256": _digest(artifact),
                "size_bytes": artifact.stat().st_size,
            }
            for artifact in sorted(args.artifacts)
        ],
    }
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"wrote release validation evidence to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
