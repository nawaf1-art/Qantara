from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VoiceRegistryEntry:
    voice_id: str
    label: str
    engine: str
    locale: str
    sample_rate: int
    model_path: str | None = None
    config_path: str | None = None
    defaults: dict[str, Any] | None = None
    allowed_transforms: list[str] | None = None
    preview_text: str | None = None
    preview_audio_path: str | None = None
    license: str | None = None
    commercial_notes: str | None = None

    def as_catalog_entry(self) -> dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "label": self.label,
            "locale": self.locale,
            "sample_rate": self.sample_rate,
            "defaults": dict(self.defaults or {}),
            "allowed_transforms": list(self.allowed_transforms or []),
        }


class VoiceRegistryError(ValueError):
    """The voice registry file is structurally invalid."""


# Mirrors identity/voice-registry.schema.json. Validated by hand because
# jsonschema is a test-only dependency.
_ALLOWED_ENGINES = frozenset({"piper", "kokoro", "chatterbox", "coqui", "melo", "custom"})
_ALLOWED_TRANSFORMS = frozenset({"rate", "pitch", "tone", "formant", "expressiveness"})
_ENTRY_KEYS = frozenset({
    "voice_id", "label", "engine", "locale", "model_path", "config_path",
    "preview_text", "preview_audio_path", "base_sample_rate", "defaults",
    "allowed_transforms", "license", "commercial_notes",
})
_DEFAULT_KEYS = frozenset({"rate", "pitch", "tone", "expressiveness"})
_DEFAULT_RANGES = {"rate": (0.5, 2.0), "pitch": (-24.0, 24.0), "expressiveness": (0.0, 1.0)}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _validate_registry_top_level(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["registry must be a JSON object"]
    errors: list[str] = []
    if str(payload.get("schema_version", "")) != "1.0":
        errors.append("schema_version must be '1.0'")
    if not isinstance(payload.get("voices"), list):
        errors.append("'voices' must be a list")
    return errors


def validate_voice_entry(raw: Any) -> list[str]:
    """Return schema violations for one registry entry (empty when valid)."""
    if not isinstance(raw, dict):
        return ["entry must be an object"]
    errors: list[str] = []
    unknown = sorted(set(raw) - _ENTRY_KEYS)
    if unknown:
        errors.append(f"unknown fields {unknown}")
    for key in ("voice_id", "label"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            errors.append(f"'{key}' must be a non-empty string")
    if raw.get("engine") not in _ALLOWED_ENGINES:
        errors.append(f"'engine' must be one of {sorted(_ALLOWED_ENGINES)}")
    locale = raw.get("locale")
    if not isinstance(locale, str) or len(locale.strip()) < 2:
        errors.append("'locale' must be a string of at least 2 characters")
    if "model_path" not in raw:
        errors.append("'model_path' is required (may be null)")
    elif raw["model_path"] is not None and (not isinstance(raw["model_path"], str) or not raw["model_path"]):
        errors.append("'model_path' must be a non-empty string or null")
    for key in ("config_path",):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            errors.append(f"'{key}' must be a string or null")
    for key in ("preview_text", "preview_audio_path", "license", "commercial_notes"):
        if key in raw and not isinstance(raw[key], str):
            errors.append(f"'{key}' must be a string")
    rate = raw.get("base_sample_rate")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 8000:
        errors.append("'base_sample_rate' must be an integer >= 8000")
    defaults = raw.get("defaults")
    if not isinstance(defaults, dict):
        errors.append("'defaults' must be an object")
    else:
        unknown_defaults = sorted(set(defaults) - _DEFAULT_KEYS)
        if unknown_defaults:
            errors.append(f"unknown defaults {unknown_defaults}")
        for key in ("rate", "pitch", "tone"):
            if key not in defaults:
                errors.append(f"defaults.{key} is required")
        for key, (low, high) in _DEFAULT_RANGES.items():
            if key in defaults and (not _is_number(defaults[key]) or not low <= defaults[key] <= high):
                errors.append(f"defaults.{key} must be a number in [{low}, {high}]")
        if "tone" in defaults and (not isinstance(defaults["tone"], str) or not defaults["tone"]):
            errors.append("defaults.tone must be a non-empty string")
    transforms = raw.get("allowed_transforms")
    if transforms is not None and (
        not isinstance(transforms, list) or any(t not in _ALLOWED_TRANSFORMS for t in transforms)
    ):
        errors.append(f"'allowed_transforms' items must be in {sorted(_ALLOWED_TRANSFORMS)}")
    return errors


def validate_voice_registry(payload: Any) -> list[str]:
    """Return all schema violations for a registry payload."""
    errors = _validate_registry_top_level(payload)
    if errors:
        return errors
    if not payload["voices"]:
        errors.append("'voices' must contain at least one entry")
    for index, raw in enumerate(payload["voices"]):
        errors.extend(f"voices[{index}]: {message}" for message in validate_voice_entry(raw))
    return errors


def default_registry_path() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(repo_root, "identity", "voice-registry", "voices.json")


def _resolve_path(path: str | None, registry_path: str) -> str | None:
    if not path:
        return None
    if os.path.isabs(path):
        return path
    registry_dir = os.path.dirname(os.path.abspath(registry_path))
    repo_root = os.path.abspath(os.path.join(registry_dir, "..", ".."))
    return os.path.join(repo_root, path)


def load_voice_registry(registry_path: str | None = None) -> list[VoiceRegistryEntry]:
    path = registry_path or os.environ.get("QANTARA_VOICE_REGISTRY") or default_registry_path()
    if not os.path.exists(path):
        return []

    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict) or not isinstance(payload.get("voices"), list):
        raise VoiceRegistryError(
            f"invalid voice registry {path}: expected an object with a 'voices' list"
        )
    for message in _validate_registry_top_level(payload):
        _LOG.warning("voice registry %s: %s", path, message)

    entries: list[VoiceRegistryEntry] = []
    for index, raw in enumerate(payload.get("voices", [])):
        entry_errors = validate_voice_entry(raw)
        if entry_errors:
            name = raw.get("voice_id") if isinstance(raw, dict) else None
            _LOG.warning(
                "skipping invalid voice registry entry %s (%s) in %s: %s",
                index, name or "?", path, "; ".join(entry_errors),
            )
            continue
        voice_id = str(raw.get("voice_id") or "").strip()
        label = str(raw.get("label") or "").strip()
        engine = str(raw.get("engine") or "").strip().lower()
        locale = str(raw.get("locale") or "").strip()
        if not voice_id or not label or not engine or not locale:
            continue
        entries.append(
            VoiceRegistryEntry(
                voice_id=voice_id,
                label=label,
                engine=engine,
                locale=locale,
                sample_rate=int(raw.get("base_sample_rate") or 0),
                model_path=_resolve_path(raw.get("model_path"), path),
                config_path=_resolve_path(raw.get("config_path"), path),
                defaults=dict(raw.get("defaults") or {}),
                allowed_transforms=list(raw.get("allowed_transforms") or []),
                preview_text=raw.get("preview_text"),
                preview_audio_path=_resolve_path(raw.get("preview_audio_path"), path),
                license=raw.get("license"),
                commercial_notes=raw.get("commercial_notes"),
            )
        )
    return entries


def filter_registry_voices(
    engine: str,
    registry_path: str | None = None,
) -> list[VoiceRegistryEntry]:
    expected = engine.strip().lower()
    return [
        entry
        for entry in load_voice_registry(registry_path)
        if entry.engine == expected
    ]
