from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


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

    entries: list[VoiceRegistryEntry] = []
    for raw in payload.get("voices", []):
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
