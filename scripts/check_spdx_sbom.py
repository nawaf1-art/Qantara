#!/usr/bin/env python3
"""Validate that a release SPDX document describes the Qantara wheel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _package_purls(package: dict[str, Any]) -> set[str]:
    references = package.get("externalRefs")
    if not isinstance(references, list):
        return set()
    return {
        reference["referenceLocator"]
        for reference in references
        if isinstance(reference, dict)
        and reference.get("referenceType") == "purl"
        and isinstance(reference.get("referenceLocator"), str)
    }


def validate_spdx_document(
    document: object,
    *,
    expected_name: str,
    expected_version: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["document root must be a JSON object"]
    if document.get("spdxVersion") != "SPDX-2.3":
        errors.append("spdxVersion must be SPDX-2.3")
    if document.get("dataLicense") != "CC0-1.0":
        errors.append("dataLicense must be CC0-1.0")

    packages = document.get("packages")
    if not isinstance(packages, list):
        return [*errors, "packages must be a JSON array"]
    package_objects = [package for package in packages if isinstance(package, dict)]
    matching = [
        package
        for package in package_objects
        if str(package.get("name", "")).casefold() == expected_name.casefold()
    ]
    if len(matching) != 1:
        errors.append(f"expected exactly one {expected_name!r} package, found {len(matching)}")
        return errors

    package = matching[0]
    if package.get("versionInfo") != expected_version:
        errors.append(
            f"{expected_name} version must be {expected_version}, got {package.get('versionInfo')!r}"
        )
    expected_purl = f"pkg:pypi/{expected_name.casefold()}@{expected_version}"
    if expected_purl not in _package_purls(package):
        errors.append(f"{expected_name} package is missing purl {expected_purl}")
    if package.get("licenseDeclared") != "Apache-2.0":
        errors.append(f"{expected_name} declared license must be Apache-2.0")
    if package.get("filesAnalyzed") is not True:
        errors.append(f"{expected_name} package files must be analyzed")

    aiohttp_packages = [
        candidate
        for candidate in package_objects
        if str(candidate.get("name", "")).casefold() == "aiohttp"
    ]
    if not aiohttp_packages:
        errors.append("required runtime dependency aiohttp is missing")
    elif not any(
        any(purl.startswith("pkg:pypi/aiohttp@") for purl in _package_purls(candidate))
        for candidate in aiohttp_packages
    ):
        errors.append("aiohttp package is missing a versioned PyPI purl")

    package_id = package.get("SPDXID")
    relationships = document.get("relationships")
    if not isinstance(relationships, list):
        errors.append("relationships must be a JSON array")
    elif not any(
        isinstance(relationship, dict)
        and relationship.get("relatedSpdxElement") == package_id
        and relationship.get("relationshipType") in {"CONTAINS", "DESCRIBES"}
        for relationship in relationships
    ):
        errors.append(f"{expected_name} package is not linked into the SPDX document")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-name", default="qantara")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("sbom", type=Path)
    args = parser.parse_args()

    try:
        document = json.loads(args.sbom.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"SPDX SBOM check failed: {exc}", file=sys.stderr)
        return 1

    errors = validate_spdx_document(
        document,
        expected_name=args.expected_name,
        expected_version=args.expected_version,
    )
    if errors:
        print("SPDX SBOM check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print(
        f"SPDX SBOM describes {args.expected_name} {args.expected_version} "
        f"with {len(document['packages'])} packages"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
