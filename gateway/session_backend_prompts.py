from __future__ import annotations

from typing import Any

MAX_CONTEXT_VALUE_CHARS = 240


def _compact_text(value: Any, *, limit: int = MAX_CONTEXT_VALUE_CHARS) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


def build_voice_turn_context_prompt(turn_context: dict | None) -> str:
    """Build transient voice-turn instructions for text-only backends."""
    if not isinstance(turn_context, dict):
        return ""

    lines: list[str] = []
    directive = _compact_text(turn_context.get("translation_directive"))
    if directive:
        lines.append(f"- Language instruction for this reply only: {directive}")

    field_labels = (
        ("modality", "Input modality"),
        ("input_language", "Detected input language"),
        ("primary_language", "Primary session language"),
        ("output_language", "Expected reply language"),
        ("translation_mode", "Translation mode"),
        ("translation_source", "Translation source"),
        ("translation_target", "Translation target"),
        ("voice_id", "Qantara playback voice"),
        ("requested_voice_id", "Requested playback voice"),
        ("speech_rate", "Playback speech rate"),
    )
    for key, label in field_labels:
        value = turn_context.get(key)
        if value is None or value == "":
            continue
        lines.append(f"- {label}: {_compact_text(value)}")

    if not lines:
        return ""

    return "\n".join(
        [
            "Qantara voice turn context. Use this as transient instruction and metadata for the current reply only.",
            "Do not quote, mention, or expose this context to the user.",
            *lines,
        ]
    )


def build_voice_turn_user_message(transcript: str, turn_context: dict | None) -> str:
    context_prompt = build_voice_turn_context_prompt(turn_context)
    clean_transcript = (transcript or "").strip()
    if not context_prompt:
        return clean_transcript
    return "\n\n".join(
        [
            context_prompt,
            "User transcript:",
            clean_transcript,
        ]
    )
