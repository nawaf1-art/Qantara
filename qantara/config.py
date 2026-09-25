"""Qantara launcher configuration: ``qantara.yml`` loading and env parsing.

The launcher (``qantara`` / ``python cli.py``) reads an optional YAML file of
this shape:

    backend:
      type: ollama
      url: http://localhost:11434
      model: qwen3.5:2b
      agent: main

    voice:
      stt: faster_whisper
      tts: kokoro

    server:
      host: 127.0.0.1
      port: 8765

Startup precedence (highest wins):
explicit CLI flags > environment variables > selected YAML file > built-in defaults.

File selection: ``--config PATH``, else ``QANTARA_CONFIG``, else ``qantara.yml``
in the current directory, else ``qantara.yml`` in the source checkout root.
A path given explicitly (flag or ``QANTARA_CONFIG``) must exist.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "ConfigError",
    "DEFAULTS",
    "env_float",
    "env_int",
    "find_config_path",
    "load_config",
    "parse_simple_yaml",
]


class ConfigError(ValueError):
    """Raised for invalid launcher configuration; the message names the source."""


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    environ: dict[str, str] | None = None,
) -> int:
    """Read an integer environment variable, naming the variable on failure."""
    source = os.environ if environ is None else environ
    raw = source.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw, 10)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    _check_range(name, value, minimum, maximum)
    return value


def env_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    environ: dict[str, str] | None = None,
) -> float:
    """Read a finite float environment variable, naming the variable on failure."""
    source = os.environ if environ is None else environ
    raw = source.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise ConfigError(f"{name} must be a finite number, got {raw!r}")
    _check_range(name, value, minimum, maximum)
    return value


def _check_range(name: str, value: float, minimum: float | None, maximum: float | None) -> None:
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}, got {value}")


# ---------------------------------------------------------------------------
# Minimal YAML parser — the two-level scalar subset above, no dependencies.
# ---------------------------------------------------------------------------


def _strip_comment(text: str) -> str:
    """Remove a YAML comment: '#' at the start or preceded by whitespace."""
    for index, char in enumerate(text):
        if char == "#" and (index == 0 or text[index - 1] in " \t"):
            return text[:index].rstrip()
    return text.rstrip()


def _parse_scalar(raw: str, where: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    quote = value[0]
    if quote not in ('"', "'"):
        return _strip_comment(value)

    chars: list[str] = []
    index = 1
    while index < len(value):
        char = value[index]
        if quote == "'" and char == "'":
            if value[index + 1 : index + 2] == "'":  # '' escapes a single quote
                chars.append("'")
                index += 2
                continue
            break
        if quote == '"' and char == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            chars.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(escaped, "\\" + escaped))
            index += 2
            continue
        if quote == '"' and char == '"':
            break
        chars.append(char)
        index += 1
    else:
        raise ConfigError(f"{where}: unterminated {quote} quoted value")

    remainder = value[index + 1 :]
    if _strip_comment(remainder):
        raise ConfigError(f"{where}: unexpected text after quoted value: {remainder.strip()!r}")
    return "".join(chars)


def parse_simple_yaml(text: str, *, source: str = "config") -> dict[str, dict[str, str]]:
    """Parse a two-level YAML mapping with scalar values.

    Returns ``{"section": {"key": "value"}}``. Comments (``#`` at line start or
    after whitespace) and blank lines are ignored; single- and double-quoted
    values keep ``#`` characters. Unsupported structure raises ConfigError.
    """
    result: dict[str, dict[str, str]] = {}
    current_section: str | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        where = f"{source}:{line_number}"
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip())]:
            raise ConfigError(f"{where}: indent with spaces, not tabs")
        line = _strip_comment(raw_line) if raw_line.lstrip().startswith("#") else raw_line.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        key, separator, rest = stripped.partition(":")
        key = key.strip()
        if not separator or not key:
            raise ConfigError(f"{where}: expected 'key: value'")

        if indent == 0:
            if _strip_comment(rest):
                raise ConfigError(f"{where}: top-level key {key!r} must be a section, not a value")
            current_section = key
            result.setdefault(current_section, {})
            continue

        if current_section is None:
            raise ConfigError(f"{where}: indented key {key!r} has no section")
        result[current_section][key] = _parse_scalar(rest, where)

    return result


# Backwards-compatible alias for the previous private helper name.
_parse_simple_yaml = parse_simple_yaml


# ---------------------------------------------------------------------------
# Defaults and loading
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


def _source_checkout_root() -> Path | None:
    root = Path(__file__).resolve().parent.parent
    return root if (root / "pyproject.toml").is_file() else None


def find_config_path(explicit: str | None = None) -> str | None:
    """Return the config file to load, or None when no file applies.

    Raises ConfigError when an explicitly requested file (``explicit`` or
    ``QANTARA_CONFIG``) does not exist.
    """
    for label, requested in (("--config", explicit), ("QANTARA_CONFIG", os.environ.get("QANTARA_CONFIG"))):
        requested = (requested or "").strip()
        if requested:
            if not os.path.isfile(requested):
                raise ConfigError(f"{label} file not found: {requested}")
            return requested

    candidates = [Path.cwd() / "qantara.yml"]
    root = _source_checkout_root()
    if root is not None:
        candidates.append(root / "qantara.yml")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _warn(message: str) -> None:
    print(f"[qantara] warning: {message}", file=sys.stderr, flush=True)


def load_config(path: str | None = None, *, include_defaults: bool = True) -> dict[str, dict[str, str]]:
    """Load the merged config: defaults <- config file.

    ``path`` is the explicit ``--config`` value (or None to search). Unknown
    sections or keys produce a warning and are ignored. With
    ``include_defaults=False`` keys absent from the file are empty strings, so
    callers can tell file values from built-in defaults.
    """
    merged: dict[str, dict[str, str]] = {
        section: {key: (value if include_defaults else "") for key, value in values.items()}
        for section, values in DEFAULTS.items()
    }

    selected = find_config_path(path)
    if selected is None:
        return merged

    try:
        text = Path(selected).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"could not read config file {selected}: {exc}") from exc
    file_cfg = parse_simple_yaml(text, source=selected)

    for section, values in file_cfg.items():
        if section not in merged:
            _warn(f"{selected}: unknown config section {section!r} ignored")
            continue
        for key, value in values.items():
            if key not in merged[section]:
                _warn(f"{selected}: unknown config key {section}.{key} ignored")
                continue
            if value:
                merged[section][key] = value

    port = merged["server"]["port"]
    if not port:
        return merged
    try:
        port_number = int(port, 10)
    except ValueError:
        raise ConfigError(f"{selected}: server.port must be an integer, got {port!r}") from None
    if not 0 < port_number < 65536:
        raise ConfigError(f"{selected}: server.port must be between 1 and 65535, got {port_number}")
    return merged
