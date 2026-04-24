from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


class VoiceRegistrySchemaTests(unittest.TestCase):
    def test_voice_registry_matches_schema(self) -> None:
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "identity" / "voice-registry.schema.json").read_text(encoding="utf-8"))
        registry = json.loads((root / "identity" / "voice-registry" / "voices.json").read_text(encoding="utf-8"))

        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(registry), key=lambda error: list(error.path))
        self.assertEqual(errors, [], [error.message for error in errors])


if __name__ == "__main__":
    unittest.main()
