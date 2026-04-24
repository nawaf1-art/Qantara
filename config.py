"""Qantara config file loader.

Loads configuration from a qantara.yml file in the repo root, or from
a path specified by the QANTARA_CONFIG environment variable.

Supported config shape:

    backend:
      type: ollama
      url: http://localhost:11434
      model: qwen2.5:7b
      agent: main

    voice:
      stt: faster_whisper
      tts: kokoro

    server:
      host: 0.0.0.0
      port: 8765

Precedence (highest wins): env vars > CLI flags > config file > defaults.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Minimal YAML parser — handles only the two-level key:value subset above.
# No extra dependencies required.
# ---------------------------------------------------------------------------

def _parse_simple_yaml(text: str) -> dict[str, dict[str, str]]:
    """Parse a two-level YAML file with only scalar values.

    Returns a dict of dicts, e.g. {"backend": {"type": "ollama", ...}}.
    Lines that are blank or start with '#' are skipped.
    Top-level keys end with ':' and have no value on the same line.
    Nested keys are indented with spaces and have a scalar value.
    """
    result: dict[str, dict[str, str]] = {}
    current_section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        # Skip blanks and comments
        if not line or line.lstrip().startswith("#"):
            continue

        # Detect indentation
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if indent == 0:
            # Top-level section header, e.g. "backend:"
            if stripped.endswith(":"):
                current_section = stripped[:-1].strip()
                result.setdefault(current_section, {})
            else:
                # Top-level scalar — ignore (not in our schema)
                current_section = None
            continue

        # Indented line — must be inside a section
        if current_section is None:
            continue

        if ":" not in stripped:
            continue

        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()

        # Strip optional quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        else:
            # Strip trailing inline comments (only for unquoted values)
            comment_idx = value.find("#")
            if comment_idx >= 0:
                value = value[:comment_idx].rstrip()

        if key:
            result[current_section][key] = value

    return result


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, dict[str, str]] = {
    "backend": {
        "type": "mock",
        "url": "",
        "model": "",
        "agent": "",
    },
    "voice": {
        "stt": "",
        "tts": "",
    },
    "server": {
        "host": "127.0.0.1",
        "port": "8765",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_config_path() -> str | None:
    """Return the config file path, or None if no file exists.

    Checks QANTARA_CONFIG env var first, then repo-root qantara.yml.
    """
    env_path = os.environ.get("QANTARA_CONFIG", "").strip()
    if env_path:
        if os.path.isfile(env_path):
            return env_path
        return None

    repo_root = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(repo_root, "qantara.yml")
    if os.path.isfile(default_path):
        return default_path
    return None


def load_config(path: str | None = None) -> dict[str, dict[str, str]]:
    """Load and return the merged config: defaults ← config file.

    If *path* is None, calls find_config_path() to locate the file.
    Returns a dict with sections: backend, voice, server.
    Values from the file override defaults; missing keys keep defaults.
    """
    # Start with a deep copy of defaults
    merged: dict[str, dict[str, str]] = {
        section: dict(values) for section, values in DEFAULTS.items()
    }

    if path is None:
        path = find_config_path()

    if path is not None and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            file_cfg = _parse_simple_yaml(f.read())

        for section, values in file_cfg.items():
            if section in merged:
                for key, value in values.items():
                    if key in merged[section] and value:
                        merged[section][key] = value

    return merged
