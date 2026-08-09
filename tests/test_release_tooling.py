from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReleaseToolingTests(unittest.TestCase):
    def test_release_versions_are_consistent(self) -> None:
        module = _load_script("check_release_consistency.py")
        versions = module.release_versions()
        self.assertEqual(set(versions.values()), {"0.3.1"})

    def test_external_workflow_actions_are_sha_pinned(self) -> None:
        module = _load_script("check_workflow_pins.py")
        self.assertEqual(module.main(), 0)

    def test_tracked_artifacts_exclude_private_runtime_files(self) -> None:
        module = _load_script("check_tracked_artifacts.py")
        self.assertEqual(module.main(), 0)

    def test_package_artifact_checker_rejects_audio_and_model_weights(self) -> None:
        module = _load_script("check_package_artifacts.py")
        for path in (
            "recordings/private.wav",
            "models/voice.pth",
            "captures/sample.flac",
        ):
            with self.subTest(path=path):
                self.assertTrue(module._has_forbidden_path(path))

    def test_checksum_manifest_requires_downloadable_basenames(self) -> None:
        module = _load_script("check_checksum_manifest.py")
        with tempfile.TemporaryDirectory(prefix="qantara-checksum-test-") as temp_dir:
            temp = Path(temp_dir)
            artifact = temp / "qantara-0.3.1.whl"
            artifact.write_bytes(b"wheel")
            digest = hashlib.sha256(b"wheel").hexdigest()
            manifest = temp / "SHA256SUMS"
            manifest.write_text(f"{digest}  qantara-0.3.1.whl\n", encoding="utf-8")
            self.assertEqual(module.check_manifest(manifest, [artifact]), [])

            manifest.write_text(f"{digest}  dist/qantara-0.3.1.whl\n", encoding="utf-8")
            errors = module.check_manifest(manifest, [artifact])
            self.assertTrue(any("basename" in error for error in errors))

    def test_spdx_checker_requires_qantara_component_and_runtime_dependency(self) -> None:
        module = _load_script("check_spdx_sbom.py")
        document = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "packages": [
                {
                    "name": "qantara",
                    "SPDXID": "SPDXRef-Package-qantara",
                    "versionInfo": "0.3.1",
                    "licenseDeclared": "Apache-2.0",
                    "filesAnalyzed": True,
                    "externalRefs": [
                        {
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/qantara@0.3.1",
                        }
                    ],
                },
                {
                    "name": "aiohttp",
                    "SPDXID": "SPDXRef-Package-aiohttp",
                    "externalRefs": [
                        {
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/aiohttp@3.14.3",
                        }
                    ],
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DocumentRoot",
                    "relatedSpdxElement": "SPDXRef-Package-qantara",
                    "relationshipType": "CONTAINS",
                }
            ],
        }
        self.assertEqual(
            module.validate_spdx_document(
                document,
                expected_name="qantara",
                expected_version="0.3.1",
            ),
            [],
        )

        document["packages"] = [document["packages"][1]]
        errors = module.validate_spdx_document(
            document,
            expected_name="qantara",
            expected_version="0.3.1",
        )
        self.assertTrue(any("exactly one" in error for error in errors))

    def test_generated_release_evidence_matches_public_schema(self) -> None:
        schema = json.loads(
            (ROOT / "docs" / "releases" / "release-validation.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        module = _load_script("write_release_validation.py")
        with tempfile.TemporaryDirectory(prefix="qantara-release-test-") as temp_dir:
            temp = Path(temp_dir)
            wheel = temp / "qantara-0.3.1-py3-none-any.whl"
            sdist = temp / "qantara-0.3.1.tar.gz"
            output = temp / "release-validation.json"
            wheel.write_bytes(b"wheel")
            sdist.write_bytes(b"sdist")
            argv = [
                "write_release_validation.py",
                "--version",
                "0.3.1",
                "--commit",
                "a" * 40,
                "--output",
                str(output),
                str(wheel),
                str(sdist),
            ]
            with patch("sys.argv", argv):
                self.assertEqual(module.main(), 0)
            evidence = json.loads(output.read_text(encoding="utf-8"))

        Draft202012Validator(schema).validate(evidence)


if __name__ == "__main__":
    unittest.main()
